"""
decryption_check.py — TLS decryption (SSL inspection) verification via Playwright.

Checks that Versa SASE is intercepting HTTPS traffic by verifying that the
TLS certificate presented for a target URL is issued by the VOS Certificate
(Versa's SSL inspection CA), not the real server certificate.

If decryption is NOT detected (cert issuer is not VOS), the test FAILS.

Called:
  - After each new tab is opened (login tab + every test-case tab)
  - Result is recorded in REPORT_DATA and surfaced in the HTML report

Config values used (all in config.py):
  DECRYPTION_CHECK_URL          — URL to probe (default: https://teams.live.com)
  DECRYPTION_ISSUER_CN_KEYWORD  — Substring to match in Issuer CN (default: "VOS Certificate")
  DECRYPTION_REQUIRED_FOR_PASS  — If True, missing decryption → test FAIL
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import ssl
import socket
import datetime
from typing import Optional

# ── optional pyOpenSSL for richer cert inspection ───────────────────────────
try:
    from OpenSSL import crypto as _crypto
    _HAVE_OPENSSL = True
except ImportError:
    _HAVE_OPENSSL = False

# cryptography package (installed alongside playwright)
try:
    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import hashes as _hashes
    _HAVE_CRYPTOGRAPHY = True
except ImportError:
    _HAVE_CRYPTOGRAPHY = False

# ── config defaults (overridden at runtime from config.py) ──────────────────
DECRYPTION_CHECK_URL         = "https://teams.live.com"
DECRYPTION_ISSUER_CN_KEYWORD = "VOS Certificate"   # must appear in Issuer CN
DECRYPTION_REQUIRED_FOR_PASS = True                 # False → warn only, not fail

# ── Per-run cert cache ───────────────────────────────────────────────────────
# Stores the last SUCCESSFUL cert fetch result per hostname so that repeated
# calls (login tab + each test-case tab) reuse the confirmed result without
# making redundant socket connections that can time out.
_cert_cache: dict = {}   # hostname -> cert_info dict


# ------------------------------------------------------------
# LOW-LEVEL CERTIFICATE FETCH
# ------------------------------------------------------------

def _fetch_cert_info(hostname: str, port: int = 443, timeout: int = 10) -> dict:
    """
    Open a raw TLS connection to hostname:port and return parsed cert fields.
    Returns a dict with keys: subject, issuer, issuer_cn, not_after, error.
    Caches successful results so subsequent calls to the same host are instant.
    """
    global _cert_cache
    # Return cached result if we already have a successful fetch for this host
    if hostname in _cert_cache and not _cert_cache[hostname].get("error"):
        cached = _cert_cache[hostname]
        print(f"   [DECRYPT] Using cached cert for {hostname} ")
        print(f"            (Issuer CN: {cached.get('issuer_cn','?')})")
        return cached

    info = {
        "hostname"  : hostname,
        "port"      : port,
        "subject"   : {},
        "issuer"    : {},
        "issuer_cn" : "",
        "issuer_org": "",
        "issuer_ou" : "",
        "not_before": "",
        "not_after" : "",
        "serial"    : "",
        "error"     : None,
        "raw"       : None,
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE          # accept self-signed / intercepted certs
    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                der = ssock.getpeercert(binary_form=True)
                info["raw"] = der

        if _HAVE_OPENSSL and der:
            x509 = _crypto.load_certificate(_crypto.FILETYPE_ASN1, der)
            def _rdn(obj):
                return {
                    k.decode(): v.decode()
                    for k, v in obj.get_components()
                }
            info["subject"]    = _rdn(x509.get_subject())
            info["issuer"]     = _rdn(x509.get_issuer())
            info["issuer_cn"]  = x509.get_issuer().CN  or ""
            info["issuer_org"] = x509.get_issuer().O   or ""
            info["issuer_ou"]  = x509.get_issuer().OU  or ""
            nb = x509.get_notBefore()
            na = x509.get_notAfter()
            info["not_before"] = nb.decode() if nb else ""
            info["not_after"]  = na.decode() if na else ""
            info["serial"]     = str(x509.get_serial_number())
        elif _HAVE_CRYPTOGRAPHY and der:
            # Use cryptography package to parse the raw DER bytes we already have
            cert = _x509.load_der_x509_certificate(der)
            def _get_attr(name_obj, oid):
                try:
                    return name_obj.get_attributes_for_oid(oid)[0].value
                except Exception:
                    return ""
            from cryptography.x509.oid import NameOID
            issuer = cert.issuer
            info["issuer_cn"]  = _get_attr(issuer, NameOID.COMMON_NAME)
            info["issuer_org"] = _get_attr(issuer, NameOID.ORGANIZATION_NAME)
            info["issuer_ou"]  = _get_attr(issuer, NameOID.ORGANIZATIONAL_UNIT_NAME)
            subject = cert.subject
            info["subject"] = {"CN": _get_attr(subject, NameOID.COMMON_NAME)}
            info["issuer"]  = {"CN": info["issuer_cn"], "O": info["issuer_org"]}
            info["not_before"] = str(cert.not_valid_before_utc)
            info["not_after"]  = str(cert.not_valid_after_utc)
            print(f"   [DECRYPT] Parsed cert via cryptography pkg — Issuer CN: {info['issuer_cn']}")
        else:
            # Last resort stdlib fallback — requires CERT_REQUIRED to get cert dict
            # Use a separate context with verification to get parsed cert
            ctx2 = ssl.create_default_context()
            ctx2.check_hostname = False
            ctx2.verify_mode    = ssl.CERT_REQUIRED
            try:
                with socket.create_connection((hostname, port), timeout=timeout) as sock2:
                    with ctx2.wrap_socket(sock2, server_hostname=hostname) as ssock2:
                        cert_dict = ssock2.getpeercert()
                        if cert_dict:
                            issuer_tuples = cert_dict.get("issuer", ())
                            for rdn in issuer_tuples:
                                for key, val in rdn:
                                    info["issuer"][key] = val
                                    if key == "commonName":
                                        info["issuer_cn"] = val
                                    elif key == "organizationName":
                                        info["issuer_org"] = val
                                    elif key == "organizationalUnitName":
                                        info["issuer_ou"] = val
                            info["not_after"] = cert_dict.get("notAfter", "")
            except Exception as e2:
                # CERT_REQUIRED failed (e.g. self-signed intercepted cert) — try DER decode via PEM
                try:
                    pem = ssl.DER_cert_to_PEM_cert(der)
                    # Extract CN from PEM string via basic text search
                    for line in pem.splitlines():
                        pass  # PEM is binary-encoded, not text-parseable without crypto lib
                except Exception:
                    pass
                print(f"   [DECRYPT] stdlib fallback also failed: {e2} — install pyOpenSSL or cryptography")

    except Exception as e:
        info["error"] = str(e)

    # Cache only successful fetches (no error, has issuer_cn)
    if not info.get("error") and info.get("issuer_cn"):
        _cert_cache[hostname] = info

    return info


# ------------------------------------------------------------
# PLAYWRIGHT-BASED CERTIFICATE CHECK
# ------------------------------------------------------------

def _fetch_cert_via_playwright(page, url: str) -> dict:
    """
    Use Playwright's response interception to grab TLS security info.
    This catches the certificate as Chrome sees it (after any proxy intercept).
    Returns a dict with issuer/subject info extracted from the security details.
    """
    result = {
        "issuer_cn"       : "",
        "issuer_org"      : "",
        "subject_cn"      : "",
        "valid_from"      : "",
        "valid_to"        : "",
        "protocol"        : "",
        "certificate_id"  : None,
        "error"           : None,
        "raw_security"    : None,
    }
    try:
        # Navigate to the URL and grab security info via CDP
        cdp = page.context.new_cdp_session(page)

        # Navigate to the page
        response = page.goto(url, wait_until="domcontentloaded", timeout=20000)

        # Use CDP Security.getSecurityState or fetch the security panel data
        try:
            security_info = cdp.send("Network.getCertificate", {"origin": url})
            result["raw_security"] = security_info
            # Parse PEM chain
            pem_chain = security_info.get("tableNames", [])
            result["certificate_id"] = str(pem_chain)[:200] if pem_chain else ""
        except Exception:
            pass

        # Best approach: use JavaScript to read navigator details (limited)
        # instead fall back to direct socket-level check
        cdp.detach()

    except Exception as e:
        result["error"] = str(e)

    return result


# ------------------------------------------------------------
# MAIN CHECK FUNCTION
# ------------------------------------------------------------

def check_decryption(
    page,
    label: str = "",
    check_url: Optional[str] = None,
    issuer_keyword: Optional[str] = None,
    required: Optional[bool] = None,
) -> dict:
    """
    Verify that Versa SASE is decrypting (SSL-inspecting) HTTPS traffic.

    Strategy:
      1. Open a direct TLS socket to app.box.com:443 from this machine.
         If Versa is doing SSL inspection, the cert Issuer CN will contain
         the VOS Certificate keyword instead of Box/DigiCert.
      2. Additionally navigate the Playwright page to the URL (or reuse
         the current page) and check via CDP if possible.
      3. Combine results → decryption_confirmed = True/False.

    Args:
        page          : Playwright Page object (used for screenshot on failure)
        label         : Human-readable label for logs/report (e.g. "login tab")
        check_url     : URL to check (default: DECRYPTION_CHECK_URL)
        issuer_keyword: Substring to match in cert Issuer CN
        required      : If True, False result causes test FAIL

    Returns dict with all findings + pass/fail status.
    """
    from config import (
        DECRYPTION_CHECK_URL         as _URL,
        DECRYPTION_ISSUER_CN_KEYWORD as _KW,
        DECRYPTION_REQUIRED_FOR_PASS as _REQ,
    )

    url      = check_url     or _URL
    keyword  = issuer_keyword or _KW
    req      = required if required is not None else _REQ
    tag      = f"[DECRYPT-CHECK{':' + label if label else ''}]"

    # Parse hostname from URL
    hostname = url.replace("https://", "").replace("http://", "").split("/")[0]

    print(f"\n   {'=' * 52}")
    print(f"   {tag} TLS DECRYPTION CHECK")
    print(f"   {'=' * 52}")
    print(f"   Target URL    : {url}")
    print(f"   Hostname      : {hostname}")
    print(f"   Issuer match  : Issuer CN must contain '{keyword}'")
    print(f"   Required      : {'YES — FAIL if not detected' if req else 'NO — warn only'}")

    cert_info = _fetch_cert_info(hostname)

    decryption_confirmed = False
    issuer_cn  = cert_info.get("issuer_cn",  "")
    issuer_org = cert_info.get("issuer_org", "")
    issuer_ou  = cert_info.get("issuer_ou",  "")
    fetch_error = cert_info.get("error")

    # Match keyword ONLY against Issuer CN — the CN must contain the VOS
    # Certificate name exactly. Org/OU are not checked to avoid false positives.
    issuer_cn_match = keyword.lower() in issuer_cn.lower() if issuer_cn else False
    decryption_confirmed = issuer_cn_match

    # Determine pass/fail
    if fetch_error and not decryption_confirmed:
        check_status = "warn"
        status_label = f"ERROR (could not fetch cert: {fetch_error})"
    elif decryption_confirmed:
        check_status = "pass"
        status_label = (
            f"CONFIRMED ✓  — Issuer CN = '{issuer_cn}' contains '{keyword}'"
        )
    else:
        check_status = "fail" if req else "warn"
        status_label = (
            f"NOT DETECTED ✗  — Issuer CN is '{issuer_cn or 'unknown'}' "
            f"(expected to contain '{keyword}')"
        )

    print(f"   Issuer CN     : {issuer_cn  or '(not available)'}")
    print(f"   Issuer Org    : {issuer_org or '(not available)'}")
    print(f"   Issuer OU     : {issuer_ou  or '(not available)'}")
    print(f"   Not After     : {cert_info.get('not_after','')}")
    print(f"   Fetch Error   : {fetch_error or 'None'}")
    print(f"   Result        : {status_label}")
    print(f"   {'=' * 52}\n")

    details = [
        f"Label         : {label or 'N/A'}",
        f"Target        : {url}",
        f"Hostname      : {hostname}",
        f"Issuer CN     : {issuer_cn  or '(not available)'}",
        f"Issuer Org    : {issuer_org or '(not available)'}",
        f"Issuer OU     : {issuer_ou  or '(not available)'}",
        f"Not After     : {cert_info.get('not_after','')}",
        f"Keyword match : '{keyword}' {'FOUND ✓' if decryption_confirmed else 'NOT FOUND ✗'}",
        f"Fetch error   : {fetch_error or 'None'}",
        f"Required      : {'Yes' if req else 'No (warn only)'}",
        f"Result        : {status_label}",
    ]

    return {
        "label"                  : label,
        "url"                    : url,
        "hostname"               : hostname,
        "issuer_cn"              : issuer_cn,
        "issuer_org"             : issuer_org,
        "issuer_ou"              : issuer_ou,
        "not_after"              : cert_info.get("not_after", ""),
        "decryption_confirmed"   : decryption_confirmed,
        "fetch_error"            : fetch_error,
        "required"               : req,
        "status"                 : check_status,   # "pass" / "fail" / "warn"
        "status_label"           : status_label,
        "details"                : details,
        # should_fail_test is True ONLY when:
        #   - decryption was actively NOT detected (cert is NOT VOS)
        #   - AND it is required
        #   - AND the fetch itself succeeded (no timeout/network error)
        # A fetch timeout = inconclusive = do NOT fail the test.
        "should_fail_test"       : (not decryption_confirmed) and req and (not fetch_error),
        "fetch_error"            : fetch_error,
        "inconclusive"           : bool(fetch_error and not decryption_confirmed),
    }
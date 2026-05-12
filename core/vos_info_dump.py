"""
vos_info_dump.py — VOS branch stats clear + info dump.

Two functions:
  run_vos_clear_stats()  — called BEFORE first TC (clears old stats)
  run_vos_info_dump()    — called AFTER all TCs (always, pass or fail)

Clear commands (before TCs):
  request clear statistics ssl profile all
  request clear statistics security decrypt-policy all
  request clear statistics security access-policy all
  request clear statistics security casb profile all

Show commands (after TCs) → written to vos_info_dump.txt:
  1.  Decryption rule config
  2.  Decrypt profile config
  3.  Decrypt profile stats
  4.  Decrypt rule hit count
  5.  CASB profile config
  6.  CASB access-policy rule config
  7.  CASB profile stats
  8.  CASB access-policy rule stats
  9.  CSI information
  10. CSI function list
  11. System package info
  12. Security package information
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import threading
import re
import time
import paramiko
from datetime import datetime

import config as _cfg


OUTPUT_FILENAME = "vos_info_dump.txt"


def vos_dump_file_stem(tc_label: str, activity_name: str) -> str:
    """
    Basename stem for ``vos_dumps/{stem}_vos_dump.txt``.

    Use this anywhere apps pass a ``tc_name`` / poller label so it stays aligned with
    :func:`run_vos_info_dump`, :func:`_append_session_output`, and session / VOS-stats
    ``dump_stem`` verification (same stem as ``runner.py``: ``tc_label`` + ``"_"`` + ``activity_name``).
    """
    return f"{tc_label}_{activity_name}"


def vos_dump_file_stem_from_result(result: dict) -> str:
    """Same as :func:`vos_dump_file_stem` for a TC ``result`` from activity run (tc_label + activity_name)."""
    return vos_dump_file_stem(result["tc_label"], result["activity_name"])


# ------------------------------------------------------------
# SSH HELPERS
# ------------------------------------------------------------

def _ssh_connect() -> paramiko.SSHClient:
    """Open SSH connection to VOS branch. Raises on failure."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    base = dict(
        hostname=_cfg.SSH_HOST, port=_cfg.SSH_PORT,
        username=_cfg.SSH_USER, timeout=10,
        look_for_keys=False, allow_agent=False,
    )
    strategies = []
    if _cfg.SSH_KEY_PATH and _cfg.SSH_PASSWORD:
        strategies += [
            ("key + passphrase", {**base, "key_filename": _cfg.SSH_KEY_PATH, "passphrase": _cfg.SSH_PASSWORD}),
            ("key only",         {**base, "key_filename": _cfg.SSH_KEY_PATH}),
            ("password only",    {**base, "password": _cfg.SSH_PASSWORD}),
        ]
    elif _cfg.SSH_KEY_PATH:
        strategies.append(("key only", {**base, "key_filename": _cfg.SSH_KEY_PATH}))
    else:
        strategies.append(("password only", {**base, "password": _cfg.SSH_PASSWORD}))

    last_err = None
    for label, kwargs in strategies:
        try:
            print(f"   [VOS] SSH trying: {label} ...")
            client.connect(**kwargs)
            print(f"   [VOS] Connected to {_cfg.SSH_HOST}")
            return client
        except Exception as e:
            last_err = e
            print(f"   [VOS] {label} failed: {e}")

    raise ConnectionError(f"All SSH auth strategies failed for {_cfg.SSH_HOST}: {last_err}")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (used by the --More-- pager)."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\[[^a-zA-Z]*[a-zA-Z]', '', text)


def _run_cmd(shell, cmd: str, timeout: int = 30) -> str:
    """
    Send a CLI command and read until the shell prompt reappears.

    Handles the VOS --More-- / (END) pager inline:
      - Sends '!' (show remaining without pagination) on --More--
      - Sends 'q' on (END) to exit the pager
    This prevents pager prompts from bleeding into subsequent commands.
    """
    shell.send(cmd + "\n")
    output = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = shell.recv(4096).decode("utf-8", errors="replace")
            output += chunk
            # Strip ANSI codes before inspecting the last line
            clean = _strip_ansi(output)
            lines = clean.strip().splitlines()
            last = lines[-1] if lines else ""

            # Handle pager prompts before checking for real prompt
            if "--More--" in last or re.search(r'--More--', last):
                shell.send("!")   # dump remaining text without further pagination
                time.sleep(0.3)
                continue
            if "(END)" in last:
                shell.send("q")   # quit the pager
                time.sleep(0.3)
                continue

            if last.endswith(">") or last.endswith("%") or last.endswith("$") or "[ok]" in clean:
                break
        except Exception:
            time.sleep(0.2)
    return output


def _open_shell(client: paramiko.SSHClient):
    """Open interactive shell, enter CLI mode, and disable pagination."""
    # Use a very large height so the terminal never hits the line limit
    # that triggers the --More-- pager.  Pagination-disable commands are
    # also sent but height is the reliable guard.
    shell = client.invoke_shell(width=220, height=9999)
    shell.settimeout(30)
    time.sleep(2)
    if shell.recv_ready():
        shell.recv(4096)  # flush banner
    _run_cmd(shell, "cli", timeout=10)
    time.sleep(1)
    if shell.recv_ready():
        shell.recv(4096)  # flush cli banner
    # Belt-and-suspenders: try both known VOS pagination-disable commands.
    # 'set cli terminal length 0' is the correct JunOS/VOS command;
    # 'set cli more false' may or may not be recognised depending on version.
    for pg_cmd in ("set cli terminal length 0", "set cli more false"):
        _run_cmd(shell, pg_cmd, timeout=10)
        time.sleep(0.3)
    if shell.recv_ready():
        shell.recv(4096)
    return shell


# ------------------------------------------------------------
# VSMD SHELL HELPERS
# ------------------------------------------------------------

def _vsmd_read(shell, timeout: int = 30) -> str:
    """
    Read from an interactive shell until the vsm-vcsn0> prompt appears,
    or until the timeout expires.  Used once after 'vsh connect vsmd' to
    confirm the vsmd shell is ready before sending any commands.

    Returns the raw accumulated buffer (ANSI codes still present).
    """
    prompt   = "vsm-vcsn0>"
    buf      = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if shell.recv_ready():
            chunk = shell.recv(4096).decode("utf-8", errors="replace")
            buf  += chunk
            if prompt in _strip_ansi(buf):
                break
        else:
            time.sleep(0.2)
    return buf


def prepare_vsmd_shell():
    """
    Pre-establish the full SSH -> bash -> vsmd connection BEFORE the message
    is sent, so that when the CASB popup fires the vsmd shell is already
    ready and the session-info command can be fired instantly.

    Call this right before send_message_to() / the Teams send action.
    Pass the returned tuple to run_session_fetch_thread(vsmd_shell=...).

    Returns (client, shell) on success, or None on failure.
    The caller owns the connection — it is closed inside
    fetch_and_append_session_info after the commands complete.
    """
    print(f"   [SESSION-INFO] Pre-connecting vsmd shell...")
    try:
        client = _ssh_connect()
    except Exception as e:
        print(f"   [SESSION-INFO] Pre-connect SSH failed: {e}")
        return None

    try:
        shell = client.invoke_shell(width=220, height=9999)
        shell.settimeout(30)
        time.sleep(2)

        # Read initial prompt
        banner   = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                chunk  = shell.recv(4096).decode("utf-8", errors="replace")
                banner += chunk
                clean  = _strip_ansi(banner).strip()
                last   = clean.splitlines()[-1] if clean.splitlines() else ""
                if last.endswith(">") or last.endswith("%") or last.endswith("$"):
                    break
            except Exception:
                time.sleep(0.2)

        def _drain(sh, wait=1.5):
            time.sleep(wait)
            while sh.recv_ready():
                sh.recv(4096)

        last_line     = _strip_ansi(banner).strip().splitlines()[-1] if _strip_ansi(banner).strip() else ""
        last_stripped = last_line.rstrip()
        if "%" in last_stripped:
            shell.send("exit\n"); _drain(shell)
            shell.send("exit\n"); _drain(shell)
        elif last_stripped.endswith(">"):
            shell.send("exit\n"); _drain(shell)
        # "$" -> already in bash, nothing needed

        # Flush before entering vsmd
        _drain(shell, wait=0.5)
        while shell.recv_ready():
            shell.recv(4096)

        # Enter vsmd
        shell.send("vsh connect vsmd\n")
        vsmd_buf = _vsmd_read(shell, timeout=30)
        if "vsm-vcsn0>" not in _strip_ansi(vsmd_buf):
            raise RuntimeError(f"vsmd prompt not seen: {_strip_ansi(vsmd_buf).strip()[-80:]}")

        print(f"   [SESSION-INFO] vsmd shell ready and waiting.")
        return (client, shell)

    except Exception as e:
        print(f"   [SESSION-INFO] Pre-connect vsmd setup failed: {e}")
        try:
            client.close()
        except Exception:
            pass
        return None


# ------------------------------------------------------------
# FUNCTION 1 — PRE-TEST CLEAR (stats + fast.log)
# ------------------------------------------------------------

def run_pre_test_clear() -> dict:
    """
    Single pre-test clear function — runs in one SSH session:
      1. Clear VOS branch stats (4 commands)
      2. Clear fast.log

    Returns combined result dict with keys:
      success, error, cleared (list), fastlog_cleared, fastlog_error
    """
    result = {
        "success"        : False,
        "error"          : None,
        "cleared"        : [],
        "fastlog_cleared": False,
        "fastlog_error"  : None,
    }

    clear_commands = [
        ("Access-policy stats",  "request clear statistics security access-policy all"),
        ("CASB profile stats",   "request clear statistics security casb profile all"),
        ("Decrypt-policy stats", "request clear statistics security decrypt-policy all"),
        ("SSL profile stats",    "request clear statistics ssl profile all"),
    ]

    print(f"\n{'=' * 55}")
    print("PRE-TEST: Clearing VOS Stats + fast.log")
    print(f"{'=' * 55}")

    try:
        client = _ssh_connect()
    except Exception as e:
        result["error"] = str(e)
        print(f"   [PRE-CLEAR] FATAL: SSH failed — {e}")
        return result

    try:
        shell = _open_shell(client)

        # ── Step 1: Clear VOS stats ───────────────────────────────────
        for label, cmd in clear_commands:
            print(f"   [PRE-CLEAR] {label}...")
            out = _run_cmd(shell, cmd, timeout=20)
            if "cleared" in out.lower() or "success" in out.lower() or "[ok]" in out:
                print(f"   [PRE-CLEAR] ✓ {label}")
                result["cleared"].append(label)
            else:
                print(f"   [PRE-CLEAR] ? {label} — response: {out.strip()[-80:]}")
                result["cleared"].append(f"{label} (response unclear)")

        # ── Step 2: Clear fast.log ────────────────────────────────────
        print(f"   [PRE-CLEAR] Clearing fast.log...")
        out = _run_cmd(shell, "request clear log idp/fast.log", timeout=20)
        if "error" not in out.lower() and "[error]" not in out.lower():
            result["fastlog_cleared"] = True
            print(f"   [PRE-CLEAR] ✓ fast.log cleared")
        else:
            result["fastlog_error"] = out.strip()[-120:]
            print(f"   [PRE-CLEAR] ? fast.log clear response: {out.strip()[-80:]}")

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        print(f"   [PRE-CLEAR] Error: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    print(f"{'=' * 55}\n")
    return result


def run_vos_clear_stats() -> dict:
    """
    Clear old SSL/decrypt/access-policy/CASB stats before TCs run.
    If SSH fails → returns success=False, caller should abort TCs.
    """
    result = {"success": False, "error": None, "cleared": []}

    clear_commands = [
        ("Access-policy stats",         "request clear statistics security access-policy all"),
        ("CASB profile stats",          "request clear statistics security casb profile all"),
        ("Decrypt-policy stats",        "request clear statistics security decrypt-policy all"),
        ("SSL profile stats",           "request clear statistics ssl profile all"),
    ]

    print(f"\n{'=' * 55}")
    print("PRE-TEST: Clearing VOS Stats")
    print(f"{'=' * 55}")

    try:
        client = _ssh_connect()
    except Exception as e:
        result["error"] = str(e)
        print(f"   [VOS-CLEAR] FATAL: SSH failed — {e}")
        return result

    try:
        shell = _open_shell(client)

        for label, cmd in clear_commands:
            print(f"   [VOS-CLEAR] {label}...")
            out = _run_cmd(shell, cmd, timeout=20)
            if "cleared" in out.lower() or "success" in out.lower() or "[ok]" in out:
                print(f"   [VOS-CLEAR] ✓ {label}")
                result["cleared"].append(label)
            else:
                print(f"   [VOS-CLEAR] ? {label} — response: {out.strip()[-80:]}")
                result["cleared"].append(f"{label} (response unclear)")

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        print(f"   [VOS-CLEAR] Error: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    print(f"{'=' * 55}\n")
    return result


# ------------------------------------------------------------
# FUNCTION 1b — QOSMOS PRE-TEST (before first TC)
# ------------------------------------------------------------

def run_qosmos_pretest() -> dict:
    """
    Run once before the first TC.
    If VOS_APPID_REPORT_METADATA is "enable" or "disable":
      - Exits CLI (or config) mode to reach bash shell
      - Runs: vsh connect vsmd  → enters vsm-vcsn0> prompt
      - Runs: set appid report_metadata <enable|disable>
      - Runs: show appid report_metadata  (verify)
    """
    setting = getattr(_cfg, "VOS_APPID_REPORT_METADATA", None)
    result  = {"success": False, "error": None, "setting": setting, "output": ""}

    if setting not in ("enable", "disable"):
        print(f"\n   [QOSMOS] VOS_APPID_REPORT_METADATA not set — skipping.")
        result["success"] = True
        return result

    print(f"\n{'=' * 55}")
    print(f"PRE-TEST: Set appid report_metadata → {setting}")
    print(f"{'=' * 55}")

    def _vsmd_read(shell, prompt="vsm-vcsn0>", timeout=15):
        """Read until a fresh vsm-vcsn0> prompt arrives. Returns raw output."""
        buf = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = shell.recv(4096).decode("utf-8", errors="replace")
                buf += chunk
                # Only break when the prompt appears in THIS chunk (fresh data)
                if prompt in _strip_ansi(chunk):
                    break
            except Exception:
                time.sleep(0.2)
        return buf

    def _vsmd_send_and_read(shell, cmd, timeout=30):
        """
        Send a vsmd command using \\r\\n and robustly read the full response.
        Stops when vsm-vcsn0> found in buffer OR 2s idle after data received.
        Returns content lines with echo and prompt stripped.
        """
        prompt = "vsm-vcsn0>"
        # Drain stale buffer
        time.sleep(0.3)
        while shell.recv_ready():
            shell.recv(65535)
            time.sleep(0.1)

        shell.send(cmd + "\r\n")   # vsmd requires CR+LF

        buf          = ""
        deadline     = time.time() + timeout
        last_data_at = time.time()

        while time.time() < deadline:
            if shell.recv_ready():
                chunk = shell.recv(65535).decode("utf-8", errors="replace")
                buf  += chunk
                last_data_at = time.time()
                if prompt in _strip_ansi(buf):
                    time.sleep(0.3)
                    while shell.recv_ready():
                        buf += shell.recv(65535).decode("utf-8", errors="replace")
                    break
            else:
                if buf and (time.time() - last_data_at) >= 2.0:
                    break
                time.sleep(0.1)

        clean = _strip_ansi(buf)
        return "\n".join(
            ln.strip() for ln in clean.splitlines()
            if ln.strip() and ln.strip() != cmd and prompt not in ln
        )


    try:
        client = _ssh_connect()
    except Exception as e:
        result["error"] = str(e)
        print(f"   [QOSMOS] SSH failed: {e}")
        return result

    try:
        shell = client.invoke_shell(width=220, height=9999)
        shell.settimeout(30)
        time.sleep(2)

        # Read initial banner/prompt to detect mode
        banner = ""
        deadline0 = time.time() + 10
        while time.time() < deadline0:
            try:
                chunk = shell.recv(4096).decode("utf-8", errors="replace")
                banner += chunk
                clean = _strip_ansi(banner).strip()
                last  = clean.splitlines()[-1] if clean.splitlines() else ""
                if last.endswith(">") or last.endswith("%") or last.endswith("$"):
                    break
            except Exception:
                time.sleep(0.2)

        clean_banner = _strip_ansi(banner).strip()
        last_line    = clean_banner.splitlines()[-1] if clean_banner.splitlines() else ""
        print(f"   [QOSMOS] Initial prompt: '{last_line}'")

        # Detect mode robustly and exit to bash:
        #   Config mode  → prompt contains '%'
        #   CLI mode     → prompt ends with '>'
        #   Bash shell   → prompt ends with '$'
        last_stripped = last_line.rstrip()
        if "%" in last_stripped:
            print(f"   [QOSMOS] Config mode — sending 2x exit...")
            for _ in range(2):
                shell.send("exit\n")
                time.sleep(1.5)
                while shell.recv_ready():
                    shell.recv(4096)
        elif last_stripped.endswith(">"):
            print(f"   [QOSMOS] CLI mode — sending 1x exit...")
            shell.send("exit\n")
            time.sleep(1.5)
            while shell.recv_ready():
                shell.recv(4096)
        elif last_stripped.endswith("$"):
            print(f"   [QOSMOS] Already in bash shell — no exit needed")
        else:
            print(f"   [QOSMOS] Unknown prompt '{last_line}' — sending 2x exit defensively")
            for _ in range(2):
                shell.send("exit\n")
                time.sleep(1.5)
                while shell.recv_ready():
                    shell.recv(4096)

        # Final drain before entering vsmd
        time.sleep(0.5)
        while shell.recv_ready():
            shell.recv(4096)

        # Enter vsmd — wait up to 30s for vsm-vcsn0> prompt
        print(f"   [QOSMOS] Running: vsh connect vsmd")
        shell.send("vsh connect vsmd\n")
        vsmd_buf = _vsmd_read(shell, prompt="vsm-vcsn0>", timeout=30)
        if "vsm-vcsn0>" not in _strip_ansi(vsmd_buf):
            raise RuntimeError(
                f"vsh connect vsmd: vsm-vcsn0> prompt not seen. "
                f"Got: {_strip_ansi(vsmd_buf).strip()[-100:]}"
            )
        print(f"   [QOSMOS] vsm-vcsn0> prompt confirmed")

        # Set the value
        set_cmd = f"set appid report_metadata {setting}"
        print(f"   [QOSMOS] Running: {set_cmd}")
        _vsmd_send_and_read(shell, set_cmd, timeout=15)

        # Show current value to verify
        print(f"   [QOSMOS] Running: show appid report_metadata")
        show_out = _vsmd_send_and_read(shell, "show appid report_metadata", timeout=15)
        print(f"   [QOSMOS] Output: {repr(show_out)}")

        # Extract enabled/disabled — the command returns just "disabled" or "enabled"
        # Scan every line of output; also check the full string in case filtering collapsed it
        verify_out = ""
        show_lower = show_out.lower()
        for ln in show_out.splitlines():
            ln_lower = ln.strip().lower()
            if "disabled" in ln_lower:
                verify_out = "disable"
                break
            if "enabled" in ln_lower:
                verify_out = "enable"
                break
        # Last resort: check the whole output string
        if not verify_out:
            if "disabled" in show_lower:
                verify_out = "disable"
            elif "enabled" in show_lower:
                verify_out = "enable"

        verify_normalised = verify_out

        if verify_normalised == setting or verify_out == setting:
            print(f"   [QOSMOS] ✓ Verified: appid report_metadata = {verify_out}")
            result["success"] = True
        else:
            print(f"   [QOSMOS] ✗ Verification failed: expected {setting}, got '{verify_out or show_out[:60]}'")
            result["error"] = f"Expected {setting}, got {verify_out or show_out[:60]}"

        result["output"] = verify_out or show_out

        # Exit vsmd back to bash
        try:
            shell.send("exit\n")
            time.sleep(1)
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)
        print(f"   [QOSMOS] Error: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    print(f"{'=' * 55}\n")
    return result


# ------------------------------------------------------------
# FUNCTION 2 — INFO DUMP (after all TCs)
# ------------------------------------------------------------

def run_vos_info_dump(tc_name: str = "") -> dict:
    """
    Collect VOS branch config + stats after a TC completes.
    Saves to vos_dumps/{tc_name}_vos_dump.txt
    Always runs regardless of TC pass/fail.
    """
    result = {
        "success"    : False,
        "error"      : None,
        "output_file": None,
        "sections"   : {},
    }

    # Read names fresh from config (may have been overridden by CLI args)
    org   = _cfg.VOS_ORG_NAME
    apol  = _cfg.VOS_ACCESS_POLICY_NAME
    dpol  = _cfg.VOS_DECRYPTION_POLICY_NAME
    drule = _cfg.VOS_DECRYPTION_RULE_NAME
    dprof = _cfg.VOS_DECRYPT_PROFILE_NAME
    cprof = _cfg.VOS_CASB_PROFILE_NAME
    crule = _cfg.VOS_CASB_RULE_NAME

    # (title, command, needs_config_mode)
    # CLI commands  → needs_config=False  (ssh → cli)
    # Config commands → needs_config=True  (ssh → cli → config)
    #
    # All CLI show commands get '| nomore' appended as a belt-and-suspenders
    # guard against the VOS pager, in addition to the terminal-height fix in
    # _open_shell.  Config-mode commands already have '| display set' and do
    # not need '| nomore'.
    commands = [
        # ── CLI commands ──────────────────────────────────────────────
        (
            "CASB Access-Policy Rule Statistics",
            f"show orgs org-services {org} security access-policies {apol} "
            f"rules access-policy-stats {crule} | nomore",
            False,
        ),
        (
            "CASB Profile Statistics",
            f"show orgs org-services {org} security profiles casb "
            f"statistics user-defined {cprof} | nomore",
            False,
        ),
        (
            "Decrypt Rule Hit Count",
            f"show orgs org-services {org} security decryption-policies {dpol} "
            f"rules decrypt-policy-stats {drule} | nomore",
            False,
        ),
        (
            "Decrypt Profile Stats",
            f"show orgs org-services {org} security profiles decrypt profile-stats {dprof} | nomore",
            False,
        ),
        (
            "System Package Info",
            "show system package-info | nomore",
            False,
        ),
        (
            "Security Package Information",
            "show security security-package info | nomore",
            False,
        ),
        # ── Config commands ───────────────────────────────────────────
        (
            "CASB Access-Policy Rule Configuration",
            f"show orgs org-services {org} security access-policies {apol} "
            f"rules {crule} | display set",
            True,
        ),
        (
            "CASB Profile Configuration",
            f"show orgs org-services {org} security profiles casb {cprof} | display set",
            True,
        ),
        (
            "Decryption Rule Configuration",
            f"show orgs org-services {org} security decryption-policies {dpol} "
            f"rules {drule} | display set",
            True,
        ),
        (
            "Decrypt Profile Configuration",
            f"show orgs org-services {org} security profiles decrypt {dprof} | display set",
            True,
        ),
    ]

    # ── appid report_metadata via vsmd ───────────────────────────────────
    # Appended separately because vsmd requires a different shell context
    # (vsh connect vsmd → vsm-vcsn0> prompt), separate from the CLI shell.
    def _run_vsmd_appid_section(lines_list: list, sections_dict: dict):
        """Open vsmd shell, run show appid report_metadata, append to dump."""
        try:
            vsmd_client = _ssh_connect()
            vsmd_shell  = vsmd_client.invoke_shell(width=220, height=50)
            vsmd_shell.settimeout(2.0)
            import time as _time

            def _vread(timeout=5.0):
                buf = b""
                deadline = _time.time() + timeout
                while _time.time() < deadline:
                    try:
                        chunk = vsmd_shell.recv(4096)
                        if chunk: buf += chunk
                    except Exception:
                        _time.sleep(0.1)
                return buf.decode("utf-8", errors="replace")

            _vread(2.0)  # banner
            vsmd_shell.send("vsh connect vsmd\n")
            _time.sleep(1.0)
            vsmd_buf = _vread(5.0)
            if "vsm-vcsn0>" not in _strip_ansi(vsmd_buf):
                raise RuntimeError(f"vsmd prompt not seen: {_strip_ansi(vsmd_buf).strip()[-80:]}")

            vsmd_shell.send("show appid report_metadata\r\n")
            _time.sleep(1.0)
            out = _vread(5.0)
            clean = _strip_ansi(out).strip()

            sep = "=" * 70
            lines_list += [
                f"\n{sep}",
                "  appid report_metadata (vsmd)",
                f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                sep,
                "Command: vsh connect vsmd → show appid report_metadata",
                "",
                clean,
                "",
            ]
            sections_dict["appid report_metadata"] = clean
            print(f"   [VOS-DUMP] ✓ appid report_metadata (vsmd)")

            vsmd_shell.send("exit\n")
            _time.sleep(0.3)
            vsmd_client.close()
        except Exception as _e:
            lines_list.append(f"\nappid report_metadata (vsmd): ERROR: {_e}")
            sections_dict["appid report_metadata"] = f"ERROR: {_e}"
            print(f"   [VOS-DUMP] ✗ appid report_metadata (vsmd): {_e}")

    print(f"\n{'=' * 55}")
    print("POST-TEST: VOS Branch Info Dump")
    print(f"{'=' * 55}")
    print(f"   Org             : {org}")
    print(f"   Access Policy   : {apol}")
    print(f"   Decrypt Policy  : {dpol}  /  Rule: {drule}  /  Profile: {dprof}")
    print(f"   CASB Profile    : {cprof}  /  Rule: {crule}")

    try:
        client = _ssh_connect()
    except Exception as e:
        result["error"] = str(e)
        print(f"   [VOS-DUMP] FATAL: SSH failed — {e}")
        # Still write an error file
        _write_output(result, [f"SSH connection failed: {e}"], org, tc_name)
        return result

    lines = []
    lines.append("VOS BRANCH INFO DUMP")
    lines.append(f"Test Case : {tc_name if tc_name else 'N/A'}")
    lines.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Host      : {_cfg.SSH_HOST}")
    lines.append(f"Org       : {org}")
    lines.append(f"Decrypt Policy / Rule / Profile : {dpol} / {drule} / {dprof}")
    lines.append(f"CASB Profile / Rule             : {cprof} / {crule}")
    lines.append("")

    try:
        shell = _open_shell(client)
        in_config = False

        for title, cmd, needs_config in commands:
            print(f"   [VOS-DUMP] {title}...")
            try:
                if needs_config and not in_config:
                    _run_cmd(shell, "configure", timeout=10)
                    in_config = True
                elif not needs_config and in_config:
                    _run_cmd(shell, "exit", timeout=10)
                    in_config = False
                    # Re-apply pagination disable after exiting config mode
                    for pg_cmd in ("set cli terminal length 0", "set cli more false"):
                        _run_cmd(shell, pg_cmd, timeout=10)
                    time.sleep(0.3)

                # Drain any residual buffered data before sending the next
                # command.  Do NOT send any character here — in config mode
                # a stray space triggers tab-completion and produces the
                # "Possible completions" noise seen in the dump output.
                time.sleep(0.3)
                while shell.recv_ready():
                    shell.recv(4096)

                output = _run_cmd(shell, cmd, timeout=60)

                # --More-- / (END) are now handled inside _run_cmd itself.
                # Just do a final drain so nothing leaks into the next command.

                # Strip echoed command line
                clean = "\n".join(
                    ln for ln in output.splitlines()
                    if not ln.strip().startswith(cmd[:30])
                ).strip()

                sep = "=" * 70
                lines += [f"\n{sep}", f"  {title}",
                          f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                          sep, f"Command: {cmd}", "", clean, ""]

                result["sections"][title] = clean
                print(f"   [VOS-DUMP] ✓ {title}")

            except Exception as e:
                lines += [f"\n{'=' * 70}", f"  {title}", "=" * 70,
                          f"Command: {cmd}", f"ERROR: {e}", ""]
                result["sections"][title] = f"ERROR: {e}"
                print(f"   [VOS-DUMP] ✗ {title}: {e}")

        # Exit cleanly
        try:
            if in_config:
                _run_cmd(shell, "exit", timeout=5)
            _run_cmd(shell, "exit", timeout=5)
        except Exception:
            pass

        # ── appid report_metadata via vsmd ────────────────────────
        _run_vsmd_appid_section(lines, result["sections"])

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        lines.append(f"\nFATAL ERROR: {e}")
        print(f"   [VOS-DUMP] Fatal: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    # ── Extract spack version from "show security security-package info" ─
    # Output looks like:
    #   Version             7452
    #   API Version         11
    #   Flavor              premium
    #   Release Date        2026-03-17
    #   Update Type         full
    # We want the "Version" line (not "API Version").
    spack_raw     = result["sections"].get("Security Package Information", "")
    spack_version = ""
    spack_flavor  = ""
    spack_date    = ""
    for line in spack_raw.splitlines():
        stripped = line.strip()
        lower    = stripped.lower()
        # "Version" only — not "API Version"
        if lower.startswith("version") and "api" not in lower:
            parts = stripped.split()
            if len(parts) >= 2:
                spack_version = parts[-1]
        elif lower.startswith("flavor"):
            parts = stripped.split()
            if len(parts) >= 2:
                spack_flavor = parts[-1]
        elif lower.startswith("release date"):
            parts = stripped.split()
            if len(parts) >= 1:
                spack_date = parts[-1]
    if spack_version:
        _cfg.REPORT_DATA["config"]["spack_version"] = spack_version
        _cfg.REPORT_DATA["config"]["spack_flavor"]  = spack_flavor
        _cfg.REPORT_DATA["config"]["spack_date"]    = spack_date
        print(f"   [VOS-DUMP] SPACK {spack_version}")

    _write_output(result, lines, org, tc_name)
    print(f"{'=' * 55}\n")
    return result





# ------------------------------------------------------------
# FUNCTION 4 — POLL SESSION HANDLE (background, before send)
# ------------------------------------------------------------

def start_session_handle_poller(timeout: int = 30):
    """
    Start a background thread that polls 'show identity alerts contexts'
    repeatedly until a non-zero sdata.sess_hdl is found or timeout expires.

    Call this BEFORE clicking Send/Post — so polling is already running
    when the CASB block fires and sess_hdl appears.

    Returns a dict with keys:
      stop()       — call to stop polling early
      get_result() — returns (alert_output, sess_hdl_hex) or (None, None)
    """
    import threading

    state = {
        "alert_output": None,
        "sess_hdl"    : None,
        "done"        : False,
        "attempts"    : 0,
    }
    stop_event = threading.Event()

    def _poll():
        print(f"   [SESSION-POLL] Starting background poll (timeout={timeout}s)...")
        try:
            client = _ssh_connect()
        except Exception as e:
            print(f"   [SESSION-POLL] SSH failed: {e}")
            state["done"] = True
            return

        try:
            shell = client.invoke_shell(width=220, height=9999)
            shell.settimeout(30)
            time.sleep(2)

            # Drain banner
            deadline0 = time.time() + 10
            banner = ""
            while time.time() < deadline0:
                try:
                    chunk = shell.recv(4096).decode("utf-8", errors="replace")
                    banner += chunk
                    clean = _strip_ansi(banner).strip()
                    last  = clean.splitlines()[-1] if clean.splitlines() else ""
                    if last.endswith(">") or last.endswith("%") or last.endswith("$"):
                        break
                except Exception:
                    time.sleep(0.2)

            def _drain(sh, wait=1.0):
                time.sleep(wait)
                while sh.recv_ready():
                    sh.recv(4096)

            last_line = _strip_ansi(banner).strip().splitlines()[-1] if _strip_ansi(banner).strip() else ""
            last_stripped = last_line.rstrip()
            if "%" in last_stripped:
                shell.send("exit\n"); _drain(shell)
                shell.send("exit\n"); _drain(shell)
            elif last_stripped.endswith(">"):
                shell.send("exit\n"); _drain(shell)

            _drain(shell, wait=0.5)
            while shell.recv_ready():
                shell.recv(4096)

            # Enter vsmd
            shell.send("vsh connect vsmd\n")
            vsmd_buf = _vsmd_read(shell, timeout=30)
            if "vsm-vcsn0>" not in _strip_ansi(vsmd_buf):
                print(f"   [SESSION-POLL] vsmd prompt not seen — aborting poll")
                state["done"] = True
                return

            print(f"   [SESSION-POLL] vsmd ready — polling started")

            def _vsmd_cmd_poll(sh, cmd, timeout=10):
                time.sleep(0.1)
                while sh.recv_ready():
                    sh.recv(65535)
                sh.send(cmd + "\r\n")
                buf, deadline, last_data_at = "", time.time() + timeout, time.time()
                prompt = "vsm-vcsn0>"
                while time.time() < deadline:
                    if sh.recv_ready():
                        chunk = sh.recv(65535).decode("utf-8", errors="replace")
                        buf += chunk
                        last_data_at = time.time()
                        if prompt in _strip_ansi(buf):
                            time.sleep(0.1)
                            while sh.recv_ready():
                                buf += sh.recv(65535).decode("utf-8", errors="replace")
                            break
                    else:
                        if buf and (time.time() - last_data_at) >= 1.5:
                            break
                        time.sleep(0.05)
                clean = _strip_ansi(buf)
                return "\n".join(
                    ln.strip() for ln in clean.splitlines()
                    if ln.strip() and ln.strip() != cmd and prompt not in ln
                )

            deadline = time.time() + timeout
            while time.time() < deadline and not stop_event.is_set():
                state["attempts"] += 1
                out = _vsmd_cmd_poll(shell, "show identity alerts contexts")
                hdl_match = re.search(r'sdata\.sess_hdl\s*:\s*(0x[\da-f]+|\d+)', out)
                hdl_val = hdl_match.group(1) if hdl_match else "0"
                hdl_hex = hdl_val if hdl_val.startswith("0x") else hex(int(hdl_val) if hdl_val.isdigit() else 0)
                print(f"   [SESSION-POLL] Attempt {state['attempts']}: sess_hdl = {hdl_hex}")
                for line in out.splitlines():
                    print(f"      {line}")
                if hdl_hex not in ("0x0", "0x00"):
                    state["alert_output"] = out
                    state["sess_hdl"]     = hdl_hex
                    print(f"   [SESSION-POLL] ✓ Valid sess_hdl captured: {hdl_hex} (attempt {state['attempts']})")

                    # Inline session dump: fire grep + handle commands immediately
                    # on this warm vsmd shell. sdata.sess_hdl is valid for only
                    # a few milliseconds — any thread handoff is too slow.
                    session_lines = [
                        "",
                        "=" * 70,
                        "  SESSION INFO (captured inline by poller)",
                        f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"  sess_hdl  : {hdl_hex}  (attempt {state['attempts']})",
                        "=" * 70,
                        "",
                        "Command: show identity alerts contexts",
                        out,
                    ]

                    grep_cmd = f"show vsf session all extensive | grep {hdl_hex}"
                    print(f"   [SESSION-POLL] Running: {grep_cmd}")
                    grep_out = _vsmd_cmd_poll(shell, grep_cmd, timeout=30)
                    print(f"   [SESSION-POLL] grep output: {grep_out}")
                    session_lines += ["", f"Command: {grep_cmd}", grep_out]

                    # grep output: "Session ID: 8201346b (0x7effaf1a5b01) (NFP), ..."
                    # extract the short handle before the parenthesised full handle
                    short_match = re.search(r'Session ID:\s*([0-9a-f]+)\s*\(', grep_out)
                    if short_match:
                        short_hdl = short_match.group(1)
                        ext_cmd = f"show vsf session handle extensive 0x{short_hdl}"
                        print(f"   [SESSION-POLL] Running: {ext_cmd}")
                        ext_out = _vsmd_cmd_poll(shell, ext_cmd, timeout=20)
                        print(f"   [SESSION-POLL] extensive output: {ext_out}")
                        session_lines += ["", f"Command: {ext_cmd}", ext_out]
                    else:
                        session_lines.append(f"Could not extract short handle from grep output: {grep_out}")

                    state["session_lines"] = session_lines
                    print(f"   [SESSION-POLL] Inline session dump complete")
                    break
                time.sleep(0.05)  # 50ms between polls

            if not state["sess_hdl"]:
                print(f"   [SESSION-POLL] sess_hdl remained 0 after {state['attempts']} attempts")

        except Exception as e:
            print(f"   [SESSION-POLL] Error: {e}")
        finally:
            try:
                shell.send("exit\n")
                time.sleep(0.5)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            state["done"] = True

    t = threading.Thread(target=_poll, daemon=True)
    t.start()

    def stop():
        stop_event.set()

    def get_result(join_timeout=None):
        # Default to timeout+5 when called without a limit (e.g. from tests).
        # _after_send passes join_timeout=3 so it doesn't block waiting for the
        # in-flight vsmd command to return before starting the session fetch thread.
        t.join(timeout=join_timeout if join_timeout is not None else timeout + 5)
        return (
            state["alert_output"],
            state["sess_hdl"],
            state["attempts"],
            state.get("session_lines"),   # None if poller didn't catch sess_hdl
        )

    return {"stop": stop, "get_result": get_result, "thread": t}

# ------------------------------------------------------------
# FUNCTION 3 — FETCH SESSION INFO (during popup, per TC)
# ------------------------------------------------------------

def fetch_and_append_session_info(tc_name: str, stop_event=None, vsmd_shell=None,
                                   alert_output=None, sess_hdl=None):
    """
    Appends session info to the TC vos_dump file.
    If alert_output and sess_hdl are provided (from poller), uses them directly.
    Otherwise falls back to retrying on vsmd_shell for up to 5 seconds.
    """
    import threading as _threading
    if stop_event is None:
        stop_event = _threading.Event()
    print(f"\n   [SESSION-INFO] Starting session fetch for {tc_name}...")

    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  SESSION INFO (captured during CASB popup)")
    lines.append(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    # ── Use pre-connected shell (fast path) or connect fresh (slow fallback) ──
    if vsmd_shell is not None:
        client, shell = vsmd_shell
        print(f"   [SESSION-INFO] Using pre-connected vsmd shell — firing immediately.")
    else:
        print(f"   [SESSION-INFO] No pre-connected shell — connecting from scratch (may be too slow).")
        try:
            client = _ssh_connect()
        except Exception as e:
            lines.append(f"SSH connection failed: {e}")
            _append_session_output(tc_name, lines)
            return

    def _vsmd_cmd(shell, cmd, timeout=30):
        """Robust vsmd command using CR+LF - reads until prompt or 2s idle."""
        time.sleep(0.3)
        while shell.recv_ready():
            shell.recv(65535)
            time.sleep(0.1)
        shell.send(cmd + "\r\n")   # vsmd requires CR+LF
        buf, deadline, last_data_at = "", time.time() + timeout, time.time()
        prompt = "vsm-vcsn0>"
        while time.time() < deadline:
            if shell.recv_ready():
                chunk = shell.recv(65535).decode("utf-8", errors="replace")
                buf  += chunk
                last_data_at = time.time()
                if prompt in _strip_ansi(buf):
                    time.sleep(0.3)
                    while shell.recv_ready():
                        buf += shell.recv(65535).decode("utf-8", errors="replace")
                    break
            else:
                if buf and (time.time() - last_data_at) >= 2.0:
                    break
                time.sleep(0.1)
        clean = _strip_ansi(buf)
        return "\n".join(
            ln.strip() for ln in clean.splitlines()
            if ln.strip() and ln.strip() != cmd and prompt not in ln
        )

    try:
        if vsmd_shell is None:
            # Slow fallback path: build shell from scratch
            shell = client.invoke_shell(width=220, height=9999)
            shell.settimeout(30)
            time.sleep(2)

            banner = ""
            deadline0 = time.time() + 10
            while time.time() < deadline0:
                try:
                    chunk = shell.recv(4096).decode("utf-8", errors="replace")
                    banner += chunk
                    clean = _strip_ansi(banner).strip()
                    last  = clean.splitlines()[-1] if clean.splitlines() else ""
                    if last.endswith(">") or last.endswith("%"):
                        break
                except Exception:
                    time.sleep(0.2)

            clean_banner = _strip_ansi(banner).strip()
            last_line    = clean_banner.splitlines()[-1] if clean_banner.splitlines() else ""
            print(f"   [SESSION-INFO] Initial prompt: '{last_line}'")

            def _drain(sh, wait=1.5):
                time.sleep(wait)
                while sh.recv_ready():
                    sh.recv(4096)

            last_stripped = last_line.rstrip()
            if "%" in last_stripped:
                print(f"   [SESSION-INFO] Config mode detected — sending 2x exit")
                shell.send("exit\n"); _drain(shell)
                shell.send("exit\n"); _drain(shell)
            elif last_stripped.endswith(">"):
                print(f"   [SESSION-INFO] CLI mode detected — sending 1x exit")
                shell.send("exit\n"); _drain(shell)
            elif last_stripped.endswith("$"):
                print(f"   [SESSION-INFO] Already in bash shell — no exit needed")
            else:
                print(f"   [SESSION-INFO] Unknown prompt '{last_line}' — sending 2x exit defensively")
                shell.send("exit\n"); _drain(shell)
                shell.send("exit\n"); _drain(shell)

            _drain(shell, wait=0.5)
            while shell.recv_ready():
                shell.recv(4096)

            print(f"   [SESSION-INFO] Entering vsh connect vsmd...")
            shell.send("vsh connect vsmd\n")
            vsmd_buf = _vsmd_read(shell, timeout=30)
            if "vsm-vcsn0>" not in _strip_ansi(vsmd_buf):
                raise RuntimeError(f"vsh connect vsmd failed. Got: {_strip_ansi(vsmd_buf).strip()[-100:]}")
            print(f"   [SESSION-INFO] vsm-vcsn0> prompt confirmed")

        # Step 1 — Use pre-captured alert output from poller if available
        # The poller started before the send click and polled continuously
        # until a valid sess_hdl appeared. If it caught one, use it directly.
        if alert_output and sess_hdl and sess_hdl not in ("0x0", "0x00"):
            print(f"   [SESSION-INFO] Using pre-captured data from poller (sess_hdl={sess_hdl})")
            lines.append("")
            lines.append("Command: show identity alerts contexts (captured by pre-send poller)")
            lines.append(alert_output)
        else:
            # Poller did not catch a valid handle — retry aggressively for 5 more seconds.
            # IMPORTANT: at this point `shell` is always a live vsmd shell — either the
            # pre-connected one passed in as vsmd_shell, or the one we just built above in
            # the slow-path branch.  The old code guarded this loop with
            # `if vsmd_shell is not None:` which checked the *parameter* (None when the
            # slow path ran) and silently skipped all retries — causing "0 attempt(s)".
            print(f"   [SESSION-INFO] Poller missed sess_hdl — retrying for up to 5s...")
            fallback_out = ""
            fallback_attempts = 0
            fallback_deadline = time.time() + 5.0
            found_hdl = None
            while time.time() < fallback_deadline:
                fallback_attempts += 1
                out = _vsmd_cmd(shell, "show identity alerts contexts", timeout=8)
                hdl_m = re.search(r'sdata\.sess_hdl\s*:\s*(0x[\da-f]+|\d+)', out)
                hdl_v = hdl_m.group(1) if hdl_m else "0"
                hdl_h = hdl_v if hdl_v.startswith("0x") else hex(int(hdl_v) if hdl_v.isdigit() else 0)
                print(f"   [SESSION-INFO] Fallback attempt {fallback_attempts}: sess_hdl = {hdl_h}")
                fallback_out = out
                if hdl_h not in ("0x0", "0x00"):
                    found_hdl = hdl_h
                    sess_hdl = hdl_h
                    print(f"   [SESSION-INFO] ✓ Caught sess_hdl on fallback attempt {fallback_attempts}: {hdl_h}")
                    break
                time.sleep(0.05)
            else:
                print(f"   [SESSION-INFO] sess_hdl remained 0 after {fallback_attempts} fallback attempts")
            alert_output = fallback_out or alert_output or ""
            lines.append("")
            lines.append(f"Command: show identity alerts contexts (fallback — {fallback_attempts} attempt(s))")
            lines.append(alert_output if alert_output else "(no output)")

        # Step 2 — Use pre-captured sess_hdl from poller, or extract from alert_output
        if not sess_hdl or sess_hdl in ("0x0", "0x00"):
            # Try to extract from alert_output as last resort
            import re as _re2
            hdl_match = _re2.search(r'sdata\.sess_hdl\s*:\s*(0x[\da-f]+|\d+)', alert_output or "")
            hdl_val = hdl_match.group(1) if hdl_match else "0"
            sess_hdl = hdl_val if hdl_val.startswith("0x") else hex(int(hdl_val) if hdl_val.isdigit() else 0)

        if not sess_hdl or sess_hdl in ("0x0", "0x00"):
            lines.append("")
            lines.append("sess_hdl = 0 — could not capture valid session handle (session expired before poller caught it)")
            _append_session_output(tc_name, lines)
            return

        print(f"   [SESSION-INFO] Using sess_hdl={sess_hdl} — grepping session table...")
        grep_cmd = f"show vsf session all extensive | grep {sess_hdl}"
        grep_output = _vsmd_cmd(shell, grep_cmd, timeout=30)
        lines.append("")
        lines.append(f"Command: {grep_cmd}")
        lines.append(grep_output)

        # Extract short handle from: Session ID: 20046aa (0x7f8dbf178c02)
        short_handles = re.findall(r'Session ID:\s*([\da-f]+)\s*\(', grep_output)
        if not short_handles:
            lines.append(f"No short handle found for sess_hdl={sess_hdl}")
            _append_session_output(tc_name, lines)
            return

        for short_hdl in short_handles:
            ext_cmd = f"show vsf session handle extensive 0x{short_hdl}"
            print(f"   [SESSION-INFO] Running {ext_cmd}...")
            ext_output = _vsmd_cmd(shell, ext_cmd, timeout=20)
            lines.append("")
            lines.append(f"Command: {ext_cmd}")
            lines.append(ext_output)

        # Exit vsmd → back to bash
        try:
            shell.send("exit\n")
            time.sleep(1)
        except Exception:
            pass

        print(f"   [SESSION-INFO] Done for {tc_name}")

    except Exception as e:
        lines.append(f"ERROR during session fetch: {e}")
        print(f"   [SESSION-INFO] Error: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    _append_session_output(tc_name, lines)


def _append_session_output(tc_name: str, lines: list):
    """Append session info lines to the existing TC vos_dump txt file."""
    dump_dir = os.path.join(_cfg.SCRIPT_DIR, "vos_dumps")
    os.makedirs(dump_dir, exist_ok=True)
    filename = f"{tc_name}_vos_dump.txt" if tc_name else "session_info.txt"
    out_path = os.path.join(dump_dir, filename)
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")
        print(f"   [SESSION-INFO] Appended to: {out_path}")
    except Exception as e:
        print(f"   [SESSION-INFO] Failed to append: {e}")


def run_session_fetch_thread(tc_name: str, vsmd_shell=None,
                              alert_output=None, sess_hdl=None):
    """
    Launch fetch_and_append_session_info in a background thread.
    Returns (thread, stop_event) tuple.

    alert_output: pre-captured output from poller
    sess_hdl    : pre-captured valid sess_hdl hex string from poller
    vsmd_shell  : pre-connected (client, shell) for fallback retries
    """
    stop_event = threading.Event()
    t = threading.Thread(
        target=fetch_and_append_session_info,
        args=(tc_name, stop_event, vsmd_shell, alert_output, sess_hdl),
        daemon=True,
    )
    t.start()
    print(f"   [SESSION-INFO] Background thread started for {tc_name}")
    return t, stop_event

def _write_output(result: dict, lines: list, org: str, tc_name: str = ""):
    # Save to vos_dumps/ subfolder, one file per TC
    dump_dir = os.path.join(_cfg.SCRIPT_DIR, "vos_dumps")
    os.makedirs(dump_dir, exist_ok=True)
    filename = f"{tc_name}_vos_dump.txt" if tc_name else OUTPUT_FILENAME
    out_path = os.path.join(dump_dir, filename)
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")
        result["output_file"] = out_path
        print(f"   [VOS-DUMP] Output written: {out_path}")
    except Exception as e:
        print(f"   [VOS-DUMP] Failed to write output file: {e}")
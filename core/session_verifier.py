"""
core/session_verifier.py — Validate session extensive fields from vos_dump file.

Reads the TC*_post_vos_dump.txt file and validates:

  1. Offload status    — must contain "http" AND end with the expected app name
                         e.g. base.ip.tcp.http.office365.ms_teams
                         Pattern: base.ip.tcp.http.*<app_name>
  2. session_action   — must be "drop-session"
  3. session_action_module — must be "casb_tnt_scanner"

All checks use regex for flexible matching.
If any check fails → session_verified = False → TC fails.
"""

import os
import re


# ── Patterns ──────────────────────────────────────────────────────────────────

# Offload status line:
#   Offload status  = Sec-No Evaluation status: Complete
#   APPID Information:Appid = [[base.ip.tcp.http.office365.ms_teams]]
OFFLOAD_APPID_PATTERN = re.compile(
    r'Appid\s*=\s*\[?\[?([^\]\s]+)\]?\]?',
    re.IGNORECASE
)

SESSION_ACTION_PATTERN = re.compile(
    r'session_action\s*=\s*(\S+)',
    re.IGNORECASE
)

SESSION_ACTION_MODULE_PATTERN = re.compile(
    r'session_action_module\s*=\s*(\S+)',
    re.IGNORECASE
)


def _find_dump_file(script_dir: str, tc_label: str) -> str | None:
    """Find the post vos_dump file for this TC label."""
    dump_dir = os.path.join(script_dir, "vos_dumps")
    if not os.path.isdir(dump_dir):
        return None
    # Look for TCx_post_vos_dump.txt or TCx_BaseSendPost_vos_dump.txt etc.
    for f in sorted(os.listdir(dump_dir)):
        if f.endswith("_vos_dump.txt") and tc_label.lower() in f.lower():
            return os.path.join(dump_dir, f)
    return None


def verify_session_extensive(script_dir: str, tc_label: str,
                              expected_app: str) -> dict:
    """
    Parse vos_dump file and validate session extensive fields.

    Args:
        script_dir   : run output folder (where vos_dumps/ lives)
        tc_label     : e.g. "TC1"
        expected_app : app name from --applications arg, e.g. "ms_teams"
                       (lowercased, underscored)

    Returns dict:
        confirmed    : bool — all checks passed
        skipped      : bool — dump file not found
        checks       : {field: (actual, expected, passed)}
        fail_fields  : list of failed field names
        dump_file    : path used
    """
    dump_file = _find_dump_file(script_dir, tc_label)

    if not dump_file:
        print(f"   [SESSION-VERIFY] No vos_dump file found for {tc_label}")
        return {
            "confirmed"  : False,
            "skipped"    : True,
            "checks"     : {},
            "fail_fields": [],
            "dump_file"  : None,
        }

    print(f"   [SESSION-VERIFY] Reading: {dump_file}")
    with open(dump_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    checks = {}

    # ── 1. Offload APPID — must contain "http" AND end with expected_app ──────
    appid_val = ""
    m = OFFLOAD_APPID_PATTERN.search(content)
    if m:
        appid_val = m.group(1).strip("[]")

    # Validate: must contain "http" and end with expected_app (case-insensitive)
    app_clean = expected_app.lower().replace("-", "_")
    appid_low = appid_val.lower()
    appid_has_http = "http" in appid_low
    appid_ends_app = appid_low.endswith(app_clean) or app_clean in appid_low
    appid_passed   = appid_has_http and appid_ends_app

    checks["offload_appid"] = (
        appid_val,
        f"must contain 'http' and end with '{app_clean}'",
        appid_passed
    )

    # ── 2. session_action — must be "drop-session" ────────────────────────────
    action_val = ""
    m = SESSION_ACTION_PATTERN.search(content)
    if m:
        action_val = m.group(1).strip()

    checks["session_action"] = (
        action_val,
        "drop-session",
        action_val.lower() == "drop-session"
    )

    # ── 3. session_action_module — must be "casb_tnt_scanner" ─────────────────
    module_val = ""
    m = SESSION_ACTION_MODULE_PATTERN.search(content)
    if m:
        module_val = m.group(1).strip()

    checks["session_action_module"] = (
        module_val,
        "casb_tnt_scanner",
        module_val.lower() == "casb_tnt_scanner"
    )

    fail_fields = [f for f, (a, e, p) in checks.items() if not p]
    confirmed   = len(fail_fields) == 0

    # ── Console output ─────────────────────────────────────────────────────────
    print(f"\n   ------------------------------")
    print(f"   SESSION EXTENSIVE VERIFICATION")
    print(f"   ------------------------------")
    print(f"   Dump file : {os.path.basename(dump_file)}")
    for field, (actual, expected, passed) in checks.items():
        icon = "✓" if passed else "✗"
        print(f"   [{icon}] {field:<25} = {actual:<40} (expected: {expected})")
    print(f"   Result    : {'CONFIRMED ✓' if confirmed else 'FAILED ✗'}")
    if fail_fields:
        print(f"   Failed    : {', '.join(fail_fields)}")
    print(f"   ------------------------------\n")

    return {
        "confirmed"  : confirmed,
        "skipped"    : False,
        "checks"     : checks,
        "fail_fields": fail_fields,
        "dump_file"  : dump_file,
    }
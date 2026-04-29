"""
run.py — CASB Automation Entry Point.

To add a new app:
  1. Create apps/{app_id}/app.yaml
  2. Create apps/{app_id}/activities.py
  3. Add one line to _APP_MAP below
  That's all — no other files need touching.
"""

import sys
import os

# Ensure the folder containing run.py is on the path so config.py
# and the core/ and apps/ packages are always found regardless of
# which directory Python is launched from.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import argparse
import re as _re
import shutil
from datetime import datetime

# ── Cleanup constants — hardcoded, not user-configurable ─────────────────────
# These apply to ALL users equally. Cannot be overridden via CLI.
_CLEANUP_THRESHOLD_GB = 20   # trigger cleanup prompt when free disk < 20 GB
_KEEP_RUNS_MIN        = 5    # never delete below this many of your own runs

# ── Default email recipients ─────────────────────────────────────────────────
_DEFAULT_EMAILS = [
    "amruta.l@versa-networks.com",
    "hrutuja.k@versa-networks.com",
    "lisari.k@versa-networks.com",
    "lankesh.g@versa-networks.com",
    "pranav.k@versa-networks.com",
    "greena@versa-networks.com",
    "utkarsh.a@versa-networks.com",
    "megha.b@versa-networks.com",
    "shubham.s@versa-networks.com",
    "shyamalapai@versa-networks.com",
    "pavanig@versa-networks.com",
    "gowtham.g@versa-networks.com",
    "neha.s@versa-networks.com",
]

# ── Allowed users — only these names accepted for --user ─────────────────────
# Add new team members here when they join.
# Names must be lowercase, no spaces.
_ALLOWED_USERS = [
    "amruta",
    "lisari",
    "lankesh",
    "hrutuja",
    "neha",
    "gowtham",
    "shyamala",
    "pranav",
    "greena",
    "utkarsh",
    "megha",
]

# ── App registry — ONE LINE PER APP ──────────────────────────────────────────
# Format: "app_id": ["account_type1", "account_type2"]
# Use ["any"] for apps with no personal/corporate distinction.
_APP_MAP = {
    "ms_teams_personal"  : ["personal"],
    "ms_teams_corporate" : ["corporate"],
    "instagram"          : ["any"],
    # "twitter"  : ["any"],
    # "onedrive" : ["any"],
    # "gmail"    : ["any"],
    # "slack"    : ["any"],
    # "box"      : ["any"],
}
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_APP          = "ms_teams_personal"
_DEFAULT_ACCOUNT_TYPE = "personal"


# ── Argument parsing ──────────────────────────────────────────────────────────
# NOTE: No arguments are marked required=True at parser level.
# This allows --manage and --help to work without --host/--pwd/--ssh-user.
# Required argument validation is done manually AFTER --help and --manage
# are handled below.

# Normalize argv — collapse multiple spaces so "Amruta  --capture-har"
# doesn't get treated as a single value for --user
import shlex as _shlex
_raw_args = " ".join(sys.argv[1:])
sys.argv[1:] = _shlex.split(_raw_args)

parser = argparse.ArgumentParser(prog="run.py", add_help=False)
# ── Required args ───────────────────────────────────────────────────────────
parser.add_argument("--host",                    default=None)
parser.add_argument("--pwd",                     default=None)
parser.add_argument("--ssh-user",                default=None)
parser.add_argument("--user",                    default=None)
parser.add_argument("--org",                     default=None)
parser.add_argument("--server-url",              default=None)
parser.add_argument("--access-policy",           default=None)
parser.add_argument("--decrypt-policy",          default=None)
parser.add_argument("--decrypt-rule",            default=None)
parser.add_argument("--decrypt-profile",         default=None)
parser.add_argument("--casb-profile",            default=None)
parser.add_argument("--casb-access-policy-rule", default=None)
parser.add_argument("--casb-profile-rule",       default=None)
# ── Optional args ────────────────────────────────────────────────────────────
parser.add_argument("--applications",  default=None)
parser.add_argument("--account_type",  default=None, choices=["personal", "corporate"])
parser.add_argument("--report-dir",    default=None)
parser.add_argument("--activities",    default="all")
parser.add_argument("--qosmos",        default="True")
parser.add_argument("--send-email",    default=None)
parser.add_argument("--smtp-pwd",      default=None)
parser.add_argument("--analytics-host", default=None,
                    help="Analytics node IP for LEF (casbLog) verification")
parser.add_argument("--analytics-pwd",  default=None,
                    help="Analytics SSH password (default: same as --pwd)")
parser.add_argument("--gateway-name",   default=None,
                    help="Gateway name for LEF log path e.g. SASE-GW-B2")
parser.add_argument("--pin",           action="store_true", default=False)
parser.add_argument("--capture-har",   action="store_true", default=False)
parser.add_argument("--manage",       default=None, choices=["pin","unpin","delete","list"],
                    help="Manage runs: pin / unpin / delete / list")
parser.add_argument("--run",          default=None,
                    help="Run folder name to pin/unpin (used with --manage pin/unpin)")
parser.add_argument("--help", "-h",   action="store_true", default=False)
args, _ = parser.parse_known_args()

if args.help:
    print(r"""
=============================================================
  CASB Automation — run.py
=============================================================
USAGE:
  python run.py --host IP --pwd PWD --ssh-user USER --user NAME
                --org ORG --server-url URL
                --access-policy P --decrypt-policy P --decrypt-rule R
                --decrypt-profile P --casb-profile P --casb-access-policy-rule R
                [options]

FULL EXAMPLE:
  python run.py --host 172.20.4.5 --pwd versa123 --ssh-user admin --user amruta
                --org "ENDTOEND-Tenant-2" --server-url "http://10.196.3.26:4012"
                --access-policy "Default-Policy" --decrypt-policy "Default-Policy"
                --decrypt-rule "decryption_rule_casb" --decrypt-profile "decrypt_profile"
                --casb-profile "casb_mobile_test_rule" --casb-access-policy-rule "mobile_test_rule"

═══════════════════════════════════════════════════════════
  REQUIRED ARGUMENTS (every run needs these 4)
═══════════════════════════════════════════════════════════
  --host              VOS branch IP              e.g. 172.20.4.5
  --pwd               SSH password               e.g. versa123
  --ssh-user          SSH username               e.g. admin
  --user              Your name tag              e.g. amruta

═══════════════════════════════════════════════════════════
  OPTIONAL ARGUMENTS
═══════════════════════════════════════════════════════════
  --applications      App(s) to test             e.g. MS_Teams  (default: all apps)
  --account_type      personal / corporate       (default: all types)
  --report-dir        Output folder for reports  e.g. C:\Users\admin\Downloads\CASB_Reports
  --activities        Which TCs to run:
                        all              → all activities, all TCs  (default)
                        post             → all post TCs
                        post[1]          → TC1 only
                        post[1,3]        → TC1 and TC3
                        "post share"     → all TCs for post and share
  --qosmos            True / False               (default: True)
  --send-email        Email(s) after run         e.g. a@versa.com,b@versa.com
  --smtp-pwd          Gmail SMTP password        (overrides config.py)
  --pin               Pin this run               (default: not pinned)
  --capture-har       Capture HAR files          (default: disabled)
  --analytics-host    Analytics IP for LEF check  e.g. 10.196.3.100
  --analytics-pwd     Analytics SSH password      (default: same as --pwd)
  --gateway-name      Gateway name               e.g. SASE-GW-B2

═══════════════════════════════════════════════════════════
  MANAGE COMMANDS  (no --host/--pwd/--ssh-user needed)
═══════════════════════════════════════════════════════════
  python run.py --manage list   --user amruta
  python run.py --manage pin    --run run_20260322_090000_amruta   --user amruta
  python run.py --manage unpin  --run run_20260322_090000_amruta_PINNED  --user amruta
  python run.py --manage delete --user amruta

═══════════════════════════════════════════════════════════
  CLEANUP (automatic — hardcoded)
═══════════════════════════════════════════════════════════
  Threshold : 20 GB free  → triggers cleanup prompt
  Keep min  : 5 runs      → never deletes below 5 of your runs
  Pinned    : never deleted regardless

REGISTERED APPS:
""")
    for app_id, atypes in _APP_MAP.items():
        print(f"  {app_id:20} account_types: {atypes}")
    print()
    sys.exit(0)


# ── Handle --manage — defined after all helper functions below ───────────────
# (actual execution happens after function definitions)

def _parse_applications(raw: str, global_at: str):
    results = []
    for token in _re.split(r',(?![^\[]*\])', raw):
        token = token.strip()
        if not token:
            continue
        m = _re.match(r'^([^\[]+)(?:\[([^\]]+)\])?$', token)
        if not m:
            print(f"[ERROR] Cannot parse: '{token}'")
            sys.exit(1)
        app_id = m.group(1).strip().lower().replace(" ", "_")
        at_str = m.group(2)
        if at_str:
            at_list = [a.strip().lower() for a in at_str.split(",") if a.strip()]
        elif args.account_type:
            at_list = [global_at]
        else:
            supported = _APP_MAP.get(app_id, ["any"])
            at_list = supported if supported != ["any"] else ["any"]
        results.append((app_id, at_list))
    return results


# ── Validate required args for normal run (not needed for --manage/--help) ───
missing = []
if not args.host:                    missing.append("--host")
if not args.pwd:                     missing.append("--pwd")
if not args.ssh_user:                missing.append("--ssh-user")
if not args.user:                    missing.append("--user")
if not args.org:                     missing.append("--org")
if not args.server_url:              missing.append("--server-url")
if not args.access_policy:           missing.append("--access-policy")
if not args.decrypt_policy:          missing.append("--decrypt-policy")
if not args.decrypt_rule:            missing.append("--decrypt-rule")
if not args.decrypt_profile:         missing.append("--decrypt-profile")
if not args.casb_profile:            missing.append("--casb-profile")
if not args.casb_access_policy_rule: missing.append("--casb-access-policy-rule")
if not args.casb_profile_rule:       missing.append("--casb-profile-rule")
if missing:
    print(f"\n[ERROR] Missing required argument(s): {', '.join(missing)}")
    print(f"\nRequired for every run:")
    print(f"  --host                     VOS branch IP          e.g. 172.20.4.5")
    print(f"  --pwd                      SSH password           e.g. versa123")
    print(f"  --ssh-user                 SSH username           e.g. admin")
    print(f"  --user                     Your name tag          e.g. amruta")
    print(f"  --org                      VOS org name           e.g. ENDTOEND-Tenant-2")
    print(f"  --server-url               Dashboard URL          e.g. http://10.196.3.26:4012")
    print(f"  --access-policy            VOS access policy      e.g. Default-Policy")
    print(f"  --decrypt-policy           VOS decrypt policy     e.g. Default-Policy")
    print(f"  --decrypt-rule             VOS decrypt rule       e.g. decryption_rule_casb")
    print(f"  --decrypt-profile          VOS decrypt profile    e.g. decrypt_profile")
    print(f"  --casb-profile             VOS CASB profile       e.g. casb_mobile_test_rule")
    print(f"  --casb-access-policy-rule  VOS CASB rule          e.g. mobile_test_rule")
    print(f"  --casb-profile-rule        CASB profile rule      e.g. ms_teams_automation")
    print(f"\nRun with --help for full usage.")
    sys.exit(1)

# ── Validate --user is in allowed list ───────────────────────────────────────
_user_lower = args.user.strip().split()[0].lower()  # take first word only, ignore extra spaces
if _user_lower not in _ALLOWED_USERS:
    print(f"\n[ERROR] Unknown user: '{args.user}'")
    print(f"  Allowed users: {', '.join(_ALLOWED_USERS)}")
    print(f"  If you are a new team member, ask admin to add your name to _ALLOWED_USERS in run.py")
    sys.exit(1)

raw_apps    = args.applications or _DEFAULT_APP
global_at   = args.account_type or _DEFAULT_ACCOUNT_TYPE
parsed_apps = _parse_applications(raw_apps, global_at)

# Validate
for app_id, at_list in parsed_apps:
    if app_id not in _APP_MAP:
        print(f"\n[ERROR] Unknown app: '{app_id}'")
        print(f"  Registered apps: {', '.join(_APP_MAP.keys())}")
        print(f"  To add '{app_id}': create apps/{app_id}/app.yaml + apps/{app_id}/activities.py")
        sys.exit(1)

# ── Parse --activities ────────────────────────────────────────────────────────

def _parse_run_navs(activities_arg: str):
    """
    Convert --activities string to a dict of {activity_name: set_of_tc_nums}.

    Each activity has its own set of TC numbers — no merging across activities.

    Examples:
      all                   → {"all": set()}         run everything
      post                  → {"post": set()}         run all post TCs
      post[1]               → {"post": {1}}           run TC1 only
      post[1,3]             → {"post": {1,3}}         run TC1, TC3
      post[1,3] share[1,4]  → {"post": {1,3},         run post TC1,TC3
                                "share": {1,4}}            share TC1,TC4
      post share            → {"post": set(),         run all TCs for both
                                "share": set()}
    """
    if not activities_arg or activities_arg.strip().lower() == "all":
        return {"all": set()}

    nav_map = {}
    for part in activities_arg.strip().split():
        m = _re.match(r'^([^\[]+)(?:\[([^\]]+)\])?$', part.strip().lower())
        if m:
            name = m.group(1).strip()
            if not name:
                continue
            tc_nums = set()
            if m.group(2):
                for n in m.group(2).split(","):
                    n = n.strip()
                    if n.isdigit():
                        tc_nums.add(int(n))
            nav_map[name] = tc_nums
    return nav_map

run_navs = _parse_run_navs(args.activities)


# ── Apply CLI overrides to config ─────────────────────────────────────────────

import config as _cfg

_cfg.SSH_HOST    = args.host
_cfg.SSH_PASSWORD = args.pwd
_cfg.SSH_USER    = args.ssh_user

if args.org:             _cfg.VOS_ORG_NAME               = args.org

# ── Build run folder name: run_YYYYMMDD_HHMMSS[_user][_PINNED] ───────────────
_user_tag   = f"_{_user_lower}"
_pin_tag    = "_PINNED" if args.pin else ""
_run_folder = datetime.now().strftime(f"run_%Y%m%d_%H%M%S{_user_tag}{_pin_tag}")

if args.report_dir:
    _cfg.BASE_DIR   = args.report_dir
    _cfg.SCRIPT_DIR = os.path.join(args.report_dir, _run_folder)
    os.makedirs(_cfg.SCRIPT_DIR, exist_ok=True)
    _cfg.REPORT_FILE = os.path.join(_cfg.SCRIPT_DIR, "test_report.json")
    _cfg.HTML_REPORT = os.path.join(_cfg.SCRIPT_DIR, "test_report.html")
else:
    # Update existing SCRIPT_DIR to include user+pin tag
    _cfg.SCRIPT_DIR = os.path.join(_cfg.BASE_DIR, _run_folder)
    os.makedirs(_cfg.SCRIPT_DIR, exist_ok=True)
    _cfg.REPORT_FILE = os.path.join(_cfg.SCRIPT_DIR, "test_report.json")
    _cfg.HTML_REPORT = os.path.join(_cfg.SCRIPT_DIR, "test_report.html")

if args.access_policy:   _cfg.VOS_ACCESS_POLICY_NAME     = args.access_policy
if args.decrypt_policy:  _cfg.VOS_DECRYPTION_POLICY_NAME = args.decrypt_policy
if args.decrypt_rule:    _cfg.VOS_DECRYPTION_RULE_NAME   = args.decrypt_rule
if args.decrypt_profile: _cfg.VOS_DECRYPT_PROFILE_NAME   = args.decrypt_profile
if args.casb_profile:    _cfg.VOS_CASB_PROFILE_NAME      = args.casb_profile
if args.casb_access_policy_rule: _cfg.VOS_CASB_RULE_NAME        = args.casb_access_policy_rule
if args.casb_profile_rule:       _cfg.VOS_CASB_PROFILE_RULE_NAME = args.casb_profile_rule
# ── Analytics / LEF config ──────────────────────────────────────────
if args.analytics_host: _cfg.ANALYTICS_HOST = args.analytics_host
if args.analytics_pwd:  _cfg.ANALYTICS_PWD  = args.analytics_pwd
elif args.analytics_host: _cfg.ANALYTICS_PWD = args.pwd  # default to --pwd
if args.gateway_name:   _cfg.GATEWAY_NAME   = args.gateway_name

if args.qosmos is not None:
    _cfg.VOS_APPID_REPORT_METADATA = "enable" if args.qosmos.lower() in ("true","1","yes") else "disable"


# ── Email + Upload helpers ────────────────────────────────────────────────────

def _build_email_html(all_results, overall_status, run_ts, server_url=None, run_folder_name=None, app_id=None):
    """Build clean email-safe HTML summary table — works in Gmail/Outlook.

    App name / navigation / activity labels come from ``apps/<app_id>/app.yaml`` when
    ``app_id`` is set (same source as the HTML report). Legacy MS Teams strings are
    only used if yaml is missing or the activity is not listed.
    """
    import yaml as _yaml_email

    _NAV_DETAILS_MS = {
        "post"         : ("Sign in → Click Chat tab → Send text to recipient",              "MS Teams", "Post"),
        "meet_now_post": ("Sign in → Meet Now → Start meeting → Chat tab → Post",           "MS Teams", "Post"),
        "forward"      : ("Sign in → Chat → Click 3 dots → Forward → Send to people",      "MS Teams", "Post"),
        "reply"        : ("Sign in → Chat → Click 3 dots → Reply → Send reply",             "MS Teams", "Post"),
    }

    _email_meta = {}
    _app_hdr = "MS Teams"
    if app_id:
        _yp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps", app_id, "app.yaml")
        try:
            with open(_yp, encoding="utf-8") as _yf:
                _acfg = _yaml_email.safe_load(_yf)
            _app_hdr = (_acfg.get("name") or app_id).strip()
            for _ak, _av in (_acfg.get("activities") or {}).items():
                _cat = _av.get("category", _ak)
                _act_label = _cat.capitalize() if isinstance(_cat, str) else str(_cat)
                _email_meta[_ak.lower()] = (
                    str(_av.get("nav") or "").strip(),
                    _app_hdr,
                    _act_label,
                )
        except Exception:
            pass

    def _nav(r):
        aname = (r.get("activity_name") or "").lower().strip()
        if aname in _email_meta:
            return _email_meta[aname]
        _cands = sorted(
            [(k, v) for k, v in _email_meta.items() if k in aname or aname in k],
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        if _cands:
            return _cands[0][1]
        if aname in _NAV_DETAILS_MS:
            return _NAV_DETAILS_MS[aname]
        for key, val in _NAV_DETAILS_MS.items():
            if key in aname:
                return val
        if _email_meta:
            return min(_email_meta.values(), key=lambda t: len(t[0]))
        return _NAV_DETAILS_MS["post"]

    total      = len(all_results)
    passed     = sum(1 for r in all_results if r.get("status") == "PASS")
    failed     = total - passed
    overall_bg = "#2e7d32" if overall_status == "PASS" else "#c62828"
    emoji      = "✅" if overall_status == "PASS" else "❌"

    rows_html = ""
    for i, r in enumerate(all_results):
        st          = r.get("status", "FAIL")
        sc          = "#2e7d32" if st == "PASS" else "#c62828"
        fl          = r.get("fast_log_confirmed", False)
        fls         = r.get("fast_log_skipped", False)
        fast_log    = "Skipped"      if fls else ("Verified" if fl                        else "Not Verified")
        flc         = "#e65100"      if fls else ("#2e7d32"  if fl                        else "#c62828")
        act_blocked = "Verified"     if r.get("message_not_delivered")                    else "Not Verified"
        ablc        = "#2e7d32"      if r.get("message_not_delivered")                    else "#c62828"
        casb_popup  = "Verified"     if r.get("blocked_by_casb")                          else "Not Verified"
        cbc         = "#2e7d32"      if r.get("blocked_by_casb")                          else "#c62828"
        nav_detail, app_name, act_name = _nav(r)
        sig_ids    = r.get("fast_log_sig_ids", [])
        multi_sigs = r.get("fast_log_multi_sigs", False)
        if not sig_ids:
            sig_cell, sig_color = "—", "#999"
        elif multi_sigs:
            sig_cell, sig_color = "⚠ " + ", ".join(sig_ids), "#e65100"
        else:
            sig_cell, sig_color = sig_ids[0], "#1565c0"
        false_sigs  = r.get("false_sig_ids", [])
        false_cell  = ", ".join(false_sigs) if false_sigs else "None"
        false_color = "#c62828" if false_sigs else "#2e7d32"
        bg = "#ffffff" if i % 2 == 0 else "#f9f9f9"
        rows_html += f"""<tr style="background:{bg}">
          <td style="padding:9px 8px;font-size:12px;font-weight:600;color:#1a1a1a;border-bottom:1px solid #e0e0e0">{app_name}</td>
          <td style="padding:9px 8px;font-size:12px;color:#1a1a1a;border-bottom:1px solid #e0e0e0">{act_name}</td>
          <td style="padding:9px 8px;font-size:11px;color:#444;border-bottom:1px solid #e0e0e0">{nav_detail}</td>
          <td style="padding:9px 8px;font-size:11px;font-family:monospace;color:{sig_color};border-bottom:1px solid #e0e0e0;white-space:nowrap">{sig_cell}</td>
          <td style="padding:9px 8px;font-size:11px;font-weight:600;color:{cbc};text-align:center;border-bottom:1px solid #e0e0e0">{casb_popup}</td>
          <td style="padding:9px 8px;font-size:11px;font-weight:600;color:{ablc};text-align:center;border-bottom:1px solid #e0e0e0">{act_blocked}</td>
          <td style="padding:9px 8px;font-size:11px;font-weight:600;color:{flc};text-align:center;border-bottom:1px solid #e0e0e0">{fast_log}</td>
          <td style="padding:9px 8px;font-size:11px;font-family:monospace;font-weight:600;color:{false_color};text-align:center;border-bottom:1px solid #e0e0e0">{false_cell}</td>
          <td style="padding:9px 8px;font-size:12px;font-weight:700;color:{sc};text-align:center;border-bottom:1px solid #e0e0e0">{st}</td>
        </tr>"""

    total_color = "#2e7d32" if failed == 0 else "#c62828"
    rows_html += f"""<tr style="background:#eeeeee">
          <td colspan="3" style="padding:9px 8px;font-size:12px;font-weight:700;color:#1a1a1a;border-top:2px solid #bbb">TOTAL</td>
          <td colspan="4" style="padding:9px 8px;font-size:11px;color:#555;border-top:2px solid #bbb">{passed} passed, {failed} failed out of {total}</td>
          <td style="padding:9px 8px;font-size:12px;font-weight:700;color:{total_color};text-align:center;border-top:2px solid #bbb">{passed}/{total} ({int(passed/total*100) if total else 0}%)</td>
        </tr>"""

    if server_url and run_folder_name:
        run_url       = server_url.rstrip('/') + '/run/' + run_folder_name
        dashboard_row = (
            '<tr><td style="padding:12px 24px;background:#e8f5e9;border-bottom:1px solid #c8e6c9;text-align:center">'
            '<a href="' + run_url + '" '
            'style="display:inline-block;background:#2e7d32;color:#ffffff;'
            'text-decoration:none;padding:10px 28px;border-radius:5px;'
            'font-size:14px;font-weight:700;letter-spacing:0.5px">'
            '&#127760;&nbsp; View Full Run on Dashboard</a>'
            '<br><span style="font-size:11px;color:#555;margin-top:4px;display:inline-block">' + run_url + '</span>'
            '</td></tr>'
        )
    else:
        dashboard_row = ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:20px 0">
<tr><td align="center">
<table width="760" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);max-width:100%">
  <tr><td style="background:#1565c0;padding:22px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><div style="font-size:18px;font-weight:700;color:#fff">🛡 CASB Block Verification Report</div>
          <div style="font-size:11px;color:#90caf9;margin-top:3px">{_app_hdr} · Versa SASE · fast.log verification</div></td>
      <td align="right"><span style="background:{overall_bg};color:#fff;font-size:14px;font-weight:700;padding:7px 16px;border-radius:5px">{emoji} {overall_status}</span></td>
    </tr></table>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px"><tr>
      <td width="32%" style="background:rgba(255,255,255,0.12);border-radius:5px;padding:10px;text-align:center">
        <div style="font-size:26px;font-weight:800;color:#fff">{total}</div>
        <div style="font-size:10px;color:#90caf9;text-transform:uppercase">Total</div></td>
      <td width="2%"></td>
      <td width="32%" style="background:rgba(0,200,83,0.2);border-radius:5px;padding:10px;text-align:center">
        <div style="font-size:26px;font-weight:800;color:#69f0ae">{passed}</div>
        <div style="font-size:10px;color:#69f0ae;text-transform:uppercase">✔ Passed</div></td>
      <td width="2%"></td>
      <td width="32%" style="background:rgba(255,23,68,0.2);border-radius:5px;padding:10px;text-align:center">
        <div style="font-size:26px;font-weight:800;color:#ff8a80">{failed}</div>
        <div style="font-size:10px;color:#ff8a80;text-transform:uppercase">✘ Failed</div></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:10px 24px;background:#e3f2fd;border-bottom:1px solid #bbdefb">
    <span style="font-size:12px;color:#555">Run timestamp: </span>
    <span style="font-size:12px;font-weight:700;color:#1565c0;font-family:monospace">{run_ts}</span>
  </td></tr>
  {dashboard_row}
  <tr><td style="padding:18px 24px 8px">
    <div style="font-size:13px;font-weight:700;color:#1565c0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #1565c0;padding-bottom:6px">Final Summary</div>
  </td></tr>
  <tr><td style="padding:0 24px 24px">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
      <thead><tr style="background:#1565c0">
        <th style="padding:9px 8px;color:#fff;text-align:left;font-size:10px;text-transform:uppercase">App</th>
        <th style="padding:9px 8px;color:#fff;text-align:left;font-size:10px;text-transform:uppercase">Activity</th>
        <th style="padding:9px 8px;color:#fff;text-align:left;font-size:10px;text-transform:uppercase">Navigation</th>
        <th style="padding:9px 8px;color:#fff;text-align:left;font-size:10px;text-transform:uppercase">Sig ID</th>
        <th style="padding:9px 8px;color:#fff;text-align:center;font-size:10px;text-transform:uppercase">CASB Block Popup</th>
        <th style="padding:9px 8px;color:#fff;text-align:center;font-size:10px;text-transform:uppercase">Activity Blocked</th>
        <th style="padding:9px 8px;color:#fff;text-align:center;font-size:10px;text-transform:uppercase">Fast Log Signature</th>
        <th style="padding:9px 8px;color:#fff;text-align:center;font-size:10px;text-transform:uppercase">False Sig ID Hits</th>
        <th style="padding:9px 8px;color:#fff;text-align:center;font-size:10px;text-transform:uppercase">Result</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </td></tr>
  <tr><td style="padding:12px 24px;background:#f5f5f5;border-top:1px solid #e0e0e0;text-align:center;font-size:11px;color:#999">
    Full report attached as ZIP · Generated by CASB Automation Script · {run_ts}
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _send_report_email(recipients, html_report_path, run_folder_path,
                       overall_status, run_ts, all_results=None,
                       server_url=None, run_folder_name=None, app_id=None):
    import smtplib, zipfile, tempfile
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText
    from email.mime.base      import MIMEBase
    from email                import encoders

    if not recipients:
        return

    print(f"\n{'=' * 55}")
    print(f"SENDING REPORT EMAIL to: {', '.join(recipients)}")
    print(f"{'=' * 55}")

    # Build clean email-safe HTML summary (not the dark theme report)
    if all_results:
        html_body = _build_email_html(
            all_results,
            overall_status,
            run_ts,
            server_url=server_url,
            run_folder_name=run_folder_name,
            app_id=app_id,
        )
    else:
        try:
            with open(html_report_path, "r", encoding="utf-8") as f:
                html_body = f.read()
        except Exception as e:
            print(f"   [EMAIL] Could not read HTML report: {e}")
            return

    # Zip run folder as attachment
    zip_path = None
    try:
        tmp      = tempfile.mktemp(suffix=".zip")
        run_name = os.path.basename(run_folder_path)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(run_folder_path):
                for file in files:
                    abs_path = os.path.join(root, file)
                    arc_name = os.path.relpath(abs_path, os.path.dirname(run_folder_path))
                    zf.write(abs_path, arc_name)
        zip_path = tmp
    except Exception as e:
        print(f"   [EMAIL] Could not zip run folder: {e}")

    status_emoji = "✅" if overall_status == "PASS" else "❌"
    subject      = f"{status_emoji} CASB Test Report — {overall_status} — {run_ts}"
    msg          = MIMEMultipart("mixed")
    msg["From"]    = _cfg.SENDER_EMAIL
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if zip_path:
        try:
            with open(zip_path, "rb") as f:
                part = MIMEBase("application", "zip")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            zip_name = f"CASB_Report_{run_ts.replace(' ','_').replace(':','')}.zip"
            part.add_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            msg.attach(part)
            print(f"   [EMAIL] Attached: {zip_name}")
        except Exception as e:
            print(f"   [EMAIL] Could not attach zip: {e}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(_cfg.SENDER_EMAIL, _cfg.SENDER_GMAIL_APP_PASSWORD)
            server.sendmail(_cfg.SENDER_EMAIL, recipients, msg.as_string())
        print(f"   [EMAIL] ✓ Sent to: {', '.join(recipients)}")
    except Exception as e:
        print(f"   [EMAIL] ✗ Failed: {e}")
    print(f"{'=' * 55}\n")


def _upload_to_server(run_folder, server_url):
    import requests, zipfile, tempfile
    print(f"\n{'=' * 55}")
    print(f"UPLOADING TO CASB RESULTS SERVER")
    print(f"  Server : {server_url}")
    print(f"  Folder : {run_folder}")
    print(f"{'=' * 55}")
    run_name = os.path.basename(run_folder)
    tmp = tempfile.mktemp(suffix=".zip")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(run_folder):
                for file in files:
                    abs_path = os.path.join(root, file)
                    arc_name = run_name + "/" + os.path.relpath(abs_path, run_folder).replace(os.sep, "/")
                    zf.write(abs_path, arc_name)
        with open(tmp, "rb") as f:
            resp = requests.post(
                f"{server_url.rstrip('/')}/api/upload",
                files={"file": (f"{run_name}.zip", f, "application/zip")},
                timeout=120,
            )
        data = resp.json()
        if data.get("status") == "ok":
            print(f"   [UPLOAD] ✓ Success!")
        else:
            print(f"   [UPLOAD] ✗ Server error: {data}")
    except Exception as e:
        print(f"   [UPLOAD] ✗ Failed: {e}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"{'=' * 55}\n")


def _get_free_gb(path: str) -> float:
    """Return free disk space in GB for the drive containing `path`."""
    total, used, free = shutil.disk_usage(path)
    return free / (1024 ** 3)


def _get_folder_size_gb(path: str) -> float:
    """Return total size of a folder in GB."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except Exception:
                    pass
    except Exception:
        pass
    return total / (1024 ** 3)


def _get_my_unpinned_runs(base_dir: str, user: str) -> list:
    """
    Return sorted list (oldest first) of this user's unpinned run folders.
    Pattern: run_YYYYMMDD_HHMMSS_username  (no _PINNED suffix)
    """
    import re
    pattern = re.compile(rf'^run_\d{{8}}_\d{{6}}_{re.escape(user.lower())}$')
    try:
        return sorted([
            d for d in os.listdir(base_dir)
            if pattern.match(d.lower()) and os.path.isdir(os.path.join(base_dir, d))
        ])
    except Exception:
        return []


def _get_my_pinned_runs(base_dir: str, user: str) -> list:
    """Return sorted list of this user's PINNED run folders."""
    import re
    pattern = re.compile(rf'^run_\d{{8}}_\d{{6}}_{re.escape(user.lower())}_PINNED$',
                         re.IGNORECASE)
    try:
        return sorted([
            d for d in os.listdir(base_dir)
            if pattern.match(d) and os.path.isdir(os.path.join(base_dir, d))
        ])
    except Exception:
        return []


def _show_disk_warning(base_dir: str, threshold_gb: int):
    """Print a disk usage warning at the start of the run."""
    free_gb  = _get_free_gb(base_dir)
    total_gb = shutil.disk_usage(base_dir).total / (1024 ** 3)
    used_gb  = total_gb - free_gb
    bar_len  = 30
    used_pct = used_gb / total_gb
    filled   = int(bar_len * used_pct)
    bar      = "█" * filled + "░" * (bar_len - filled)
    status   = ("🔴 LOW"  if free_gb < threshold_gb else
                "🟡 WARN" if free_gb < threshold_gb * 1.5 else
                "🟢 OK")
    print(f"\n{'=' * 55}")
    print(f"  DISK SPACE CHECK")
    print(f"{'=' * 55}")
    print(f"  [{bar}] {used_pct*100:.0f}%")
    print(f"  Used  : {used_gb:.1f} GB  |  Free: {free_gb:.1f} GB  |  Total: {total_gb:.1f} GB")
    print(f"  Status: {status}  (threshold: {threshold_gb} GB free)")
    print(f"{'=' * 55}\n")
    return free_gb


def _ask_and_delete_runs(base_dir: str, user: str, keep_runs: int,
                         triggered_by: str = "manual", suggest: int = 0):
    """
    Interactive delete — shows unpinned runs oldest→newest,
    asks how many to delete, confirms, then deletes.

    triggered_by: "manual" or "auto" (low disk)
    suggest     : suggested number to delete (shown for auto trigger)
    """
    if not user:
        print("   [DELETE] --user is required to delete runs.")
        return

    unpinned = _get_my_unpinned_runs(base_dir, user)
    pinned   = _get_my_pinned_runs(base_dir, user)

    print(f"\n{'=' * 55}")
    if triggered_by == "auto":
        print(f"  ⚠  LOW DISK — Cleanup needed  |  User: {user}")
    else:
        print(f"  MANAGE DELETE  |  User: {user}")
    print(f"{'=' * 55}")

    if not unpinned:
        print(f"  No unpinned runs found for user '{user}'.")
        if pinned:
            print(f"  You have {len(pinned)} pinned run(s) — unpin first to delete.")
        print(f"{'=' * 55}\n")
        return

    # Show all unpinned runs with sizes
    print(f"\n  Your unpinned runs (oldest → newest):\n")
    sizes = []
    for i, folder in enumerate(unpinned, 1):
        size_gb = _get_folder_size_gb(os.path.join(base_dir, folder))
        sizes.append(size_gb)
        print(f"  #{i:<3} {folder:<45} {size_gb:.2f} GB")

    if pinned:
        print(f"\n  📌 Pinned runs (never deleted):")
        for folder in pinned:
            print(f"      {folder}")

    total_unpinned_gb = sum(sizes)
    free_gb           = _get_free_gb(base_dir)
    max_deletable     = len(unpinned)  # can delete all unpinned if needed

    print(f"\n  Total unpinned: {len(unpinned)} runs  |  {total_unpinned_gb:.2f} GB")
    print(f"  Free disk     : {free_gb:.1f} GB")
    if triggered_by == "auto" and suggest > 0:
        print(f"\n  💡 Suggested: delete {suggest} oldest run(s) to free "
              f"~{sum(sizes[:suggest]):.2f} GB")

    print(f"\n  How many oldest runs to delete? "
          f"(1-{max_deletable}, or 0 to skip): ", end="", flush=True)
    try:
        count = int(input().strip())
    except (ValueError, EOFError):
        count = 0

    if count <= 0:
        print(f"  Skipped — nothing deleted.")
        print(f"{'=' * 55}\n")
        return

    count = min(count, max_deletable)
    to_delete = unpinned[:count]

    # Show confirmation
    print(f"\n  Will delete ({count} run(s)):")
    for folder in to_delete:
        idx   = unpinned.index(folder)
        print(f"    ✗  {folder}  ({sizes[idx]:.2f} GB)")
    print(f"\n  Will keep:")
    for folder in unpinned[count:]:
        print(f"    ✓  {folder}")
    for folder in pinned:
        print(f"    📌 {folder}  (pinned)")

    freed_estimate = sum(sizes[:count])
    print(f"\n  Estimated space freed: ~{freed_estimate:.2f} GB")
    print(f"\n  Confirm delete? (yes/no): ", end="", flush=True)
    try:
        confirm = input().strip().lower()
    except EOFError:
        confirm = "no"

    if confirm != "yes":
        print(f"  Cancelled — nothing deleted.")
        print(f"{'=' * 55}\n")
        return

    # Delete
    deleted = 0
    for folder in to_delete:
        full_path = os.path.join(base_dir, folder)
        try:
            shutil.rmtree(full_path)
            deleted += 1
            print(f"  ✓ Deleted: {folder}")
        except Exception as e:
            print(f"  ✗ Could not delete {folder}: {e}")

    free_now = _get_free_gb(base_dir)
    print(f"\n  Done! Deleted {deleted} run(s)  |  Free disk now: {free_now:.1f} GB")
    print(f"{'=' * 55}\n")


def _auto_cleanup(base_dir: str, user: str, keep_runs: int, threshold_gb: int):
    """
    Check disk space — if below threshold, ask user how many runs to delete.
    Never deletes silently — always asks for confirmation.
    """
    if not user:
        print(f"   [CLEANUP] Skipped — no --user tag. Use --user yourname to enable cleanup.")
        return

    free_gb = _get_free_gb(base_dir)
    if free_gb >= threshold_gb:
        print(f"   [CLEANUP] Disk healthy ({free_gb:.1f} GB free) — no cleanup needed. ✅")
        return

    # Calculate suggested count to get back above threshold
    unpinned = _get_my_unpinned_runs(base_dir, user)
    suggest  = 0
    running_free = free_gb
    for folder in unpinned:
        if running_free >= threshold_gb:
            break
        running_free += _get_folder_size_gb(os.path.join(base_dir, folder))
        suggest += 1
    # Never suggest deleting below keep_runs
    max_suggest = max(0, len(unpinned) - keep_runs)
    suggest = min(suggest, max_suggest)

    _ask_and_delete_runs(base_dir, user, keep_runs,
                         triggered_by="auto", suggest=suggest)


def _manage_runs(base_dir: str, action: str, user: str,
                 run_folder: str, keep_runs: int):
    """
    Handle --manage pin / unpin / delete / list
    """
    import re

    # ── LIST ─────────────────────────────────────────────────────
    if action == "list":
        print(f"\n{'=' * 62}")
        print(f"  ALL RUN FOLDERS  —  {base_dir}")
        print(f"{'=' * 62}\n")
        try:
            pattern = re.compile(r'^run_\d{8}_\d{6}')
            folders = sorted([
                d for d in os.listdir(base_dir)
                if pattern.match(d) and os.path.isdir(os.path.join(base_dir, d))
            ])
            if not folders:
                print("  No run folders found.")
            else:
                total_gb = 0
                for folder in folders:
                    size_gb   = _get_folder_size_gb(os.path.join(base_dir, folder))
                    total_gb += size_gb
                    is_pinned = folder.upper().endswith("_PINNED")
                    icon      = "📌" if is_pinned else "✅"
                    # highlight current user's folders
                    is_mine   = (f"_{user.lower()}" in folder.lower()) if user else False
                    mine_tag  = " ← yours" if is_mine else ""
                    print(f"  {icon}  {folder:<50} {size_gb:.2f} GB{mine_tag}")
                free_gb = _get_free_gb(base_dir)
                print(f"\n  Total: {len(folders)} runs  |  {total_gb:.2f} GB used  "
                      f"|  {free_gb:.1f} GB free")
        except Exception as e:
            print(f"  Error listing folders: {e}")
        print(f"{'=' * 62}\n")
        return

    # ── PIN ──────────────────────────────────────────────────────
    if action == "pin":
        if not run_folder:
            print("[ERROR] --run is required for --manage pin")
            print("  Usage: python run.py --manage pin --run run_20260322_090000_amruta")
            return
        full_path = os.path.join(base_dir, run_folder)
        if not os.path.isdir(full_path):
            print(f"[ERROR] Folder not found: {full_path}")
            return
        if run_folder.upper().endswith("_PINNED"):
            print(f"  ℹ  Already pinned: {run_folder}")
            return
        new_name = run_folder + "_PINNED"
        new_path = os.path.join(base_dir, new_name)
        try:
            os.rename(full_path, new_path)
            print(f"\n  📌 Pinned successfully!")
            print(f"  Old: {run_folder}")
            print(f"  New: {new_name}\n")
        except Exception as e:
            print(f"[ERROR] Could not pin: {e}")
        return

    # ── UNPIN ────────────────────────────────────────────────────
    if action == "unpin":
        if not run_folder:
            print("[ERROR] --run is required for --manage unpin")
            print("  Usage: python run.py --manage unpin --run run_20260322_090000_amruta_PINNED")
            return
        full_path = os.path.join(base_dir, run_folder)
        if not os.path.isdir(full_path):
            print(f"[ERROR] Folder not found: {full_path}")
            return
        if not run_folder.upper().endswith("_PINNED"):
            print(f"  ℹ  This run is not pinned: {run_folder}")
            return
        new_name = run_folder[:-7]  # remove _PINNED
        new_path = os.path.join(base_dir, new_name)
        try:
            os.rename(full_path, new_path)
            print(f"\n  ✅ Unpinned successfully!")
            print(f"  Old: {run_folder}")
            print(f"  New: {new_name}\n")
        except Exception as e:
            print(f"[ERROR] Could not unpin: {e}")
        return

    # ── DELETE ───────────────────────────────────────────────────
    if action == "delete":
        if not user:
            print("[ERROR] --user is required for --manage delete")
            return
        _ask_and_delete_runs(base_dir, user, keep_runs, triggered_by="manual")


# ── Handle --manage (now that all functions are defined) ─────────────────────
if args.manage:
    import config as _cfg_manage
    _base = args.report_dir or _cfg_manage.BASE_DIR
    _manage_runs(
        base_dir   = _base,
        action     = args.manage,
        user       = args.user or "",
        run_folder = args.run or "",
        keep_runs  = _KEEP_RUNS_MIN,
    )
    sys.exit(0)

# ── Run each app ──────────────────────────────────────────────────────────────

from playwright.sync_api import sync_playwright
from core.runner import run_all
from core.report_generator import save_report, generate_html_report

_send_email_list = [e.strip() for e in args.send_email.split(",")] if args.send_email else _DEFAULT_EMAILS
_server_url      = args.server_url
_cfg.REPORT_DATA["server_url"] = _server_url or ""

# ── Disk space check at startup ───────────────────────────────────────────────
_free_gb = _show_disk_warning(_cfg.BASE_DIR, _CLEANUP_THRESHOLD_GB)
if _free_gb < _CLEANUP_THRESHOLD_GB:
    print(f"   ⚠  Low disk detected before run — running cleanup first...")
    _auto_cleanup(_cfg.BASE_DIR, _user_lower, _KEEP_RUNS_MIN, _CLEANUP_THRESHOLD_GB)

with sync_playwright() as pw:
    for app_id, at_list in parsed_apps:
        for account_type in at_list:
            print(f"\n{'=' * 55}")
            print(f"  App          : {app_id}")
            print(f"  Account type : {account_type}")
            nav_display = "all" if "all" in run_navs else ", ".join(
                f"{k}[{','.join(str(n) for n in sorted(v))}]" if v else k
                for k, v in run_navs.items()
            )
            print(f"  Activities   : {nav_display}")
            print(f"{'=' * 55}\n")

            # Launch browser (persistent context for cookie persistence)
            # NOTE: Do NOT add --proxy-server here — routing Chrome through
            # a local proxy (e.g. mitmproxy) bypasses Versa SASE entirely,
            # which means no CASB block, no popup, no fast.log hit.
            # HAR capture uses Playwright context listeners instead.
            _browser_args = [
                "--start-maximized",
            ]
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=_cfg.SENDER_PROFILE_DIR,
                headless=False,
                args=_browser_args,
                no_viewport=True,
                ignore_https_errors=True,  # Trust Versa SASE intercepted/self-signed certs
            )

            # Login (app-specific login handler)
            _login_path = os.path.join("apps", app_id, "login_handler.py")
            if os.path.exists(_login_path):
                import importlib.util as _ilu
                spec   = _ilu.spec_from_file_location(f"{app_id}.login", _login_path)
                mod    = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "login"):
                    mod.login(browser, account_type, _cfg)

            # Run all TCs
            all_results = run_all(
                app_id       = app_id,
                account_type = account_type,
                browser      = browser,
                script_dir   = _cfg.SCRIPT_DIR,
                run_navs     = run_navs,
                config_module= _cfg,
                capture_har     = True,
                capture_har_all = args.capture_har,
            )

            # Report
            overall = "PASS" if all(r.get("status") == "PASS" for r in all_results) else "FAIL"
            _cfg.REPORT_DATA["run_status"] = overall
            save_report(all_results)
            generate_html_report(all_results)

            passed = sum(1 for r in all_results if r.get("status") == "PASS")
            total  = len(all_results)
            failed = total - passed

            # ── Final summary table ───────────────────────────────
            # Load TC metadata from app.yaml — zero hardcoding
            import yaml as _yaml
            _app_yaml_path = os.path.join(
                os.path.dirname(__file__), "apps", app_id, "app.yaml"
            )
            _tc_meta_cli = {}
            try:
                with open(_app_yaml_path, encoding="utf-8") as _yf:
                    _app_cfg = _yaml.safe_load(_yf)
                for _ak, _av in (_app_cfg.get("activities") or {}).items():
                    _tl = _av.get("tc_label", _ak.upper())
                    _tc_meta_cli[_ak.lower()] = (
                        _tl,
                        (_av.get("category", _ak)).capitalize(),
                        str(_av.get("nav") or "").strip(),
                    )
            except Exception as _e:
                print(f"  [warn] Could not load app.yaml for summary: {_e}")

            def _resolve_cli_meta(activity_name):
                aname = (activity_name or "").lower().strip()
                if aname in _tc_meta_cli:
                    return _tc_meta_cli[aname]
                for k, v in _tc_meta_cli.items():
                    if k in aname or aname in k:
                        return v
                if _tc_meta_cli:
                    return min(_tc_meta_cli.values(), key=lambda x: x[0])
                return ("TC?", "?", "?")

            W = 178

            def _sum3(confirmed, skipped):
                if skipped:
                    return "Skipped"
                return "Verified" if confirmed else "Not Verified"

            print("\n" + "=" * W)
            print(f"  FINAL SUMMARY  |  OVERALL: {overall}  ({passed}/{total} passed, {failed} failed)")
            print("=" * W)
            print(
                f"  {'TC':<6}  {'Activity':<8}  {'Navigation':<40}  {'CASB':<14}  {'UI blk':<14}  "
                f"{'fast.log':<14}  {'LEF':<14}  {'Session':<14}  {'VOS':<14}  "
                f"{'False sigs':<18}  Result"
            )
            print(
                f"  {'-'*6}  {'-'*8}  {'-'*40}  {'-'*14}  {'-'*14}  "
                f"{'-'*14}  {'-'*14}  {'-'*14}  {'-'*14}  {'-'*18}  ------"
            )
            for r in all_results:
                tc, act, nav   = _resolve_cli_meta(r.get("activity_name"))
                st             = r.get("status", "FAIL")
                casb_popup     = "Verified"     if r.get("blocked_by_casb")      else "Not Verified"
                act_blocked    = "Verified"     if r.get("message_not_delivered") else "Not Verified"
                fl             = r.get("fast_log_confirmed", False)
                fls            = r.get("fast_log_skipped",   False)
                fast_log_sig   = "Skipped"      if fls else ("Verified" if fl    else "Not Verified")
                lef_s          = _sum3(r.get("lef_confirmed"), r.get("lef_skipped"))
                ses_s          = _sum3(r.get("session_verified"), r.get("session_skipped"))
                vos_s          = _sum3(r.get("vos_stats_verified"), r.get("vos_stats_skipped"))
                false_sigs     = r.get("false_sig_ids", [])
                false_sig_str  = ", ".join(false_sigs) if false_sigs else "None"
                nav40 = (nav or "")[:40]
                print(
                    f"  {tc:<6}  {act:<8}  {nav40:<40}  {casb_popup:<14}  {act_blocked:<14}  "
                    f"{fast_log_sig:<14}  {lef_s:<14}  {ses_s:<14}  {vos_s:<14}  "
                    f"{false_sig_str:<18}  {st}"
                )
            print("-" * W)
            print(f"  TOTAL: {passed} passed, {failed} failed out of {total}  ({int(passed/total*100) if total else 0}%)")
            print("=" * W)
            print(f"  HTML Report : {_cfg.HTML_REPORT}")
            print("=" * W)

            # ── Send email report ─────────────────────────────────
            if _send_email_list:
                _send_report_email(
                    recipients       = _send_email_list,
                    html_report_path = _cfg.HTML_REPORT,
                    run_folder_path  = _cfg.SCRIPT_DIR,
                    overall_status   = overall,
                    run_ts           = _cfg.REPORT_DATA.get("run_timestamp", ""),
                    all_results      = all_results,
                    server_url       = _server_url,
                    run_folder_name  = os.path.basename(_cfg.SCRIPT_DIR),
                    app_id           = app_id,
                )

            # ── Upload to CASB Results Server ─────────────────────
            if _server_url:
                _upload_to_server(_cfg.SCRIPT_DIR, _server_url)
                print(f"\n   🌐 View results at: {_server_url}/run/{os.path.basename(_cfg.SCRIPT_DIR)}")

            # ── Smart auto-cleanup after run ──────────────────────
            print(f"\n   [CLEANUP] Post-run disk check...")
            _auto_cleanup(_cfg.BASE_DIR, _user_lower, _KEEP_RUNS_MIN, _CLEANUP_THRESHOLD_GB)

            browser.close()
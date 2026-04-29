"""
core/runner.py — Generic test orchestrator.

Handles the full run lifecycle for ANY app:
  - Load app config (app.yaml) + activity class
  - Browser login
  - TLS decryption check
  - Qosmos pre-test
  - Per-TC: clear stats → run activity → VOS dump → join session thread
  - Report generation + email + server upload

Adding a new app NEVER requires touching this file.
"""

import os
import sys
import importlib.util
from datetime import datetime

import yaml

_ROOT = os.path.dirname(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ------------------------------------------------------------
# APP LOADER
# ------------------------------------------------------------

def load_app(app_id: str):
    """
    Load app.yaml config and ActivityClass for the given app_id.

    Looks for:
        apps/{app_id}/app.yaml
        apps/{app_id}/activities.py   (class must be named e.g. MSTeamsActivity)

    Class naming convention: ms_teams → MSTeamsActivity
                             instagram → InstagramActivity
                             google_drive → GoogleDriveActivity
    """
    app_dir = os.path.join(_ROOT, "apps", app_id)

    if not os.path.isdir(app_dir):
        raise FileNotFoundError(
            f"App folder not found: {app_dir}\n"
            f"Create apps/{app_id}/app.yaml and apps/{app_id}/activities.py"
        )

    # Load app.yaml
    yaml_path = os.path.join(app_dir, "app.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Missing app.yaml: {yaml_path}")
    with open(yaml_path, encoding="utf-8") as f:
        app_config = yaml.safe_load(f)

    # Dynamically import activities.py
    act_path = os.path.join(app_dir, "activities.py")
    if not os.path.exists(act_path):
        raise FileNotFoundError(f"Missing activities.py: {act_path}")

    spec   = importlib.util.spec_from_file_location(f"{app_id}.activities", act_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Derive class name: ms_teams → MSTeamsActivity
    class_name     = "".join(w.capitalize() for w in app_id.split("_")) + "Activity"
    ActivityClass  = getattr(module, class_name, None)
    if ActivityClass is None:
        raise AttributeError(
            f"Class '{class_name}' not found in {act_path}.\n"
            f"Make sure activities.py defines: class {class_name}(BaseActivity)"
        )

    return app_config, ActivityClass


def resolve_category_log_config(app_config: dict, activity_name: str):
    """
    Resolve fast.log keywords and Versa popup expectations from app.yaml.

    Uses ``activities.<name>.category`` → ``categories.<category>.{log_match,expected}``.
    Falls back to legacy top-level ``log_match`` / ``expected`` when ``categories`` is absent
    or the category key is missing.

    Returns:
        (keywords, expected, category_key)
    """
    meta = (app_config.get("activities") or {}).get(activity_name) or {}
    category = meta.get("category", activity_name)
    cats = app_config.get("categories") or {}
    if category in cats:
        cat = cats[category]
        keywords = (cat.get("log_match") or {}).get("keywords", [])
        expected = cat.get("expected") or {}
        return keywords, expected, category
    lm = app_config.get("log_match") or {}
    keywords = lm.get("keywords", [])
    expected = app_config.get("expected") or {}
    return keywords, expected, category


# ------------------------------------------------------------
# MAIN RUN LOOP
# ------------------------------------------------------------

def run_all(app_id: str, account_type: str, browser, script_dir: str,
            run_navs: dict, config_module, capture_har: bool = False, capture_har_all: bool = False):
    """
    Generic test run for any app.

    Args:
        app_id        : e.g. "ms_teams", "instagram"
        account_type  : e.g. "personal", "corporate"
        browser       : Playwright browser/context object
        script_dir    : output folder for this run
        run_navs      : dict of {activity_name: set_of_tc_nums}
                        e.g. {"post": {1,3}, "share": {1,4}} or {"all": set()}
        config_module : the imported config module (for REPORT_DATA, credentials etc.)

    Returns:
        list of result dicts (one per TC)
    """
    from core.decryption_check import check_decryption
    from core.vos_info_dump import (
        run_pre_test_clear, run_vos_info_dump,
        run_qosmos_pretest, run_session_fetch_thread,
    )
    from core.report_generator import save_report, generate_html_report

    REPORT_DATA = config_module.REPORT_DATA
    RECIPIENTS  = config_module.RECIPIENTS
    all_results = []

    # Load app
    app_config, ActivityClass = load_app(app_id)
    activities_meta = app_config.get("activities", {})

    # Record run metadata
    REPORT_DATA["run_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    REPORT_DATA["config"] = {
        "app_id"          : app_id,
        "account_type"    : account_type,
        "app_name"        : app_config.get("name", app_id),
        "ssh_host"        : config_module.SSH_HOST,
        "vos_org"         : config_module.VOS_ORG_NAME,
        "vos_access_policy"  : config_module.VOS_ACCESS_POLICY_NAME,
        "vos_decrypt_policy" : config_module.VOS_DECRYPTION_POLICY_NAME,
        "vos_decrypt_rule"   : config_module.VOS_DECRYPTION_RULE_NAME,
        "vos_decrypt_profile": config_module.VOS_DECRYPT_PROFILE_NAME,
        "vos_casb_profile"   : config_module.VOS_CASB_PROFILE_NAME,
        "vos_casb_rule"      : config_module.VOS_CASB_RULE_NAME,
    }

    # ── Step 0: TLS Decryption check ─────────────────────────────
    print(f"\n{'=' * 55}")
    print("PRE-TEST: TLS Decryption Check")
    print(f"{'=' * 55}")
    first_page = browser.pages[0] if browser.pages else browser.new_page()
    decryption_result = check_decryption(first_page, label="pre-test")
    REPORT_DATA["step_decryption"] = decryption_result

    if decryption_result["should_fail_test"]:
        print("[DECRYPTION FAIL] SSL inspection not detected — aborting all TCs.")
        # Create one fail entry per (recipient × activity) so the report shows
        # the correct TC label and navigation for every TC that was going to run,
        # rather than a single blank entry that falls back to TC1.
        reason = "TLS decryption not detected — SSL inspection required"
        for recipient in RECIPIENTS:
            added = False
            for act_name, act_meta in activities_meta.items():
                tc_label_a = act_meta.get("tc_label", act_name.upper())
                tc_num_a   = int(tc_label_a.replace("TC", "")) if tc_label_a.startswith("TC") else 0
                # Apply the same run_navs filter used in the normal loop
                if "all" not in run_navs:
                    act_cat    = act_meta.get("category", act_name)
                    matched    = None
                    if act_name in run_navs:
                        matched = act_name
                    elif act_cat in run_navs:
                        matched = act_cat
                    if matched is None:
                        continue
                    if run_navs[matched] and tc_num_a not in run_navs[matched]:
                        continue
                _append_fail(all_results, REPORT_DATA, recipient, reason,
                             activity_name=act_name, tc_label=tc_label_a)
                added = True
            # Fallback: if no activities matched the filter, add one blank entry
            if not added:
                _append_fail(all_results, REPORT_DATA, recipient, reason)
        return all_results

    # ── Step 0b: Qosmos appid report_metadata ────────────────────
    run_qosmos_pretest()

    # ── Per-recipient loop ────────────────────────────────────────
    for index, recipient in enumerate(RECIPIENTS):
        print(f"\n{'=' * 55}")
        print(f"Recipient {index + 1}/{len(RECIPIENTS)}: {recipient}")
        print(f"{'=' * 55}")

        activity_obj = ActivityClass(browser, app_config, script_dir, capture_har=capture_har, capture_har_all=capture_har_all)
        skipped = []

        for activity_name, meta in activities_meta.items():
            tc_label  = meta.get("tc_label", activity_name.upper())
            tc_num    = int(tc_label.replace("TC", "")) if tc_label.startswith("TC") else 0

            # ── Activity + TC filtering ───────────────────────────
            # run_navs is a dict: {"post": {1,3}, "share": {1,4}} or {"all": set()}
            # "all" key means run everything — no filtering
            if "all" not in run_navs:
                activity_category = meta.get("category", activity_name)

                # Find which key in run_navs matches this activity
                matched_key = None
                if activity_name in run_navs:
                    matched_key = activity_name
                elif activity_category in run_navs:
                    matched_key = activity_category

                # Activity not requested at all → skip
                if matched_key is None:
                    skipped.append(tc_label)
                    continue

                # Activity requested but with specific TC numbers → filter
                activity_tc_nums = run_navs[matched_key]
                if activity_tc_nums and tc_num not in activity_tc_nums:
                    skipped.append(tc_label)
                    continue
            print(f"\n{'─' * 55}")
            print(f"  {tc_label}: {meta.get('nav', activity_name)}")
            print(f"{'─' * 55}")
            _kw, _exp, _cat = resolve_category_log_config(app_config, activity_name)
            print(
                f"   [log_match] category={_cat!r} · keywords={_kw!r} · "
                f"expected={_exp!r}"
            )

            # ── Pre-TC: clear VOS stats + fast.log ───────────────
            print(f"\n   [{tc_label}] PRE-TC CLEAR: VOS stats + fast.log...")
            clear_result = run_pre_test_clear()
            REPORT_DATA["step_vos_clear"] = clear_result
            if not clear_result["success"] and clear_result["error"]:
                print(f"   [{tc_label}] CLEAR FAILED: {clear_result['error']} — continuing anyway")

            # ── Run activity ──────────────────────────────────────
            kwargs = _build_kwargs(activity_name, recipient, config_module)
            kwargs["pre_clear_result"] = clear_result
            result, session_thread = activity_obj.run_activity(
                activity_name, tc_label, **kwargs
            )
            result["recipient"] = recipient

            # ── Post-TC: VOS info dump ────────────────────────────
            run_vos_info_dump(f"{tc_label}_{activity_name}")

            # ── Join session fetch thread ─────────────────────────
            if session_thread and session_thread.is_alive():
                print(f"   [{tc_label}] Waiting for session fetch thread...")
                session_thread.join(timeout=30)

            # ── Session extensive verification (needs vos_dump) ───────────
            activity_obj._finish_session_verification(result, tc_label)

            # ── VOS stats counter verification ──────────────────────
            activity_obj._finish_vos_stats_verification(result, tc_label)

            result["status"] = "PASS" if not result["fail_reason"] else "FAIL"

            # ── Save/discard HAR ──────────────────────────────────
            har = result.pop("_har", None)
            if har:
                har.save_or_discard(result.get("fail_reason", []))

            # Append after all TC steps (including session / VOS stats) are recorded
            all_results.append(result)

        if skipped:
            print(f"\n   Skipped: {', '.join(skipped)} (not in --activities)")

        if index < len(RECIPIENTS) - 1:
            from core.browser_handler import countdown_wait
            countdown_wait(config_module.WAIT_BETWEEN_RECIPIENTS)

    return all_results


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def _build_kwargs(activity_name: str, recipient: str, cfg) -> dict:
    """
    Build keyword arguments for each activity type.
    Extend this if a new activity needs different parameters.
    """
    base = {
        "recipient": recipient,
        "message"  : cfg.MESSAGE,
    }
    if activity_name == "reply":
        base["reply_text"] = f"Reply {cfg.MESSAGE}"
    return base


def _append_fail(all_results, REPORT_DATA, recipient, reason,
                 activity_name="", tc_label=""):
    """Append a failed TC entry when we need to abort early."""
    from datetime import datetime
    entry = {
        "recipient"             : recipient,
        "activity_name"         : activity_name,
        "tc_label"              : tc_label,
        "timestamp"             : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status"                : "FAIL",
        "fail_reason"           : [reason],
        "fast_log_confirmed"    : False,
        "fast_log_skipped"      : False,
        "fast_log_matches"      : [],
        "application_match"     : False,
        "activity_match"        : False,
        "blocked_by_casb"       : False,
        "message_not_delivered" : False,
        "steps"                 : [],
    }
    all_results.append(entry)
    REPORT_DATA["recipients"].append({
        "recipient"  : recipient,
        "timestamp"  : entry["timestamp"],
        "status"     : "FAIL",
        "fail_reason": [reason],
        "steps"      : [],
    })
"""
core/base_activity.py — Base class for all CASB app activities.

Every app subclasses BaseActivity and implements:
  - _open_fresh_tab()          open a browser tab at the app URL
  - _wait_for_app(page)        wait until the app is fully loaded
  - _do_{activity}(page, result, **kwargs)   UI steps only

Everything else — log capture, CASB popup wait, session fetch,
step recording, report registration — is handled here once.

Adding a new app means implementing those 3 things above. Nothing else.
"""

import time
import sys
import os

# Add project root to path so all imports work regardless of where
# this file sits in the directory tree
_ROOT = os.path.dirname(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.runner import resolve_category_log_config


class BaseActivity:
    """
    Base class for all CASB app activity handlers.

    Constructor args:
        browser     : Playwright Browser/BrowserContext object
        app_config  : dict loaded from apps/{app_id}/app.yaml
        script_dir  : run output folder path (screenshots, HAR saved here)
    """

    def __init__(self, browser, app_config: dict, script_dir: str, capture_har: bool = False, capture_har_all: bool = False):
        self.browser     = browser
        self.app_config  = app_config
        self.script_dir  = script_dir
        self.capture_har     = capture_har
        self.capture_har_all = capture_har_all
        lm = app_config.get("log_match") or {}
        self.keywords    = lm.get("keywords", [])
        self.expected    = app_config.get("expected", {})
        self.app_name    = app_config.get("name", "App")

    def _apply_category_log_match(self, activity_name: str) -> None:
        """Set ``self.keywords`` / ``self.expected`` from ``categories`` (or legacy YAML)."""
        keywords, expected, _ = resolve_category_log_config(self.app_config, activity_name)
        self.keywords = keywords
        self.expected = expected

    def _sync_config_expected_from_app(self) -> None:
        """Push ``self.expected`` into ``config`` for Versa popup validation."""
        import config as _cfg
        exp = self.expected or {}
        if exp.get("application"):
            _cfg.EXPECTED_APPLICATION = exp["application"]
        if exp.get("activity"):
            _cfg.EXPECTED_ACTIVITY = exp["activity"]
        if exp.get("blocked_by"):
            _cfg.EXPECTED_BLOCKED_BY = exp["blocked_by"]

    # ================================================================
    # MAIN ENTRY POINT — called by runner.py for each activity
    # ================================================================

    def run_activity(self, activity_name: str, tc_label: str, **kwargs):
        """
        Orchestrates a single activity end-to-end:
          1.  Record pre-test clear steps
          2.  Open fresh tab + wait for app to load
          3.  Start fast.log SSH capture (keywords from app.yaml)
          4.  Call _do_{activity_name}(page, result, **kwargs)
              App stores poller in result["_poller"] via _after_send.
          5.  Wait for CASB AlertWindow popup + validate
          6.  Finish log capture + validate
          7.  Determine overall pass/fail
          8.  Register to report

        Returns: (result dict, session_thread or None)
        """
        import config as _cfg
        result = self._make_result(activity_name, tc_label)

        self._apply_category_log_match(activity_name)
        self._sync_config_expected_from_app()

        # ── Step 0: Record pre-test clear steps ──────────────────
        pre_clear = kwargs.pop("pre_clear_result", None)
        if pre_clear is not None:
            self._add_pre_clear_steps(result, pre_clear, tc_label)

        # ── Step 1: Open tab ──────────────────────────────────────
        page = self._open_fresh_tab()
        if not self._wait_for_app(page):
            result["fail_reason"].append(f"{self.app_name} did not load in browser")
            self._register_to_report(result)
            return result, None

        # ── Step 2: Start log capture ─────────────────────────────
        cap = self._start_log_capture()
        self._add_step(result, f"{tc_label}-a", "SSH Log Capture Started",
                       "pass" if cap._connected else "warn",
                       [f"Target   : {_cfg.SSH_USER}@{_cfg.SSH_HOST}:{_cfg.SSH_PORT}",
                        f"Log file : {_cfg.FAST_LOG}",
                        f"Keywords : {self.keywords}",
                        f"Connected: {'Yes' if cap._connected else 'No — ' + str(cap._error)}"])

        # ── Step 3: Run app UI method ─────────────────────────────
        method = getattr(self, f"_do_{activity_name}", None)
        if method is None:
            result["fail_reason"].append(
                f"Activity '{activity_name}' not implemented in {self.__class__.__name__}"
            )
            cap.stop()
            self._register_to_report(result)
            return result, None

        send_attempted = method(page, result, **kwargs)

        # Retrieve poller started inside _do_* via _after_send
        poller       = result.pop("_poller",       None)
        poller_label = result.pop("_poller_label", tc_label)
        session_thread = result.pop("_session_thread", None)

        # ── Step 4: CASB popup wait ───────────────────────────────
        if send_attempted:
            self._wait_casb_popup(page, result, tag=tc_label)
            time.sleep(5)   # give fast.log time to flush

        # ── Step 4b: Join poller and write session dump ───────────
        # Popup just fired (or timed out) — sess_hdl appears at popup time,
        # so the poller has already caught it and run the inline dump.
        # Give it up to 60s grace for the extensive command to finish.
        if poller:
            from core.vos_info_dump import _append_session_output
            from datetime import datetime as _dt
            _, sess_hdl, attempts, session_lines = poller["get_result"](join_timeout=60)
            print(f"   [SESSION-INFO] Poller result: sess_hdl={sess_hdl}, attempts={attempts}")
            if session_lines:
                _append_session_output(poller_label, session_lines)
            else:
                _append_session_output(poller_label, [
                    "",
                    "=" * 70,
                    "  SESSION INFO — not captured",
                    f"  Timestamp : {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "=" * 70,
                    "",
                    f"sess_hdl = 0 after {attempts} poll attempt(s)",
                ])

        # ── Step 5: Finish log capture ────────────────────────────
        self._finish_log_capture(cap, result, f"{tc_label}-log")

        # ── Step 6: Pass/fail ─────────────────────────────────────
        result["status"] = "PASS" if not result["fail_reason"] else "FAIL"

        # ── Step 7: Register ──────────────────────────────────────
        self._register_to_report(result)
        return result, session_thread

    # ================================================================
    # HOOKS CALLED FROM _do_* — app calls these at the right moment
    # ================================================================

    def _before_send(self, page, tc_label: str):
        """
        Call right before clicking Send.
        Starts the session handle poller — it connects to vsmd in the background
        and polls until sdata.sess_hdl becomes non-zero, then immediately runs
        the full grep + extensive dump on the same warm shell.
        No hardcoded timeout — poller runs until the popup fires (which is when
        sess_hdl appears), so run_activity joins it after _wait_casb_popup.
        Returns ((poller, None, None), har).
        """
        from core.vos_info_dump import start_session_handle_poller
        from core.browser_handler import HarRecorder
        import config as _cfg
        # Safety cap: CASB_POPUP_WAIT_TIMEOUT + extra for the inline dump commands
        poller = start_session_handle_poller(timeout=_cfg.CASB_POPUP_WAIT_TIMEOUT + 60)
        har = HarRecorder(page, tc_label, self.script_dir, capture_har=self.capture_har, capture_har_all=self.capture_har_all)
        har.start()
        return (poller, None, None), har

    def _after_send(self, page, result: dict, vsmd_prep, har,
                    tc_label: str, sent_text: str = None):
        """
        Call right after clicking Send.
        Stores the poller in result for run_activity to join after the popup,
        confirms message appeared in browser, and stops HAR recording.
        The poller runs freely in the background — no blocking here.
        """
        # ── Don't block here — let poller run freely in the background ────
        # sess_hdl appears at the exact moment the CASB popup fires.
        # _wait_casb_popup runs after this returns, so by the time the popup
        # is detected and dismissed the poller has already caught sess_hdl
        # and completed the inline dump. run_activity joins the poller thread
        # after _wait_casb_popup with a short grace period.
        poller, _, _ = vsmd_prep
        result["_poller"]         = poller   # joined in run_activity after popup
        result["_poller_label"]   = tc_label
        result["_session_thread"] = None

        # ── Now wait for message confirmation + stop HAR ──────────────────
        # MUST use page.wait_for_timeout() not time.sleep() so Playwright
        # event loop keeps running and HAR listeners can receive responses.
        if sent_text:
            try:
                page.locator(f"text='{sent_text}'").first.wait_for(
                    state="visible", timeout=5000)
                print(f"   [HAR] Message confirmed visible — stopping HAR")
            except Exception:
                # Fallback — message may not be visible (CASB blocked it)
                print(f"   [HAR] Message not visible (blocked?) — waiting 3s for network")
                page.wait_for_timeout(3000)
        else:
            page.wait_for_timeout(2000)

        har.stop()
        result["_har"] = har    # stored so runner can call save_or_discard
        return None  # no session stop_event needed — poller is self-contained

    # ================================================================
    # ABSTRACT — subclass must implement
    # ================================================================

    def _open_fresh_tab(self):
        """Open and return a Playwright page at the app URL."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _open_fresh_tab()"
        )

    def _wait_for_app(self, page) -> bool:
        """
        Wait until the app is fully loaded and ready to interact with.
        Returns True if loaded, False if timed out.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _wait_for_app(page)"
        )

    # ================================================================
    # SHARED HELPERS — used internally and from _do_* methods
    # ================================================================

    def _add_pre_clear_steps(self, result: dict, clear_result: dict, tc_label: str):
        """Record pre-test VOS clear as steps inside the TC result."""
        ssh_ok = clear_result.get("success", False)
        error  = clear_result.get("error")

        # Step PRE-1: SSH + Stats clear
        cleared = clear_result.get("cleared", [])
        self._add_step(
            result, f"{tc_label}-pre1",
            "Pre-Test: Clear Versa CLI / VOS Stats",
            "pass" if ssh_ok else "fail",
            [f"SSH success  : {ssh_ok}"]
            + ([f"Error        : {error}"] if error else [])
            + [f"Cleared      : {c}" for c in cleared]
        )

        # Step PRE-2: fast.log clear
        fl_ok  = clear_result.get("fastlog_cleared", False)
        fl_err = clear_result.get("fastlog_error")
        self._add_step(
            result, f"{tc_label}-pre2",
            "Pre-Test: Clear fast.log",
            "pass" if fl_ok else ("warn" if not error else "fail"),
            [f"Command      : request clear log idp/fast.log",
             f"Result       : {'Cleared ✓' if fl_ok else 'Response unclear'}"]
            + ([f"Response     : {fl_err}"] if fl_err else [])
        )

    def _make_result(self, activity_name: str, tc_label: str = None) -> dict:
        from datetime import datetime
        return {
            "activity_name"        : activity_name,
            "tc_label"             : tc_label or "",
            "timestamp"            : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status"               : "FAIL",
            "application_match"    : False,
            "activity_match"       : False,
            "blocked_by_casb"      : False,
            "fast_log_confirmed"   : False,
            "fast_log_skipped"     : False,
            "fast_log_matches"     : [],
            "fast_log_sig_ids"     : [],
            "fast_log_multi_sigs"  : False,
            "false_sig_ids"        : [],
            "message_not_delivered": False,
            "fail_reason"          : [],
            "steps"                : [],
        }

    def _add_step(self, result: dict, number, name: str, status: str,
                  details: list, screenshot_b64=None):
        result["steps"].append({
            "number"        : number,
            "name"          : name,
            "status"        : status,
            "details"       : details,
            "screenshot_b64": screenshot_b64,
        })

    def _screenshot(self, page, label: str):
        """Take screenshot, return (b64, path)."""
        from core.browser_handler import take_screenshot_b64
        return take_screenshot_b64(page, label, self.script_dir)

    def _start_log_capture(self):
        """Build and start a FastLogCapture using keywords from app.yaml."""
        from core.versa_handler import FastLogCapture
        keywords = self.keywords
        cap = FastLogCapture()
        cap._keywords = keywords
        def _is_match(line):
            low = line.lower()
            return all(k.lower() in low for k in keywords)
        cap._is_match = _is_match
        cap.start()
        return cap

    def _finish_log_capture(self, cap, result: dict, step_num=None):
        """Stop capture, validate, record step, update result."""
        cap.stop()
        log_result = cap.validate()
        result["fast_log_confirmed"]  = log_result["fast_log_confirmed"]
        result["fast_log_skipped"]    = log_result["ssh_skipped"]
        result["fast_log_matches"]    = log_result["matched_lines"]
        result["fast_log_sig_ids"]    = log_result.get("sig_ids", [])
        result["fast_log_multi_sigs"] = log_result.get("multiple_sig_ids", False)
        result["false_sig_ids"]       = log_result.get("false_sig_ids", [])
        result["fast_log_all_lines"]  = log_result.get("all_lines", [])

        false_sigs = log_result.get("false_sig_ids", [])
        details = [
            f"SSH connected  : {log_result['ssh_connected']}",
            f"Total captured : {log_result['total_lines']} lines",
            f"Matching lines : {log_result['matched_count']}",
            f"Keywords       : {cap._keywords}",
            f"Result         : {'CONFIRMED' if log_result['fast_log_confirmed'] else 'NOT FOUND'}",
        ] + [f"Match: {ln}" for ln in log_result["matched_lines"]]           + ([f"False Sig ID: {sid}" for sid in false_sigs] if false_sigs else [])

        self._add_step(result, step_num or "log", "fast.log Signature Validation",
                       "pass" if log_result["fast_log_confirmed"] else
                       ("warn" if log_result["ssh_skipped"] else "fail"),
                       details)

        if not log_result["fast_log_confirmed"] and not log_result["ssh_skipped"]:
            result["fail_reason"].append(
                f"fast.log: no match for keywords {cap._keywords}"
            )

        # ── Fail TC if false sig IDs were detected ────────────
        if false_sigs:
            result["fail_reason"].append(
                f"False sig ID(s) detected in fast.log: {', '.join(false_sigs)}"
            )

    def _wait_casb_popup(self, page, result: dict, tag: str = ""):
        """
        Wait for the Versa AlertWindow to appear, validate it, wait for expiry.

        FAIL conditions (all added to fail_reason):
          1. Popup did not appear within timeout
          2. Popup appeared but application/activity did not match expected
          3. Popup appeared but not confirmed blocked by CASB
        """
        from core.versa_handler import (
            extract_popup_data, validate_popup_data,
            wait_until_popup_appears, wait_until_popup_disappears,
            capture_popup_screenshot,
        )
        print(f"   [{tag}] Waiting for Versa AlertWindow popup...")
        popup_win    = None
        popup_data   = {}
        popup_valid  = {}
        popup_ss_b64 = None
        casb_blocked = False

        try:
            popup_win = wait_until_popup_appears()
            if popup_win is None:
                # ── FAIL 1: Popup never appeared ─────────────────
                print(f"   [{tag}] No popup appeared.")
                result["fail_reason"].append(
                    f"CASB AlertWindow did NOT appear within timeout [{tag}]"
                )
            else:
                # Capture screenshot of the AlertWindow immediately while it's visible
                popup_ss_b64, _ = capture_popup_screenshot(popup_win, self.script_dir, tag)
                popup_data   = extract_popup_data(popup_win)
                popup_valid  = validate_popup_data(popup_data)
                casb_blocked = popup_valid.get("blocked_by_casb", False)
                app_match    = popup_valid.get("application_match", False)
                act_match    = popup_valid.get("activity_match", False)

                result["application_match"] = app_match
                result["activity_match"]    = act_match
                result["blocked_by_casb"]   = casb_blocked

                # ── FAIL 2: Application/Activity mismatch ────────
                if not app_match:
                    result["fail_reason"].append(
                        f"Popup application did not match expected [{tag}]"
                    )
                if not act_match:
                    result["fail_reason"].append(
                        f"Popup activity did not match expected [{tag}]"
                    )
                # ── FAIL 3: Not confirmed blocked by CASB ────────
                if not casb_blocked:
                    result["fail_reason"].append(
                        f"CASB AlertWindow appeared but block NOT confirmed [{tag}]"
                    )

                # Take browser screenshot while popup is still visible
                browser_ss, _ = self._screenshot(page, f"{tag}_casb_block")
                print(f"   [{tag}] Waiting for AlertWindow to auto-expire...")
                wait_until_popup_disappears()

        except Exception as e:
            print(f"   [{tag}] AlertWindow error: {e}")
            result["fail_reason"].append(f"CASB AlertWindow error: {e} [{tag}]")
            if stop_event:
                stop_event.set()

        step_status = "pass" if casb_blocked else "fail"
        # Use popup screenshot if captured, fall back to browser screenshot
        # browser_ss may be None if popup never appeared
        if "browser_ss" not in dir():
            browser_ss, _ = self._screenshot(page, f"{tag}_casb_block")
        display_ss = popup_ss_b64 if popup_ss_b64 else browser_ss
        self._add_step(result, f"{tag}-popup", "Versa AlertWindow (CASB Block) Validation",
                       step_status,
                       [f"Popup found       : {popup_win is not None}",
                        f"Application match : {popup_valid.get('application_match', False)}",
                        f"Activity match    : {popup_valid.get('activity_match', False)}",
                        f"Blocked by CASB   : {casb_blocked}",
                        f"Full text         : {popup_data.get('full_text', 'N/A')}"],
                       display_ss)
        # Also store popup screenshot path in result for server dashboard
        result["casb_popup_screenshot"] = f"{tag}_casb_popup_screenshot.png" if popup_ss_b64 else None
        return casb_blocked

    def _check_delivery_generic(self, page, result: dict, message: str,
                                 step_num: str, tag: str = ""):
        """
        Generic delivery check — works for regular chat (TC1, TC3, TC4).
        Looks for message status icon in the standard Teams chat DOM.

        FAIL condition: message has a timestamp (was delivered) → CASB did not block.
        """
        sending   = False
        delivered = False
        detail    = "Status inconclusive — assuming CASB blocked"
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            content_div = page.locator(
                f"xpath=//div[@data-message-content=''][.//p[contains(text(),'{message}')]]"
            ).first
            content_id = content_div.get_attribute("id")
            if content_id:
                num = content_id.replace("content-", "")
                status_label = ""
                try:
                    status_label = (
                        page.locator(f"xpath=//span[@id='read-status-icon-{num}']")
                            .first.get_attribute("aria-label") or ""
                    )
                except Exception:
                    pass
                ts_count  = page.locator(f"xpath=//time[@id='timestamp-{num}']").count()
                sending   = "Sending" in status_label
                delivered = ts_count > 0 and not sending
        except Exception:
            pass

        if sending:
            detail = "Message stuck at 'Sending...' → CASB block CONFIRMED ✓"
            result["message_not_delivered"] = True
        elif delivered:
            detail = "Message has timestamp (delivered) → CASB did NOT block ✗"
            result["message_not_delivered"] = False
            result["fail_reason"].append(
                f"Message was delivered to recipient — CASB did not block [{tag}]"
            )
        else:
            detail = "Status inconclusive — assuming CASB blocked"
            result["message_not_delivered"] = True

        ss, _ = self._screenshot(page, f"{tag}_delivery_status")
        self._add_step(result, step_num, "Message Delivery Status Check",
                       "pass" if result["message_not_delivered"] else "fail",
                       [detail,
                        f"Sending... : {sending}",
                        f"Delivered  : {delivered}",
                        "Sending... = CASB blocked  |  timestamp = delivered"], ss)

    def _register_to_report(self, result: dict):
        """Push result into REPORT_DATA so generate_html_report renders it."""
        import config as _cfg
        _cfg.REPORT_DATA["recipients"].append({
            "recipient"    : f"{result.get('recipient', '')} — {result.get('activity_name', '')}",
            "activity_name": result.get("activity_name", ""),
            "tc_label"     : result.get("tc_label", ""),
            "timestamp"    : result.get("timestamp", ""),
            "status"       : result.get("status", "FAIL"),
            "fail_reason"  : result.get("fail_reason", []),
            "steps"        : result.get("steps", []),
        })
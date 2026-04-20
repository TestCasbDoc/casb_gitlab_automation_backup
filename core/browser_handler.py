"""
core/browser_handler.py — Generic browser utilities shared across all apps.

Contains:
  - Tab management (open_fresh_tab)
  - Screenshot helpers
  - HAR recording (HarRecorder)
  - Countdown wait

Apps provide their own URL and wait_for_app() logic.
This file has ZERO app-specific knowledge.
"""

import os
import base64
import json
import time
from datetime import datetime


# ------------------------------------------------------------
# SCREENSHOT COUNTER
# ------------------------------------------------------------

_ss_counter = 0

def next_ss_counter():
    global _ss_counter
    _ss_counter += 1
    return _ss_counter

def reset_ss_counter():
    global _ss_counter
    _ss_counter = 0


# ------------------------------------------------------------
# TAB MANAGEMENT
# ------------------------------------------------------------

def open_fresh_tab(browser, url: str):
    """
    Open a new Playwright tab at the given URL, closing all existing tabs.
    Generic — works for any app URL.
    """
    print(f"\nOpening fresh tab -> {url}")
    old_pages = list(browser.pages)
    new_page  = browser.new_page()
    new_page.goto(url, wait_until="domcontentloaded")
    new_page.wait_for_timeout(8000)
    for old_page in old_pages:
        try:
            old_page.close()
        except Exception:
            pass
    print(f"   Tab ready: {url}")
    return new_page


# ------------------------------------------------------------
# SCREENSHOT
# ------------------------------------------------------------

def take_screenshot_b64(page, label: str, script_dir: str):
    """
    Take a screenshot of `page`, encode as base64 for HTML embedding,
    then DELETE the PNG file — screenshots live only in the HTML report.

    Label format  : TC1_BaseSendPost_step1_message_sent
    Temp file     : TC1_SS1_BaseSendPost_step1_message_sent_182917.png (deleted after read)
    """
    ss_num = next_ss_counter()
    ts     = datetime.now().strftime("%H%M%S")
    parts  = label.split("_", 1)
    name   = (f"{parts[0]}_SS{ss_num}_{parts[1]}_{ts}.png"
              if len(parts) == 2 else f"{label}_SS{ss_num}_{ts}.png")
    path   = os.path.join(script_dir, name)
    try:
        page.screenshot(path=path, full_page=False)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # Delete PNG — it is now embedded in the HTML report
        try:
            os.remove(path)
        except Exception:
            pass
        return b64, path
    except Exception as e:
        print(f"   [SS] Screenshot failed: {e}")
        return None, None


# ------------------------------------------------------------
# COUNTDOWN WAIT
# ------------------------------------------------------------

def countdown_wait(seconds: int):
    print(f"\nWaiting {seconds}s before next recipient...")
    for i in range(seconds, 0, -1):
        print(f"   {i}s remaining...", end="\r")
        time.sleep(1)
    print()


# ------------------------------------------------------------
# HAR RECORDER  (Playwright context listeners)
# ------------------------------------------------------------
# NOTE: Teams uses a shared service worker for API calls.
# Playwright context listeners capture page-level requests
# but miss service worker fetch calls (the actual POST).
# The HAR will contain CDN, auth and other requests but
# may not contain the Teams message POST itself.
#
# This is a known Playwright limitation with persistent context.
# The HAR is still useful — devs can see surrounding traffic
# and the fast.log separately confirms the exact POST URL.
# DO NOT route Chrome through a local proxy to fix this —
# that bypasses Versa SASE and breaks CASB blocking entirely.

# Dev failure keywords — if any fail_reason contains these, save HAR
_DEV_FAILURE_KEYWORDS = [
    "casb did not block", "application", "activity",
    "fast.log did not confirm", "not found in popup",
    "alertwindow did not confirm", "casb block", "signature",
    "could not send", "failed to send", "failed to type",
]

# Infra failure keywords — if ONLY these appear, discard HAR
_INFRA_FAILURE_KEYWORDS = [
    "ssh", "decryption", "ssl inspection", "vos stats clear",
    "pre-test clear", "app did not load",
]


def _is_dev_failure(fail_reasons: list) -> bool:
    if not fail_reasons:
        return False   # TC passed — save HAR
    reasons_lower = [r.lower() for r in fail_reasons]
    all_infra = all(
        any(kw in r for kw in _INFRA_FAILURE_KEYWORDS)
        for r in reasons_lower
    )
    return not all_infra


class HarRecorder:
    """
    Records HAR by listening to Playwright context request/response events.

    Usage:
        har = HarRecorder(page, "TC1_BaseSendPost", script_dir, capture_har=True)
        har.start()
        # ... send action ...
        har.stop()
        har.save_or_discard(fail_reasons)

    If capture_har=False (default), all methods are no-ops — zero overhead.
    Enable via: python run.py --capture-har
    """

    def __init__(self, page, tc_name: str, script_dir: str, capture_har: bool = False, capture_har_all: bool = False):
        self.page          = page
        self.tc_name       = tc_name
        self.script_dir    = script_dir
        self.capture_har     = capture_har
        self.capture_har_all = capture_har_all
        self.har_path      = None
        self._started      = False
        self._entries      = []
        self._pending      = {}
        self._req_handler  = None
        self._resp_handler = None
        self._context      = None

    def start(self):
        if not self.capture_har:
            print(f"   [HAR] Skipped (use --capture-har to enable)")
            return
        har_dir = os.path.join(self.script_dir, "har_files")
        os.makedirs(har_dir, exist_ok=True)
        self.har_path = os.path.join(har_dir, f"{self.tc_name}.har")
        self._entries = []
        self._pending = {}

        def _on_request(request):
            try:
                entry = {
                    "startedDateTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "time": 0,
                    "request": {
                        "method":      request.method,
                        "url":         request.url,
                        "httpVersion": "HTTP/1.1",
                        "headers":     [{"name": k, "value": v}
                                        for k, v in request.headers.items()],
                        "queryString": [],
                        "cookies":     [],
                        "headersSize": -1,
                        "bodySize":    -1,
                        "postData":    None,
                    },
                    "response": {
                        "status":      0,
                        "statusText":  "",
                        "httpVersion": "HTTP/1.1",
                        "headers":     [],
                        "cookies":     [],
                        "content":     {"size": 0, "mimeType": ""},
                        "redirectURL": "",
                        "headersSize": -1,
                        "bodySize":    -1,
                    },
                    "cache":   {},
                    "timings": {"send": 0, "wait": 0, "receive": 0},
                }
                try:
                    post_data = request.post_data
                    if post_data:
                        entry["request"]["postData"] = {
                            "mimeType": request.headers.get("content-type", ""),
                            "text":     post_data,
                        }
                        entry["request"]["bodySize"] = len(post_data.encode("utf-8", errors="replace"))
                except Exception:
                    pass
                self._pending[id(request)] = entry
            except Exception:
                pass

        def _on_response(response):
            try:
                entry = self._pending.pop(id(response.request), None)
                if entry is None:
                    return
                entry["response"]["status"]     = response.status
                entry["response"]["statusText"] = response.status_text
                entry["response"]["headers"]    = [
                    {"name": k, "value": v}
                    for k, v in response.headers.items()
                ]
                mime = response.headers.get("content-type", "")
                entry["response"]["content"]["mimeType"] = mime
                self._entries.append(entry)
            except Exception:
                pass

        self._req_handler  = _on_request
        self._resp_handler = _on_response
        self._context      = self.page.context
        self._context.on("request",  self._req_handler)
        self._context.on("response", self._resp_handler)
        self._started = True
        print(f"   [HAR] Recording started → {self.har_path}")

    def stop(self):
        if not self.capture_har or not self._started:
            return

        # Wait up to 3s for pending requests to receive responses.
        # MUST use page.wait_for_timeout() NOT time.sleep() —
        # Playwright response events fire on the same thread,
        # time.sleep() blocks the event loop so responses never arrive.
        import time as _time
        deadline = _time.time() + 3.0
        while self._pending and _time.time() < deadline:
            self.page.wait_for_timeout(100)   # yields to Playwright event loop

        try:
            self._context.remove_listener("request",  self._req_handler)
            self._context.remove_listener("response", self._resp_handler)
        except Exception as e:
            print(f"   [HAR] Stop listener error: {e}")
        self._started = False

        # Flush still-pending requests (no response received — e.g. CASB blocked).
        # Include them anyway so devs can see the POST URL + body in the HAR.
        if self._pending:
            print(f"   [HAR] {len(self._pending)} pending request(s) without response — including in HAR")
            for entry in self._pending.values():
                self._entries.append(entry)
            self._pending = {}

        print(f"   [HAR] Recording stopped — {len(self._entries)} entries captured for {self.tc_name}")

    def save_or_discard(self, fail_reasons: list = None):
        if not self.capture_har:
            return  # HAR not enabled — nothing to save
        save = self.capture_har_all or _is_dev_failure(fail_reasons) or not fail_reasons
        if save:
            if self._entries:
                har = {
                    "log": {
                        "version": "1.2",
                        "creator": {"name": "CASB Automation", "version": "1.0"},
                        "pages":   [],
                        "entries": self._entries,
                    }
                }
                try:
                    with open(self.har_path, "w", encoding="utf-8") as f:
                        json.dump(har, f, indent=2, ensure_ascii=False)
                    print(f"   [HAR] Saved: {self.har_path} ({len(self._entries)} entries)")
                except Exception as e:
                    print(f"   [HAR] Save failed: {e}")
            else:
                print(f"   [HAR] Nothing to save — 0 entries for {self.tc_name}")
        else:
            print(f"   [HAR] Infra failure — discarding HAR for {self.tc_name}")
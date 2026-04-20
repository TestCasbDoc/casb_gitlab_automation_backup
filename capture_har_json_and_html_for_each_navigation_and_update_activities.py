"""
capture_session.py
==================
Generic session capture tool — works for ANY web application,
including SPAs like OneDrive that never reach true network idle.

Simultaneously captures:
  1. HAR  — all network traffic (API calls, request/response bodies)
  2. UI   — every click (DOM element, selectors, container HTML)
             ↳ also captures clicks inside iframes / shadow dialogs

Produces exactly TWO files to upload to Claude:
  claude_upload_api.json  — API calls (endpoints, bodies, responses)
  claude_upload_ui.json   — UI clicks (selectors, element info, HTML)

Usage:
  python capture_session.py                         # prompts for URL
  python capture_session.py --url https://app.com
  python capture_session.py --url https://app.com --name myapp
  python capture_session.py --url https://app.com --keep-har

Steps:
  1. Run the script — Chromium opens
  2. Log in to the app if prompted
  3. Perform the action you want to capture  (go slowly)
     Each click flashes a RED outline in the browser
  4. Press ENTER when done  (NOT Ctrl+C)
  5. Two upload files are written automatically

Key design decisions:
  - POLLING instead of expose_binding: expose_binding() silently fails on
    Windows with launch_persistent_context. Instead, each frame stores clicks
    in its own local window.__clickQueue[] and a background Python thread
    drains every frame's queue via frame.evaluate() every second.
  - Per-frame local queues: cross-origin iframes (e.g. OneDrive share dialog
    on my.microsoftpersonalcontent.com) block window.top access. Each frame
    owns its own queue; the poller iterates page.frames to drain them all.
  - Short networkidle timeout: SPAs like OneDrive poll continuously and
    never reach true idle. We try 15s then fall back to DOM checks.
  - iframe injection: JS injected into every existing + new frame so clicks
    inside share dialogs and file pickers are captured too.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, BrowserContext, Frame


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args():
    p = argparse.ArgumentParser(
        description="Capture HAR + UI clicks for any web app -> 2 files for Claude"
    )
    p.add_argument("--url",      default="", help="Starting URL (prompted if omitted)")
    p.add_argument("--name",     default="", help="App name label used in output folder")
    p.add_argument("--out",      default="", help="Output folder (default: ~/Downloads/capture)")
    p.add_argument("--profile",  default="", help="Chromium profile dir (reuses login session)")
    p.add_argument("--keep-har", action="store_true",
                   help="Keep raw HAR after extraction (large -- off by default)")
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

def _setup_paths(args) -> dict:
    base     = args.out or os.path.join(os.path.expanduser("~"), "Downloads", "capture")
    run_ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    app_slug = re.sub(r"[^\w]", "_", args.name.strip()) if args.name.strip() else "app"
    run_id   = f"{app_slug}_{run_ts}"
    run_dir  = os.path.join(base, run_id)
    profile  = args.profile or os.path.join(base, "chromium_profile")

    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(profile, exist_ok=True)

    return {
        "run_id":   run_id,
        "run_dir":  run_dir,
        "har":      os.path.join(run_dir, "_raw.har"),
        "out_api":  os.path.join(run_dir, "claude_upload_api.json"),
        "out_ui":   os.path.join(run_dir, "claude_upload_ui.json"),
        "profile":  profile,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TOKEN / AUTH CAPTURE
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_HEADERS = [
    "authorization",
    "x-skypetoken", "skypetoken",
    "x-api-key", "x-auth-token", "x-access-token",
    "x-token", "api-key", "token",
    "x-csrf-token", "x-request-token",
]


@dataclass
class _TokenStore:
    bearer_token:  Optional[str] = None
    custom_tokens: dict          = field(default_factory=dict)
    _lock: threading.Lock        = field(default_factory=threading.Lock, repr=False)

    def update(self, url: str, headers: dict):
        with self._lock:
            for hdr in _AUTH_HEADERS:
                val = headers.get(hdr, "")
                if not val:
                    continue
                if hdr == "authorization" and val.lower().startswith("bearer "):
                    if not self.bearer_token:
                        self.bearer_token = val[7:]
                        print(f"[token] Bearer token captured (len={len(self.bearer_token)})")
                elif hdr not in self.custom_tokens:
                    self.custom_tokens[hdr] = val
                    print(f"[token] Auth header '{hdr}' captured (len={len(val)})")

    def summary(self) -> dict:
        return {
            "bearer_token_available": self.bearer_token is not None,
            "other_auth_headers":     list(self.custom_tokens.keys()),
        }


TOKEN = _TokenStore()

def _on_request(request):
    TOKEN.update(request.url, {k.lower(): v for k, v in request.headers.items()})


# ══════════════════════════════════════════════════════════════════════════════
#  HAR EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

_SKIP_EXT = {
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".woff", ".woff2", ".ttf", ".ico", ".webp", ".map", ".txt",
}

_SKIP_DOMAINS = {
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "facebook.net", "hotjar.com", "segment.io", "mixpanel.com",
    "amplitude.com", "sentry.io", "bugsnag.com", "newrelic.com",
    "cloudflare.com", "fonts.googleapis.com", "gravatar.com",
}

_ACTION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_API_PATH_HINTS = [
    "/api/", "/v1/", "/v2/", "/v3/", "/v4/",
    "/rest/", "/graphql", "/query",
    "/search", "/messages", "/users", "/auth",
    "/chat", "/conversations", "/feed",
]


def _is_api_call(entry: dict) -> bool:
    req    = entry["request"]
    url    = req["url"]
    method = req["method"].upper()
    parsed = urlparse(url)
    path   = parsed.path.lower()
    host   = parsed.netloc.lower()

    if any(d in host for d in _SKIP_DOMAINS):
        return False
    ext = os.path.splitext(path)[1]
    if ext in _SKIP_EXT:
        return False
    if method in _ACTION_METHODS:
        return True
    if method == "GET":
        resp_hdrs = {h["name"].lower(): h["value"].lower()
                     for h in entry.get("response", {}).get("headers", [])}
        if "application/json" in resp_hdrs.get("content-type", ""):
            return True
        if any(hint in path for hint in _API_PATH_HINTS):
            return True
        qs = parsed.query.lower()
        if any(k in qs for k in ["page=", "limit=", "offset=", "cursor=", "filter=", "q="]):
            return True
    return False


def _extract_body(post) -> Optional[dict | str]:
    text = (post or {}).get("text", "")
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text[:1000]


def _extract_resp(response: dict) -> Optional[dict | str]:
    text = (response.get("content", {}) or {}).get("text", "") or ""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text[:500]


def _parse_har(har_path: str) -> list[dict]:
    print(f"\n[har]  Parsing ...")
    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)
    entries = har.get("log", {}).get("entries", [])
    print(f"[har]  {len(entries)} total entries in raw HAR")

    calls = []
    for e in entries:
        if not _is_api_call(e):
            continue
        req    = e["request"]
        resp   = e.get("response", {})
        url    = req["url"]
        method = req["method"].upper()
        hdrs   = {h["name"].lower(): h["value"] for h in req.get("headers", [])}
        parsed = urlparse(url)

        auth_found = {}
        for hdr in _AUTH_HEADERS:
            val = hdrs.get(hdr, "")
            if val:
                auth_found[hdr] = f"{val[:40]}..." if len(val) > 40 else val

        calls.append({
            "method":        method,
            "url":           url,
            "host":          parsed.netloc,
            "path":          parsed.path,
            "query":         parsed.query,
            "status":        resp.get("status"),
            "timestamp":     e.get("startedDateTime", ""),
            "request_body":  _extract_body(req.get("postData")),
            "response_body": _extract_resp(resp),
            "auth_headers":  auth_found,
            "content_type":  hdrs.get("content-type", ""),
        })
        print(f"[har]    {method:6} {resp.get('status')} {parsed.netloc}{parsed.path[:60]}")

    print(f"[har]  {len(calls)} API calls extracted")
    return calls


# ══════════════════════════════════════════════════════════════════════════════
#  UI CLICK CAPTURE  —  POLLING DESIGN
#
#  Why polling instead of expose_binding?
#  expose_binding() silently fails on Windows when using
#  launch_persistent_context — window.__captureClick is undefined in the
#  browser so every click handler fires but nothing gets recorded in Python.
#
#  Solution:
#    JS side  -> pushes click data into window.__clickQueue[]
#    Python   -> background thread calls page.evaluate() every second to
#               drain that queue and save steps locally
# ══════════════════════════════════════════════════════════════════════════════

_steps: list[dict] = []
_step_lock = threading.Lock()


def _best_selectors(el: dict) -> list[str]:
    out = []
    for k, v in (el.get("data_attrs") or {}).items():
        if v and len(v) < 100:
            out.append(f"[{k}='{v}']")
    if el.get("aria"):
        out.append(f"[aria-label='{el['aria']}']")
    if el.get("id") and not re.search(r"\d{5,}", el["id"]):
        out.append(f"#{el['id']}")
    if el.get("role") and el.get("aria"):
        out.append(f"[role='{el['role']}'][aria-label='{el['aria']}']")
    if el.get("name"):
        out.append(f"[name='{el['name']}']")
    if el.get("placeholder"):
        out.append(f"[placeholder='{el['placeholder']}']")
    if el.get("text"):
        t = el["text"].strip().replace("'", "")[:50]
        if t:
            out.append(f"text={t}")
    if el.get("xpath"):
        out.append(f"xpath={el['xpath']}")
    return out


def _record_step(data: dict) -> None:
    with _step_lock:
        n  = len(_steps) + 1
        el = data.get("element", {})
        step = {
            "step":           n,
            "url":            data.get("url", ""),
            "tag":            el.get("tag", ""),
            "aria":           el.get("aria", ""),
            "role":           el.get("role", ""),
            "text":           (el.get("text", "") or "")[:80],
            "id":             el.get("id", ""),
            "name":           el.get("name", ""),
            "type":           el.get("type", ""),
            "placeholder":    el.get("placeholder", ""),
            "data_attrs":     el.get("data_attrs", {}),
            "xpath":          el.get("xpath", ""),
            "selectors":      _best_selectors(el),
            "container_html": (data.get("container_html", "") or "")[:2000],
        }
        _steps.append(step)
        label = (step["aria"] or step["text"] or
                 next(iter(step["data_attrs"].values()), None) or
                 step["id"] or step["name"] or "?")
        print(f"[step {n:02d}] {step['tag']} | {str(label)[:60]}")


# JS: each frame gets its OWN local window.__clickQueue[].
# We do NOT use window.top because cross-origin iframes (e.g. OneDrive share
# dialog on my.microsoftpersonalcontent.com) block access to the parent window.
# Python polls every live frame individually instead.
_CAPTURE_JS = """
(function() {
    var root = window;  // always local -- no cross-origin window.top access

    if (root.__captureInjected) return;
    root.__captureInjected = true;
    root.__clickQueue = root.__clickQueue || [];

    function getContainer(el) {
        var SEM_ROLES = ["dialog","menu","listbox","textbox","combobox","form",
            "navigation","main","region","alertdialog","tooltip",
            "tree","grid","table","search","banner","complementary"];
        var SEM_TAGS = ["FORM","DIALOG","DETAILS","ARTICLE","SECTION","NAV","MAIN","ASIDE"];
        var cur = el, depth = 0;
        while (cur && depth < 20) {
            if (!cur.getAttribute) break;
            var role = cur.getAttribute("role") || "";
            var tag  = (cur.tagName || "").toUpperCase();
            var hasDataId = Array.from(cur.attributes || []).some(function(a) {
                return a.name.startsWith("data-") && a.value && a.value.length < 100;
            });
            if (SEM_ROLES.indexOf(role) > -1 || SEM_TAGS.indexOf(tag) > -1 || hasDataId)
                return cur.outerHTML.slice(0, 5000);
            cur = cur.parentElement;
            depth++;
        }
        cur = el;
        for (var i = 0; i < 3 && cur && cur.parentElement; i++) cur = cur.parentElement;
        return cur ? cur.outerHTML.slice(0, 5000) : "";
    }

    function getXPath(el) {
        if (!el || el.nodeType !== 1) return "";
        if (el.id && !/\\d{5,}/.test(el.id)) return '//*[@id="' + el.id + '"]';
        var parts = [], node = el;
        while (node && node.nodeType === 1) {
            var idx = 1, sib = node.previousSibling;
            while (sib) {
                if (sib.nodeType === 1 && sib.tagName === node.tagName) idx++;
                sib = sib.previousSibling;
            }
            parts.unshift(node.tagName.toLowerCase() + "[" + idx + "]");
            node = node.parentNode;
        }
        return "/" + parts.join("/");
    }

    function getDataAttrs(el) {
        var out = {};
        Array.from(el.attributes || []).forEach(function(a) {
            if (a.name.startsWith("data-") && a.value && a.value.length < 120)
                out[a.name] = a.value;
        });
        return out;
    }

    document.addEventListener("click", function(e) {
        var el = e.target;
        var prev = el.style.outline;
        el.style.outline = "3px solid red";
        setTimeout(function() { el.style.outline = prev; }, 1200);
        root.__clickQueue.push({
            element: {
                tag:         el.tagName || "",
                text:        (el.innerText || "").slice(0, 150),
                id:          el.id || "",
                aria:        el.getAttribute("aria-label")   || "",
                role:        el.getAttribute("role")         || "",
                name:        el.getAttribute("name")         || "",
                type:        el.getAttribute("type")         || "",
                placeholder: el.getAttribute("placeholder") || "",
                href:        el.getAttribute("href")         || "",
                data_attrs:  getDataAttrs(el),
                xpath:       getXPath(el)
            },
            container_html: getContainer(el),
            url: window.location.href
        });
    }, true);
})();
"""

# Atomically drain the queue and return all items
_DRAIN_JS = """
(function() {
    if (!window.__clickQueue || window.__clickQueue.length === 0) return [];
    return window.__clickQueue.splice(0, window.__clickQueue.length);
})()
"""


def _drain_all_frames(page: Page) -> None:
    """Drain __clickQueue from every live frame on the MAIN thread.
    Playwright sync_api uses greenlets and must only be called from the
    main thread -- calling evaluate() from a background thread causes
    'greenlet.error: cannot switch to a different thread'.
    """
    try:
        for frame in page.frames:
            try:
                items = frame.evaluate(_DRAIN_JS)
                if items:
                    for item in items:
                        _record_step(item)
            except Exception:
                pass  # cross-origin or navigating frame -- skip safely
    except Exception:
        pass  # page mid-navigation


# ══════════════════════════════════════════════════════════════════════════════
#  IFRAME INJECTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _inject_into_frame(frame: Frame) -> None:
    try:
        frame.evaluate(_CAPTURE_JS)
    except Exception as exc:
        url_hint = ""
        try:
            url_hint = frame.url[:60]
        except Exception:
            pass
        print(f"[frame] Could not inject into frame ({url_hint}): {exc}")


def _inject_into_all_frames(page: Page) -> None:
    for frame in page.frames:
        _inject_into_frame(frame)
    print(f"[frame] Injected into {len(page.frames)} frame(s)")


# ══════════════════════════════════════════════════════════════════════════════
#  APP LOAD WAIT
# ══════════════════════════════════════════════════════════════════════════════

def _wait_for_app(page: Page, timeout: int = 60):
    print("\n[load]  Waiting for app ...")

    # Short networkidle attempt (SPAs like OneDrive never reach true idle)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
        print("[load]  Network idle")
        return
    except Exception:
        print("[load]  Network never went idle (SPA/polling app) -- checking DOM ...")

    # Fall back to DOM visibility
    generic_sels = [
        "nav", "header", "main", "[role='main']", "[role='navigation']",
        "#app", "#root", ".app", ".main",
        "[data-reactroot]", "[data-v-app]",
        "button:visible", "a:visible",
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in generic_sels:
            try:
                if page.locator(sel).first.is_visible(timeout=1000):
                    print(f"[load]  App loaded ({sel})")
                    return
            except Exception:
                pass
        time.sleep(1)

    print("[load]  Could not confirm load -- continuing")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    args  = _parse_args()
    paths = _setup_paths(args)

    url = args.url.strip()
    if not url:
        url = input("\n  Enter the app URL  (e.g. https://app.example.com): ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    print(f"\n{'=' * 60}")
    print(f"  Session Capture  ->  2 upload files for Claude")
    print(f"  App     : {url}")
    print(f"  Output  : {paths['run_dir']}")
    print(f"{'=' * 60}")

    with sync_playwright() as p:
        ctx: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir      = paths["profile"],
            headless           = False,
            record_har_path    = paths["har"],
            record_har_content = "embed",
            ignore_https_errors= True,
            args               = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--disable-infobars",
            ],
        )

        # add_init_script runs on every new document/frame automatically
        # NOTE: no expose_binding -- we use polling instead (see above)
        ctx.add_init_script(_CAPTURE_JS)

        page: Page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", _on_request)

        # NOTE: we do NOT call frame.evaluate() inside event callbacks --
        # Playwright sync_api callbacks run on a different greenlet and any
        # Playwright call from there causes "cannot switch to a different thread".
        # ctx.add_init_script() already injects _CAPTURE_JS into every new
        # frame/document automatically -- no manual injection needed here.
        def _on_frameattached(frame: Frame):
            try:
                print(f"[frame] New frame: {frame.url[:60]}")
            except Exception:
                pass

        page.on("frameattached", _on_frameattached)

        # Navigate
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        _wait_for_app(page)

        # Belt-and-suspenders: inject into all frames already present
        _inject_into_all_frames(page)
        try:
            page.evaluate(_CAPTURE_JS)
            print("[ui]    Click queue ready (main frame)")
        except Exception as e:
            print(f"[ui]    Direct inject note: {e}")

        print(f"\n{'=' * 60}")
        print(f"  CAPTURING -- perform your action now")
        print(f"  -> Go slowly -- each click flashes RED")
        print(f"  -> Complete the full flow from start to finish")
        print(f"  -> Clicks inside share dialogs / popups are captured too")
        print(f"  Press ENTER when done -- do NOT Ctrl+C")
        print(f"{'=' * 60}\n")

        # A tiny background thread ONLY watches for ENTER -- no Playwright calls.
        # All page.evaluate / frame.evaluate stay on the main thread below.
        _done = threading.Event()

        def _wait_for_enter():
            try:
                sys.stdin.readline()
            except Exception:
                pass
            _done.set()

        t = threading.Thread(target=_wait_for_enter, daemon=True)
        t.start()
        print("  [ Press ENTER when done ]\n")

        # Main-thread polling loop -- safe to call Playwright here
        while not _done.is_set():
            _drain_all_frames(page)
            time.sleep(1)

        # Final drain after ENTER
        _drain_all_frames(page)

        print(f"\n[ui]    {len(_steps)} clicks captured total")
        print("\n[stop]  Flushing HAR ...")

        # Give any in-flight network responses 3 s to land in the HAR buffer.
        time.sleep(3)

        # ctx.close() writes the HAR file and MUST run on the main thread.
        # We catch everything -- if it raises, the HAR is still written because
        # Playwright flushes to disk before raising on persistent-context close.
        try:
            ctx.close()
            print("[stop]  Context closed cleanly")
        except Exception as exc:
            print(f"[stop]  Close raised (HAR still written): {exc}")
        time.sleep(1)

    # ── Post-process ──────────────────────────────────────────────────────
    har_size  = os.path.getsize(paths["har"]) if os.path.exists(paths["har"]) else 0
    api_calls = []

    if har_size == 0:
        print("[har]   HAR empty -- use ENTER not Ctrl+C next time")
    else:
        print(f"[har]   Raw HAR: {har_size // 1024} KB")
        api_calls = _parse_har(paths["har"])
        if not args.keep_har:
            try:
                os.remove(paths["har"])
                print("[har]   Raw HAR deleted (--keep-har to retain)")
            except Exception:
                pass

    # ── claude_upload_api.json ────────────────────────────────────────────
    with open(paths["out_api"], "w", encoding="utf-8") as f:
        json.dump({
            "run_id":      paths["run_id"],
            "app_url":     url,
            "captured_at": datetime.now().isoformat(),
            "auth_tokens": TOKEN.summary(),
            "total_calls": len(api_calls),
            "api_calls":   api_calls,
        }, f, indent=2, ensure_ascii=False)
    api_kb = os.path.getsize(paths["out_api"]) // 1024
    print(f"\n[out]   claude_upload_api.json  ({api_kb} KB)  --  {len(api_calls)} API calls")

    # ── claude_upload_ui.json ─────────────────────────────────────────────
    with open(paths["out_ui"], "w", encoding="utf-8") as f:
        json.dump({
            "run_id":      paths["run_id"],
            "app_url":     url,
            "captured_at": datetime.now().isoformat(),
            "total_steps": len(_steps),
            "steps":       _steps,
        }, f, indent=2, ensure_ascii=False)
    ui_kb = os.path.getsize(paths["out_ui"]) // 1024
    print(f"[out]   claude_upload_ui.json   ({ui_kb} KB)  --  {len(_steps)} clicks")

    print(f"\n{'=' * 60}")
    print(f"  Done! Upload both files to Claude:")
    print(f"  1. {paths['out_api']}")
    print(f"  2. {paths['out_ui']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run()
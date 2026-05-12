"""
login_handler.py — Browser launch, Chrome session fixes, and login flows.

MOST LIKELY TO NEED UPDATES when:
  - Microsoft login page layout changes (OTP screen, Stay signed in, etc.)
  - Google OAuth flow changes
  - Teams marketing page layout changes
  - Chrome version changes (restore bubble behaviour)
"""
import os
import json as _json
import time as _time
import sys as _sys

# Add project root to path
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import (
    SCRIPT_DIR, RECIPIENT_CREDENTIALS, _recipient_browsers,
    get_recipient_creds, SSH_REQUIRED_FOR_PASS,
)

# Teams load selectors (duplicated here to avoid circular import)
TEAMS_LOADED_SELECTORS = [
    "[data-tid='chat-list']",
    "div[role='list']",
    "button[aria-label='Chat']",
    "text=New chat",
    "text=Recent",
]


def wait_for_teams(page, label=""):
    tag = f"[{label}] " if label else ""
    for attempt in range(36):
        for selector in TEAMS_LOADED_SELECTORS:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=3000)
                return True
            except Exception:
                continue
        page.wait_for_timeout(5000)
    return False

try:
    from pywinauto import Desktop
    from pywinauto.application import Application
except ImportError:
    Desktop = None
    Application = None


# ============================================================
# URL CLASSIFIERS
# ============================================================

def _current_url_is_google(url):
    u = url.lower()
    return "accounts.google.com" in u or "google.com/o/oauth" in u or "google.com/signin" in u


def _current_url_is_microsoft_login(url):
    u = url.lower()
    return (
        "login.live.com"         in u or
        "login.microsoftonline"  in u or
        "account.microsoft"      in u or
        "microsoftonline.com"    in u
    )


def _current_url_is_teams_app(url):
    u = url.lower()
    if "login.live.com" in u or "microsoftonline" in u or "login.microsoft" in u:
        return False
    return "teams.live.com/v2" in u or "teams.microsoft.com" in u


def _page_is_marketing(page):
    """
    Returns True if the page is the Teams marketing/landing page rather than
    the authenticated chat app.
    Update this if Teams changes their marketing page layout.
    """
    try:
        if page.locator("a:has-text('Sign in'), button:has-text('Sign in')").count() > 0:
            return True
        if page.locator("text=Video calls with anyone").count() > 0:
            return True
    except:
        pass
    return False


# ============================================================
# CHROME SESSION / RESTORE BUBBLE FIXES
# ============================================================

def patch_chrome_preferences_for_clean_exit(profile_dir):
    """
    Overwrite exit_type → 'Normal' in Chrome's Preferences JSON before launch
    so the 'Restore pages?' crash-recovery bubble never appears.
    """
    prefs_path = os.path.join(profile_dir, "Default", "Preferences")
    if not os.path.exists(prefs_path):
        print(f"   [PREF-PATCH] Preferences not found at {prefs_path} — skipping patch")
        return
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = _json.load(f)
        profile = prefs.setdefault("profile", {})
        old_exit = profile.get("exit_type", "(missing)")
        profile["exit_type"]     = "Normal"
        profile["exited_cleanly"] = True
        prefs.pop("session", None)
        profile.pop("last_was_default", None)
        with open(prefs_path, "w", encoding="utf-8") as f:
            _json.dump(prefs, f, indent=2)
        print(f"   [PREF-PATCH] exit_type patched: '{old_exit}' → 'Normal'")
    except Exception as e:
        print(f"   [PREF-PATCH] Failed to patch Preferences: {e}")


def dismiss_chrome_restore_bubble_pywinauto():
    """
    Use pywinauto UIA to click the ✕ on Chrome's native restore bubble.
    Works even when Playwright cannot see it in the DOM.
    """
    if Desktop is None:
        return
    deadline = _time.time() + 5
    found = False
    while _time.time() < deadline:
        try:
            desktop = Desktop(backend="uia")
            for win in desktop.windows():
                try:
                    title = win.window_text()
                    if "Chrome" not in title and "Teams" not in title and "Google" not in title:
                        continue
                    app = Application(backend="uia").connect(handle=win.handle)
                    dlg = app.window(handle=win.handle)
                    for elem in dlg.descendants(control_type="Button"):
                        try:
                            n = elem.window_text().strip().lower()
                            if n in ("close", "×", "x", "✕", ""):
                                parent_text = ""
                                try:
                                    parent_text = elem.parent().window_text().lower()
                                except:
                                    pass
                                if any(kw in parent_text for kw in
                                       ["restore", "crash", "shut down", "didn't"]):
                                    elem.click_input()
                                    print(f"   [RESTORE-DISMISS] Clicked ✕ on restore bubble via pywinauto")
                                    found = True
                                    return
                        except:
                            continue
                except:
                    continue
        except:
            pass
        _time.sleep(0.5)
    if not found:
        print(f"   [RESTORE-DISMISS] No restore bubble found via pywinauto (OK if already gone)")


# ============================================================
# LOGIN FORM HELPERS
# ============================================================

def _click_next_or_submit(page):
    """Try various ways to advance a login form."""
    for strategy in [
        lambda: page.get_by_role("button", name="Next").click(timeout=3000),
        lambda: page.locator("#identifierNext").click(timeout=3000),
        lambda: page.locator("#passwordNext").click(timeout=3000),
        lambda: page.locator('input[type="submit"]').click(timeout=3000),
        lambda: page.keyboard.press("Enter"),
    ]:
        try:
            strategy()
            return
        except:
            continue


def _dump_page_debug(page, label, screenshot_dir=None):
    sd = screenshot_dir or SCRIPT_DIR
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace(" ", "_").replace("/", "_")
    try:
        ss_path = os.path.join(sd, f"debug_{safe_label}_{ts}.png")
        page.screenshot(path=ss_path, full_page=True)
        print(f"   [DEBUG] Screenshot saved: {ss_path}")
    except Exception as e:
        print(f"   [DEBUG] Screenshot failed: {e}")
    try:
        html_path = os.path.join(sd, f"debug_{safe_label}_{ts}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"   [DEBUG] HTML dump saved: {html_path}")
    except Exception as e:
        print(f"   [DEBUG] HTML dump failed: {e}")
    try:
        visible_text = page.evaluate("""
            () => {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false);
                const texts = [];
                let node;
                while (node = walker.nextNode()) {
                    const t = node.textContent.trim();
                    if (t.length > 2) texts.push(t);
                }
                return [...new Set(texts)].slice(0, 40).join(' | ');
            }
        """)
        print(f"   [DEBUG] Page text: {visible_text[:500]}")
    except:
        pass


# ============================================================
# MICROSOFT ACCOUNT PICKER
# ============================================================

def _handle_microsoft_account_picker(page, email):
    """
    Handle the 'Choose an account' picker that sometimes appears when Microsoft
    recognises multiple previously-used accounts.
    Update selectors here if Microsoft changes the picker layout.
    """
    is_picker_url = "prompt=select_account" in page.url
    if not is_picker_url:
        for sel in [f'[data-identifier="{email}"]', '#otherTile', 'div[data-viewid="5"]']:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=2000)
                is_picker_url = True
                break
            except:
                continue

    if not is_picker_url:
        print(f"   [LOGIN] No account picker — skipping picker step")
        return False

    print(f"   [LOGIN] Account picker present.")
    try:
        acct = page.locator(f'[data-identifier="{email}"]')
        if acct.is_visible(timeout=2000):
            acct.click()
            print(f"   [LOGIN] Clicked account tile for: {email}")
            page.wait_for_timeout(3000)
            return True
    except:
        pass

    for label_str, strategy in [
        ("#otherTile",           lambda: page.locator('#otherTile').click(timeout=3000)),
        ("text Use another",     lambda: page.get_by_text("Use another account", exact=True).click(timeout=3000)),
        ("role Use another",     lambda: page.get_by_role("button", name="Use another account").click(timeout=3000)),
        ("li:last-child",        lambda: page.locator('ul[role="listbox"] li:last-child').click(timeout=3000)),
    ]:
        try:
            strategy()
            print(f"   [LOGIN] Picker dismissed via: {label_str}")
            page.wait_for_timeout(2500)
            return True
        except:
            continue

    # JS fallback
    js_result = page.evaluate("""
        () => {
            const candidates = [
                document.querySelector('#otherTile'),
                document.querySelector('[data-value="other"]'),
                ...[...document.querySelectorAll('a, button, div[role="button"], li')]
                    .filter(el => (el.textContent || '').toLowerCase().includes('another account')),
            ].filter(Boolean);
            if (candidates.length === 0) return 'no candidates found';
            candidates[0].click();
            return 'clicked: ' + (candidates[0].id || candidates[0].textContent.trim().slice(0,40));
        }
    """)
    print(f"   [LOGIN] JS picker result: {js_result}")
    if "no candidates" not in str(js_result):
        page.wait_for_timeout(3000)
        return True
    return False


# ============================================================
# GOOGLE LOGIN
# ============================================================

def _handle_google_login(page, email, password):
    """
    Handle Google OAuth flow.
    Update if Google changes their sign-in page layout.
    """
    print(f"   [LOGIN] Google OAuth — logging in as {email}")
    try:
        acct = page.locator(f'[data-identifier="{email}"]')
        if acct.is_visible(timeout=3000):
            acct.click()
            print(f"   [LOGIN] Clicked existing Google account: {email}")
            page.wait_for_timeout(4000)
            current_url = page.url.lower()
            if _current_url_is_teams_app(current_url):
                return True
    except:
        pass

    # Enter email
    for sel in ['input[type="email"]', '#identifierId', 'input[name="identifier"]']:
        try:
            inp = page.locator(sel)
            inp.wait_for(state="visible", timeout=5000)
            inp.fill("")
            inp.type(email, delay=60)
            page.wait_for_timeout(400)
            _click_next_or_submit(page)
            print(f"   [LOGIN] Google email entered via {sel}")
            break
        except:
            continue

    page.wait_for_timeout(3000)

    # Enter password
    for sel in ['input[type="password"]', '#password input', 'input[name="Passwd"]']:
        try:
            pwd = page.locator(sel)
            pwd.wait_for(state="visible", timeout=5000)
            pwd.fill("")
            pwd.type(password, delay=60)
            page.wait_for_timeout(400)
            _click_next_or_submit(page)
            print(f"   [LOGIN] Google password entered via {sel}")
            break
        except:
            continue

    page.wait_for_timeout(5000)
    return True


# ============================================================
# MICROSOFT LOGIN
# ============================================================

# Selectors to try for the MS email input field
MS_EMAIL_SELECTORS = [
    "#usernameEntry",
    'input[type="email"]',
    'input[name="loginfmt"]',
    'input[id="i0116"]',
    'input[placeholder*="mail"]',
    'input[placeholder*="phone"]',
]


def _handle_microsoft_login(page, email, password):
    """
    Handle Microsoft login flow including:
      - Account picker
      - 'Get a code to sign in' OTP screen → click 'Use your password'
      - Password entry
      - 'Stay signed in?' prompt

    UPDATE THIS FUNCTION if Microsoft changes:
      - The email input field selector
      - The OTP screen layout
      - The 'Use your password' link
      - The 'Stay signed in' button
    """
    print(f"   [LOGIN] Microsoft login for: {email}")
    page.wait_for_timeout(2000)
    current_url = page.url.lower()

    # Account picker
    _handle_microsoft_account_picker(page, email)
    page.wait_for_timeout(1500)
    current_url = page.url.lower()

    if _current_url_is_google(current_url):
        return _handle_google_login(page, email, password)
    if _current_url_is_teams_app(current_url):
        return True

    # Enter email
    email_entered = False
    for sel in MS_EMAIL_SELECTORS:
        try:
            inp = page.locator(sel)
            inp.wait_for(state="visible", timeout=4000)
            inp.fill("")
            inp.type(email, delay=60)
            page.wait_for_timeout(400)
            _click_next_or_submit(page)
            print(f"   [LOGIN] MS email entered via {sel}")
            email_entered = True
            break
        except:
            continue

    if not email_entered:
        print(f"   [LOGIN] Could not enter MS email — dumping page debug")
        _dump_page_debug(page, "ms_email_fail")
        return False

    page.wait_for_timeout(3000)
    current_url = page.url.lower()

    if _current_url_is_google(current_url):
        return _handle_google_login(page, email, password)
    if _current_url_is_teams_app(current_url):
        return True

    # Detect OTP screen: "Get a code to sign in"
    otp_screen = False
    for otp_sel in [
        "text=Get a code to sign in",
        "text=Send code",
        "text=We'll send a code",
    ]:
        try:
            if page.locator(otp_sel).count() > 0:
                otp_screen = True
                break
        except:
            pass

    if otp_screen:
        print(f"   [LOGIN] OTP screen detected — clicking 'Use your password'")
        clicked_password = False
        for pwd_link in [
            lambda: page.get_by_text("Use your password", exact=True).click(timeout=4000),
            lambda: page.get_by_role("link", name="Use your password").click(timeout=4000),
            lambda: page.get_by_role("button", name="Use your password").click(timeout=4000),
            lambda: page.locator("a:has-text('Use your password')").first.click(timeout=4000),
            lambda: page.locator("button:has-text('Use your password')").first.click(timeout=4000),
        ]:
            try:
                pwd_link()
                clicked_password = True
                print(f"   [LOGIN] Clicked 'Use your password'")
                page.wait_for_timeout(2000)
                break
            except:
                continue

        if clicked_password:
            current_url = page.url.lower()
            if _current_url_is_google(current_url):
                return _handle_google_login(page, email, password)
            if _current_url_is_teams_app(current_url):
                return True

            # Enter password after OTP bypass
            print(f"   [LOGIN] Looking for password field after 'Use your password'...")
            for pwd_sel in ['input[type="password"]', '#password', 'input[name="passwd"]']:
                try:
                    pwd_inp = page.locator(pwd_sel)
                    pwd_inp.wait_for(state="visible", timeout=5000)
                    pwd_inp.fill("")
                    pwd_inp.type(password, delay=60)
                    page.wait_for_timeout(400)
                    _click_next_or_submit(page)
                    print(f"   [LOGIN] Password entered via {pwd_sel}")
                    page.wait_for_timeout(4000)
                    current_url = page.url.lower()
                    print(f"   [LOGIN] After password, URL: {page.url}")

                    # Dismiss Chrome Save password bubble
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    except:
                        pass

                    # Stay signed in?
                    for stay_sel in [
                        lambda: page.get_by_role("button", name="Yes").click(timeout=4000),
                        lambda: page.locator("button:has-text('Yes')").first.click(timeout=3000),
                        lambda: page.locator("#acceptButton").click(timeout=3000),
                        lambda: page.locator("input[value='Yes']").click(timeout=3000),
                    ]:
                        try:
                            stay_sel()
                            print(f"   [LOGIN] Clicked 'Yes' on Stay signed in")
                            page.wait_for_timeout(4000)
                            current_url = page.url.lower()
                            break
                        except:
                            continue

                    print(f"   [LOGIN] After Stay signed in, URL: {page.url}")
                    if _current_url_is_google(current_url):
                        return _handle_google_login(page, email, password)
                    if _current_url_is_teams_app(current_url):
                        return True
                    print(f"   [LOGIN] Navigating to Teams after MS password login...")
                    page.goto("https://teams.live.com/v2/", wait_until="domcontentloaded")
                    page.wait_for_timeout(5000)
                    return True
                except:
                    continue

    # Standard MS password entry (no OTP screen)
    print(f"   [LOGIN] Attempting Microsoft password field...")
    for pwd_sel in ['input[type="password"]', '#i0118', 'input[name="passwd"]']:
        try:
            pwd = page.locator(pwd_sel)
            pwd.wait_for(state="visible", timeout=5000)
            pwd.fill("")
            pwd.type(password, delay=60)
            page.wait_for_timeout(400)
            _click_next_or_submit(page)
            print(f"   [LOGIN] MS password entered via {pwd_sel}")
            break
        except:
            continue

    page.wait_for_timeout(4000)
    current_url = page.url.lower()

    if _current_url_is_google(current_url):
        return _handle_google_login(page, email, password)
    if _current_url_is_teams_app(current_url):
        return True

    # Check for 'Continue to Google' intermediate page
    print(f"   [LOGIN] Checking for 'Continue to Google' intermediate page...")
    for cont_strategy in [
        lambda: page.get_by_text("Sign in with Google").click(timeout=4000),
        lambda: page.get_by_role("button", name="Continue").click(timeout=4000),
        lambda: page.get_by_role("link", name="Continue").click(timeout=4000),
        lambda: page.locator('button:has-text("Google")').first.click(timeout=3000),
    ]:
        try:
            cont_strategy()
            print(f"   [LOGIN] Clicked Continue/Google")
            page.wait_for_timeout(3000)
            current_url = page.url.lower()
            if _current_url_is_google(current_url):
                return _handle_google_login(page, email, password)
            if _current_url_is_teams_app(current_url):
                return True
            break
        except:
            continue

    # Stay signed in?
    page.wait_for_timeout(2000)
    try:
        stay = page.get_by_role("button", name="Yes")
        if stay.is_visible(timeout=3000):
            stay.click()
            page.wait_for_timeout(3000)
            print(f"   [LOGIN] Clicked 'Stay signed in'")
    except:
        pass

    print(f"   [LOGIN] Final URL: {page.url}")
    return True


# ============================================================
# TEAMS NAVIGATION — full redirect chain handler
# ============================================================

def navigate_to_teams_chat(page, email, password):
    """
    Navigate the given page to the Teams chat app, handling:
      - Session still valid (fast path)
      - Session expired → marketing page → Sign in → MS/Google login
      - Retry on network timeout (CASB block from previous run)

    UPDATE THIS FUNCTION if Teams changes their redirect chain or
    marketing page Sign in button.
    """
    print(f"   [RECIPIENT] Navigating to Teams for: {email}")

    for nav_attempt in range(3):
        try:
            page.goto("https://teams.live.com/v2/", wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as nav_err:
            print(f"   [RECIPIENT] Navigation attempt {nav_attempt+1} failed: {nav_err}")
            if nav_attempt < 2:
                print(f"   [RECIPIENT] Retrying in 5s...")
                page.wait_for_timeout(5000)
            else:
                print(f"   [RECIPIENT] All /v2/ attempts failed — trying /free/ as fallback")
                try:
                    page.goto("https://teams.live.com/free/", wait_until="domcontentloaded", timeout=20000)
                except:
                    print(f"   [RECIPIENT] Network unreachable — cannot login")
                    return False

    page.wait_for_timeout(5000)
    current_url = page.url.lower()
    print(f"   [RECIPIENT] Landing URL: {page.url}")

    # Poll up to 12s to confirm session is genuinely valid
    if _current_url_is_teams_app(current_url) and not _page_is_marketing(page):
        print(f"   [RECIPIENT] URL shows /v2/ — polling to confirm session (up to 12s)...")
        session_confirmed = False
        for poll in range(12):
            page.wait_for_timeout(1000)
            current_url = page.url.lower()
            on_marketing = _page_is_marketing(page)
            print(f"   [RECIPIENT] Poll {poll+1}/12 — URL: {page.url[:60]}... marketing={on_marketing}")
            if on_marketing or ("teams.live.com/free" in current_url):
                print(f"   [RECIPIENT] Session EXPIRED — marketing page appeared at poll {poll+1}")
                break
            if _current_url_is_teams_app(current_url):
                for sel in TEAMS_LOADED_SELECTORS:
                    try:
                        page.locator(sel).first.wait_for(state="visible", timeout=1500)
                        print(f"   [RECIPIENT] Chat UI confirmed at poll {poll+1} (matched: {sel})")
                        session_confirmed = True
                        break
                    except:
                        continue
                if session_confirmed:
                    break
        if session_confirmed:
            print(f"   [RECIPIENT] Session valid — Teams chat UI loaded.")
            return True
        print(f"   [RECIPIENT] Session check failed — proceeding to login. URL: {page.url}")
        current_url = page.url.lower()
    elif _page_is_marketing(page):
        print(f"   [RECIPIENT] Marketing page detected on initial load (session expired)")

    current_url = page.url.lower()

    if "teams.live.com/free" in current_url or _page_is_marketing(page) or (
        "teams.live.com" in current_url and "/v2" not in current_url
    ):
        print(f"   [RECIPIENT] Marketing page detected — clicking Sign in...")
        for sign_in in [
            lambda: page.get_by_role("link", name="Sign in").click(timeout=5000),
            lambda: page.get_by_role("button", name="Sign in").click(timeout=5000),
            lambda: page.get_by_text("Sign in").first.click(timeout=5000),
            lambda: page.locator("a:has-text('Sign in')").first.click(timeout=5000),
        ]:
            try:
                sign_in()
                print(f"   [RECIPIENT] Clicked Sign in.")
                break
            except:
                continue

        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except:
            pass
        page.wait_for_timeout(2000)

        print(f"   [RECIPIENT] Waiting for redirect to MS/Google login page (up to 30s)...")
        try:
            page.wait_for_url(
                lambda url: (
                    "login.live.com" in url or
                    "login.microsoftonline" in url or
                    "accounts.google.com" in url or
                    ("teams.live.com/v2" in url and "#/" not in url and "free" not in url)
                ),
                timeout=30000,
            )
            print(f"   [RECIPIENT] Redirect settled: {page.url}")
        except:
            print(f"   [RECIPIENT] wait_for_url timed out — current URL: {page.url}")

        current_url = page.url.lower()
        print(f"   [RECIPIENT] After Sign in redirect settled: {page.url}")

    if _current_url_is_google(current_url):
        print(f"   [RECIPIENT] Landed on Google OAuth.")
        _handle_google_login(page, email, password)
    elif _current_url_is_microsoft_login(current_url):
        print(f"   [RECIPIENT] Landed on Microsoft login page.")
        _handle_microsoft_login(page, email, password)
    elif _current_url_is_teams_app(current_url) and "#/" not in page.url:
        print(f"   [RECIPIENT] Already authenticated — Teams app loaded.")

    page.wait_for_timeout(4000)
    try:
        stay = page.get_by_role("button", name="Yes")
        if stay.is_visible(timeout=3000):
            stay.click()
            page.wait_for_timeout(3000)
            print(f"   [RECIPIENT] Clicked 'Stay signed in' (post-login).")
    except:
        pass

    current_url = page.url.lower()

    # Late login page detection
    if _current_url_is_microsoft_login(current_url):
        print(f"   [RECIPIENT] Late MS login page detected — logging in...")
        _handle_microsoft_login(page, email, password)
        page.wait_for_timeout(4000)
        current_url = page.url.lower()
    elif _current_url_is_google(current_url):
        print(f"   [RECIPIENT] Late Google login page detected — logging in...")
        _handle_google_login(page, email, password)
        page.wait_for_timeout(4000)
        current_url = page.url.lower()

    if not _current_url_is_teams_app(current_url) or _page_is_marketing(page):
        print(f"   [RECIPIENT] Not yet on Teams chat — navigating to /v2/ directly...")
        page.goto("https://teams.live.com/v2/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

    return wait_for_teams(page, label="RECIPIENT")


# ============================================================
# PRE-LAUNCH RECIPIENT BROWSERS
# ============================================================

def pre_launch_recipient_browsers(playwright):
    """Launch and log in recipient browsers before any CASB test runs."""
    from config import RECIPIENT_CREDENTIALS, _recipient_browsers

    print(f"\n{'=' * 55}")
    print("PRE-LAUNCH: Starting recipient browsers...")
    print(f"{'=' * 55}")

    success_count = 0
    for recipient_name, creds in RECIPIENT_CREDENTIALS.items():
        email       = creds["email"]
        password    = creds["password"]
        profile_dir = creds["profile_dir"]

        print(f"\n   [PRE-LAUNCH] Launching browser for: {recipient_name} ({email})")
        os.makedirs(profile_dir, exist_ok=True)
        patch_chrome_preferences_for_clean_exit(profile_dir)

        browser = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="chrome",
            headless=False,
            slow_mo=300,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--start-maximized",
                "--no-first-run",
                "--disable-session-crashed-bubble",
                "--no-default-browser-check",
                "--hide-crash-restore-bubble",
            ],
            ignore_default_args=["--enable-automation"],
            viewport=None,
            ignore_https_errors=True,  # Trust Versa SASE intercepted/self-signed certs
        )

        existing_pages = list(browser.pages)
        print(f"   [PRE-LAUNCH] Pages on launch: {len(existing_pages)}")

        if len(existing_pages) == 0:
            page = browser.new_page()
        elif len(existing_pages) == 1:
            page = existing_pages[0]
            try:
                page.goto("about:blank", wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            except:
                pass
        else:
            page = browser.new_page()
            try:
                page.goto("about:blank", wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            except:
                pass
            for old_pg in existing_pages:
                try:
                    old_pg.close()
                    print(f"   [PRE-LAUNCH] Closed stale page")
                except:
                    pass

        dismiss_chrome_restore_bubble_pywinauto()

        loaded = navigate_to_teams_chat(page, email, password)
        if loaded:
            _recipient_browsers[recipient_name] = (browser, page)
            print(f"   [PRE-LAUNCH] ✓ '{recipient_name}' Teams loaded and ready")
            success_count += 1
        else:
            print(f"   [PRE-LAUNCH] ✗ '{recipient_name}' Teams did NOT load — delivery check will fail")
            _recipient_browsers[recipient_name] = (browser, page)

    print(f"\n   [PRE-LAUNCH] Done. {success_count}/{len(RECIPIENT_CREDENTIALS)} recipient browsers ready.")
    print(f"{'=' * 55}")


def close_recipient_browsers():
    """Close all pre-launched recipient browsers."""
    from config import _recipient_browsers
    for name, (browser, page) in list(_recipient_browsers.items()):
        try:
            browser.close()
            print(f"   [CLEANUP] Closed recipient browser for: {name}")
        except:
            pass
    _recipient_browsers.clear()


# ============================================================
# ENTRY POINT — called by core/runner.py
# ============================================================

def login(browser, account_type: str, cfg):
    """
    Called by runner.py before the test loop.
    Navigates to Teams and completes the login flow.
    """
    page = browser.pages[0] if browser.pages else browser.new_page()
    navigate_to_teams_chat(page, cfg.SENDER_EMAIL, cfg.SENDER_PASSWORD)
    print(f"   [LOGIN] MS Teams login complete (account_type={account_type})")

# ============================================================
# BROWSER MIXIN — consumed by activities.py class builder
# ============================================================

class BrowserMixin:

    def _open_fresh_tab(self):
        app_url = self.app_config.get("app_url", "https://teams.live.com/v2/")
        try:
            existing = self.browser.pages
        except AttributeError:
            existing = []
        page = existing[0] if existing else self.browser.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.goto(app_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"   [BROWSER] goto {app_url} failed: {e} — continuing anyway")
        return page

    def _wait_for_app(self, page) -> bool:
        import config as _cfg
        for sel in TEAMS_LOADED_SELECTORS:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=3000)
                return True
            except Exception:
                continue
        print("   [BROWSER] Teams not loaded — re-navigating...")
        navigate_to_teams_chat(page, _cfg.SENDER_EMAIL, _cfg.SENDER_PASSWORD)
        return wait_for_teams(page, label="SENDER")

    def _api_headers(self, page, extra: dict = None) -> dict:
        skype_token = ""
        try:
            for c in page.context.cookies():
                if c.get("name", "").lower() in ("skypetoken_asm", "skypetoken"):
                    skype_token = c.get("value", "")
                    break
        except Exception:
            pass
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Skypetoken": skype_token,
            "BehaviorOverride": "redirectAs404",
        }
        if extra:
            headers.update(extra)
        return headers

    def _click_chat_by_name(self, page, name: str) -> bool:
        for strategy in [
            lambda: page.locator(f"xpath=//span[normalize-space(text())='{name}']").first.click(timeout=5000),
            lambda: page.get_by_text(name, exact=True).first.click(timeout=5000),
            lambda: page.get_by_text(name).first.click(timeout=5000),
        ]:
            try:
                strategy(); return True
            except Exception:
                continue
        return False

    def _open_chat_via_search(self, page, name: str) -> bool:
        for sel in ["[data-tid='AUTOSUGGEST_INPUT']", "#ms-searchux-input",
                    "button[aria-label='New chat']"]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="visible", timeout=4000); el.click()
                page.wait_for_timeout(500); break
            except Exception:
                continue
        typed = False
        for sel in ["[data-tid='AUTOSUGGEST_INPUT']", "#ms-searchux-input",
                    "div[contenteditable='true']"]:
            try:
                box = page.locator(sel).first
                box.wait_for(state="visible", timeout=4000)
                box.fill(""); box.type(name, delay=80)
                page.wait_for_timeout(1500); typed = True; break
            except Exception:
                continue
        if not typed:
            return False
        for sel in [f"xpath=//li[.//span[normalize-space(text())='{name}']]",
                    f"[data-tid='searchResult']:has-text('{name}')",
                    f"text={name}"]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="visible", timeout=5000); el.click()
                page.wait_for_timeout(2000); return True
            except Exception:
                continue
        try:
            page.keyboard.press("Enter"); page.wait_for_timeout(2000); return True
        except Exception:
            return False

    def _extract_thread_id(self, page, chat_name: str) -> str:
        import re
        from urllib.parse import unquote
        try:
            raw = page.url or ""
            url = unquote(raw)
            # Consumer IDs look like 19:uni01_xxx@thread.v2 — not hex-only (old regex missed them).
            for pat in (
                r"[#/]conversations/([^/?#&]+)",
                r"conversations/([^/?#&]+)",
            ):
                m = re.search(pat, url, re.IGNORECASE)
                if m:
                    tid = unquote(m.group(1)).strip().rstrip("/")
                    if tid and len(tid) > 10:
                        return tid
        except Exception:
            pass
        for attr in ("data-thread-id", "data-conversation-id"):
            try:
                val = page.locator(f"[{attr}]").first.get_attribute(attr)
                if val and len(val) > 10:
                    return unquote(val.strip())
            except Exception:
                continue
        return ""

    def _get_sender_identity(self, page) -> tuple:
        name = ""
        for sel in ["button[aria-label*='Profile picture']",
                    "button[aria-label*='profile']"]:
            try:
                label = page.locator(sel).first.get_attribute("aria-label") or ""
                if label:
                    name = label.replace("Profile picture for", "").strip(); break
            except Exception:
                continue
        return "", name

    def _find_thread_id_via_api(self, page, recipient_name: str) -> str:
        try:
            url = (
                "https://teams.live.com/api/chatsvc/consumer/v1/users/ME/conversations"
                "?startTime=0&pageSize=200&view=msnp24Equivalent"
            )
            resp = page.request.get(url, headers=self._api_headers(page))
            if not resp.ok:
                return ""
            name_lower = recipient_name.lower().strip()
            if not name_lower:
                return ""
            for conv in resp.json().get("conversations", []) or []:
                tid = (conv.get("id") or "").strip()
                if not tid:
                    continue
                tp = conv.get("threadProperties") or {}
                parts = [
                    str(tp.get("topic") or ""),
                    str(tp.get("title") or ""),
                    str(conv.get("displayName") or conv.get("chatName") or conv.get("name") or ""),
                ]
                blob = " ".join(parts).lower()
                if name_lower in blob:
                    return tid
                for mem in conv.get("members") or []:
                    if not isinstance(mem, dict):
                        continue
                    disp = (mem.get("displayName") or mem.get("name") or "").lower()
                    if name_lower in disp:
                        return tid
        except Exception:
            pass
        return ""

    def _dismiss_windows_firewall(self):
        if Desktop is None:
            return
        import time as _t
        deadline = _t.time() + 3
        while _t.time() < deadline:
            try:
                for win in Desktop(backend="win32").windows():
                    try:
                        title = (win.window_text() or "").lower()
                        if "firewall" in title or "windows security" in title:
                            for btn in ("Allow access", "Allow", "Cancel"):
                                try:
                                    win.child_window(title=btn, control_type="Button").click_input()
                                    return
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception:
                pass
            _t.sleep(0.5)
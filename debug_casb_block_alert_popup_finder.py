"""
debug_casb_block_alert_popup_finder.py

PURPOSE:
    Identifies the exact Versa CASB AlertWindow title and class name
    on YOUR machine. Run this once when setting up a new app or when
    the popup window properties are unknown.

HOW TO USE:
    1. Make sure Versa Secure Access Client is running and CASB policy is active
    2. Run this script:
           python debug_casb_block_alert_popup_finder.py
    3. Script captures a baseline of all currently open windows
    4. YOU manually trigger a CASB block — do any blocked activity in any app
       (e.g. send a message in MS Teams, upload a file, post on Instagram etc.)
    5. Script detects and prints any NEW windows that appear
    6. Look for the Versa popup in the output — note the TITLE and CLASS
    7. Update versa_handler.py with the exact title/class found

OUTPUT EXAMPLE:
    [5s] *** NEW WINDOW(S) DETECTED ***
       TITLE   : 'AlertWindow'
       CLASS   : 'VersaSecureAccessClient.Alerts'
       BACKEND : uia

NOTE:
    This script does NOT send any message or open any browser.
    You trigger the block manually — works for ANY app, ANY activity.
"""

import time
from pywinauto import Desktop


# ── Config ────────────────────────────────────────────────────────────────────

WATCH_DURATION_SECONDS = 120   # how long to watch for new windows
POLL_INTERVAL_SECONDS  = 0.2   # how often to check (fast polling to catch short-lived popups)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_all_window_titles():
    """Returns a set of (title, class, backend) for all open windows."""
    found = set()
    for backend in ["uia", "win32"]:
        try:
            desktop = Desktop(backend=backend)
            for win in desktop.windows():
                try:
                    title = win.window_text().strip()
                    cls   = win.class_name().strip()
                    if title:
                        found.add((title, cls, backend))
                except Exception:
                    pass
        except Exception:
            pass
    return found


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("=" * 60)
    print("  VERSA CASB POPUP WINDOW FINDER")
    print("=" * 60)
    print()
    print("INSTRUCTIONS:")
    print("  1. This script is now watching all open windows")
    print("  2. Go to your app (MS Teams, Instagram, etc.)")
    print("  3. Perform any activity that CASB should block")
    print("     e.g. send a message, upload a file, post content")
    print("  4. When the Versa popup appears, check output below")
    print("  5. Note the TITLE and CLASS — update versa_handler.py")
    print()
    print(f"Watching for {WATCH_DURATION_SECONDS} seconds...")
    print("-" * 60)

    # Snapshot baseline BEFORE user triggers block
    baseline_windows = get_all_window_titles()
    print(f"Baseline captured: {len(baseline_windows)} windows currently open")

    # Warn if AlertWindow is already open — show details but keep watching
    already_open = [(t, c, b) for t, c, b in baseline_windows if "AlertWindow" in t]
    if already_open:
        print()
        print("WARNING: AlertWindow already open — details below.")
        print("   Close the popup, trigger a fresh block, and watch for new detections below...")
        print()
        for t, c, b in already_open:
            print(f"   TITLE   : '{t}'  <- ✅ CASB POPUP (already open)")
            print(f"   CLASS   : '{c}'")
            print(f"   BACKEND : {b}")
            print()



    print()
    print(">>> Waiting for you to trigger a CASB block... <<<")
    print()

    detected = []

    for i in range(WATCH_DURATION_SECONDS):
        current_windows = get_all_window_titles()
        new_windows     = current_windows - baseline_windows

        if new_windows:
            print(f"\n[{i}s] *** NEW WINDOW(S) DETECTED ***")
            for title, cls, backend in sorted(new_windows):
                # Identify if this is the CASB AlertWindow
                is_casb = "AlertWindow" in title and "VersaSecureAccessClient" in cls
                is_noise = any(x in title for x in [
                    "MediaContextNotificationWindow",
                    "SystemResourceNotifyWindow",
                ]) or cls == "Chrome_WidgetWin_1"
                tag = "  ← ✅ CASB POPUP (use this)" if is_casb else (
                      "  ← ⚠ noise (ignore)" if is_noise else "")
                print(f"   TITLE   : '{title}'{tag}")
                print(f"   CLASS   : '{cls}'")
                print(f"   BACKEND : {backend}")
                print()
                if not is_noise:
                    detected.append((title, cls, backend))

            # Update baseline — only show truly new windows each iteration
            baseline_windows = current_windows
        else:
            remaining = WATCH_DURATION_SECONDS - i
            print(f"[{i}s] No new windows yet... ({remaining}s remaining)", end="\r")

        time.sleep(POLL_INTERVAL_SECONDS)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n")
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    if detected:
        print(f"\n{len(detected)} new window(s) detected during the session:\n")
        for title, cls, backend in detected:
            print(f"   TITLE   : '{title}'")
            print(f"   CLASS   : '{cls}'")
            print(f"   BACKEND : {backend}")
            print()
    else:
        print("\nNo new windows were detected during the watch period.")
        print("Possible reasons:")
        print("  - CASB policy may not be active")
        print("  - Activity was not blocked")
        print("  - Popup appeared and closed before detection (try increasing WATCH_DURATION_SECONDS)")
        print("  - Versa Secure Access Client may not be running")
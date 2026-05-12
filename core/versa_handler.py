"""
versa_handler.py — Versa CASB interaction: CLI commands, AlertWindow popup,
                   and fast.log SSH capture/validation.
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import time
import threading

import paramiko

from config import (
    SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD, SSH_KEY_PATH,
    FAST_LOG, LOG_MATCH_KEYWORDS, SSH_REQUIRED_FOR_PASS, REPORT_DATA,
    CASB_POPUP_WAIT_TIMEOUT,        # NEW: 3-minute timeout for popup appearance
    CASB_POPUP_DISAPPEAR_TIMEOUT,   # NEW: 3-minute timeout for auto-expiry
)
# EXPECTED_APPLICATION / ACTIVITY / BLOCKED_BY — read via config module at runtime
# (run.py sets them from apps/<app_id>/app.yaml before each app run).

try:
    from pywinauto import Desktop
    from pywinauto.application import Application
except ImportError:
    Desktop = None
    Application = None


# ------------------------------------------------------------
# FAST.LOG SSH CAPTURE
# ------------------------------------------------------------

class FastLogCapture:
    """
    Streams fast.log via SSH tail -f in a background thread.
    Call start() before sending the Teams message, stop() + validate() after.
    """
    def __init__(self):
        self.matched_lines = []
        self.all_captured  = []
        self._stop_event   = threading.Event()
        self._thread       = None
        self._ssh          = None
        self._channel      = None
        self._connected    = False
        self._error        = None

    def _connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        base = dict(hostname=SSH_HOST, port=SSH_PORT, username=SSH_USER,
                    timeout=10, look_for_keys=False, allow_agent=False)
        strategies = []
        if SSH_KEY_PATH and SSH_PASSWORD:
            strategies += [
                ("key + passphrase", {**base, "key_filename": SSH_KEY_PATH, "passphrase": SSH_PASSWORD}),
                ("key only",         {**base, "key_filename": SSH_KEY_PATH}),
                ("password only",    {**base, "password": SSH_PASSWORD}),
            ]
        elif SSH_KEY_PATH:
            strategies.append(("key only", {**base, "key_filename": SSH_KEY_PATH}))
        else:
            strategies.append(("password only", {**base, "password": SSH_PASSWORD}))

        last_error = None
        for label, kwargs in strategies:
            try:
                print(f"   [SSH] Trying: {label} ...")
                client.connect(**kwargs)
                self._ssh = client
                self._connected = True
                print(f"   [SSH] Connected to {SSH_HOST} via [{label}]")
                return
            except Exception as e:
                last_error = e
                print(f"   [SSH] {label} failed: {e}")
        self._error = str(last_error)
        self._connected = False
        print(f"   [SSH] ALL AUTH STRATEGIES FAILED: {last_error}")
        if not SSH_REQUIRED_FOR_PASS:
            print(f"   [SSH] NOTE: SSH_REQUIRED_FOR_PASS=False — test can still PASS without SSH")

    def _tail_worker(self):
        try:
            transport = self._ssh.get_transport()
            self._channel = transport.open_session()
            self._channel.exec_command(f"tail -f {FAST_LOG}")
            self._channel.settimeout(1.0)
            buffer = b""
            while not self._stop_event.is_set():
                try:
                    chunk = self._channel.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line_bytes, buffer = buffer.split(b"\n", 1)
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if line:
                            self.all_captured.append(line)
                            if self._is_match(line):
                                self.matched_lines.append(line)
                                print(f"   [SSH LOG MATCH] {line}")
                except Exception:
                    pass
        except Exception as e:
            print(f"   [SSH] tail worker error: {e}")
        finally:
            try:
                self._channel.close()
            except:
                pass

    def _is_match(self, line):
        """Match line if it contains application (ms_teams), activity (post),
        AND classification (app-activity for casb), case-insensitive."""
        low = line.lower()
        return "ms_teams" in low and "post" in low and "app-activity for casb" in low

    def start(self):
        self._connect()
        if not self._connected:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tail_worker, daemon=True)
        self._thread.start()
        print(f"   [SSH] Log capture started -> tail -f {FAST_LOG}")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._ssh:
            try:
                self._ssh.close()
            except:
                pass
        print(f"   [SSH] Stopped. {len(self.matched_lines)} match(es) in {len(self.all_captured)} line(s).")

    def validate(self):
        import re as _re
        matched = len(self.matched_lines) > 0

        # Extract unique sig IDs from matched lines (correct hits)
        sig_id_set = []
        seen_sigs = set()
        for line in self.matched_lines:
            for sid in _re.findall(r'1:(\d{7,}):\d+', line):
                if sid not in seen_sigs:
                    seen_sigs.add(sid)
                    sig_id_set.append(sid)
        multiple_sig_ids = len(sig_id_set) > 1

        # Extract false sig IDs — sig IDs from NON-matching lines
        # These are lines that fired a signature but didn't match our keywords
        false_sig_set = []
        seen_false = set()
        non_matched_lines = [l for l in self.all_captured if l not in self.matched_lines]
        for line in non_matched_lines:
            for sid in _re.findall(r'1:(\d{7,}):\d+', line):
                if sid not in seen_sigs and sid not in seen_false:
                    seen_false.add(sid)
                    false_sig_set.append(sid)

        print(f"\n   ------------------------------")
        print(f"   FAST.LOG VALIDATION")
        print(f"   ------------------------------")
        print(f"   Total lines captured : {len(self.all_captured)}")
        print(f"   Matching lines       : {len(self.matched_lines)}")
        kw_disp = getattr(self, "_keywords", None) or LOG_MATCH_KEYWORDS
        print(f"   Keywords required    : {kw_disp}")
        print(f"   Unique Sig IDs found : {sig_id_set if sig_id_set else 'None'}")
        print(f"   False Sig IDs found  : {false_sig_set if false_sig_set else 'None'}")
        if multiple_sig_ids:
            print(f"   WARNING: Multiple sig IDs hit — skipping sig validation")
        if false_sig_set:
            print(f"   WARNING: False sig ID hits detected — {false_sig_set}")
        if not self._connected:
            print(f"   Log match result     : SKIPPED (SSH unavailable)")
        else:
            print(f"   Log match result     : {'CONFIRMED' if matched else 'NOT FOUND'}")
        for i, ln in enumerate(self.matched_lines, 1):
            print(f"   Match [{i}]: {ln}")
        print(f"   ------------------------------\n")
        return {
            "ssh_connected"     : self._connected,
            "ssh_error"         : self._error,
            "total_lines"       : len(self.all_captured),
            "matched_lines"     : self.matched_lines,
            "matched_count"     : len(self.matched_lines),
            "fast_log_confirmed": matched,
            "ssh_skipped"       : not self._connected,
            "sig_ids"           : sig_id_set,
            "multiple_sig_ids"  : multiple_sig_ids,
            "false_sig_ids"     : false_sig_set,
            "all_lines"         : self.all_captured,
        }


# ------------------------------------------------------------
# VERSA CLI — clear logs
# ------------------------------------------------------------

def clear_versa_cli():
    """
    Connect to Versa CLI via SSH and clear the IDP fast.log.
    Returns True on success, False on failure.
    """
    CLI_COMMANDS = [
        "request clear log idp/fast.log",
    ]
    CMD_TIMEOUT = 30

    print(f"\n{'=' * 55}")
    print("PRE-TEST: Clearing Versa CLI logs...")
    print(f"{'=' * 55}")

    step = {
        "timestamp" : __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "connected" : False,
        "commands"  : [],
        "overall_ok": False,
        "error"     : None,
    }

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        base = dict(hostname=SSH_HOST, port=SSH_PORT, username=SSH_USER,
                    timeout=10, look_for_keys=False, allow_agent=False)
        if SSH_KEY_PATH:
            client.connect(**base, key_filename=SSH_KEY_PATH)
        else:
            client.connect(**base, password=SSH_PASSWORD)
        step["connected"] = True
        print(f"   [CLI] Connected to {SSH_HOST}")
    except Exception as e:
        step["error"] = str(e)
        print(f"   [CLI] SSH connection failed: {e}")
        print(f"   [CLI] Skipping CLI clear — continuing with test.")
        REPORT_DATA["step_cli"] = step
        return False

    try:
        shell = client.invoke_shell(width=220, height=50)
        shell.settimeout(CMD_TIMEOUT)

        def read_until_prompt(timeout=CMD_TIMEOUT):
            """
            Read shell output until prompt.
            Handles:
            - Pagination mode (--More--)
            - Config mode ([edit] or (config)%)
            - Timeout scenarios
            """
            output = ""
            deadline = time.time() + timeout
            no_data_count = 0
            
            while time.time() < deadline:
                try:
                    chunk = shell.recv(4096).decode("utf-8", errors="replace")
                    
                    # Handle no data received
                    if not chunk:
                        no_data_count += 1
                        if no_data_count > 15:
                            print(f"   [CLI] No data received, timing out...")
                            break
                        time.sleep(0.2)
                        continue
                    
                    no_data_count = 0
                    output += chunk
                    
                    # FIX #1: Handle pagination
                    if "--More--" in chunk:
                        print(f"   [CLI] Pagination detected, sending 'q'...")
                        shell.send("q")
                        time.sleep(0.3)
                        continue
                    
                    if "(END)" in chunk:
                        print(f"   [CLI] Pagination end detected, sending 'q'...")
                        shell.send("q")
                        time.sleep(0.3)
                        continue
                    
                    # FIX #2: Exit config mode (CRITICAL!)
                    last_line = output.strip().split("\n")[-1] if output.strip() else ""
                    
                    # Detect config mode: [edit] or (config)%
                    if "[edit]" in last_line:
                        print(f"   [CLI] Config mode [edit] detected, exiting...")
                        shell.send("exit\n")
                        time.sleep(0.5)
                        output = ""  # Reset output
                        continue
                    
                    if "(config)%" in last_line:
                        print(f"   [CLI] Config mode (config)% detected, exiting...")
                        shell.send("exit\n")
                        time.sleep(0.5)
                        output = ""  # Reset output
                        continue
                    
                    # FIX #3: Check for operational mode prompt
                    if ">" in last_line and "(config)" not in last_line:
                        print(f"   [CLI] Operational prompt detected")
                        break
                
                except Exception as e:
                    print(f"   [CLI] Exception: {e}")
                    time.sleep(0.2)
            
            return output

        initial = read_until_prompt(timeout=15)
        print(f"   [CLI] Shell ready. Last line: "
              f"{initial.strip().splitlines()[-1] if initial.strip() else '(empty)'}")

        shell.send("cli\n")
        cli_banner = read_until_prompt(timeout=15)
        last_line = cli_banner.strip().splitlines()[-1] if cli_banner.strip() else "(empty)"
        print(f"   [CLI] Versa CLI ready. Last line: {last_line}")

        for cmd in CLI_COMMANDS:
            cmd_record = {"cmd": cmd, "output": "", "ok": True}
            print(f"   [CLI] Sending: {cmd}")
            try:
                shell.send(cmd + "\n")
                time.sleep(3)
                if shell.recv_ready():
                    response = shell.recv(4096).decode("utf-8", errors="replace")
                    cmd_record["output"] = response.strip()
            except Exception:
                pass
            print(f"   [CLI] Sent.")
            step["commands"].append(cmd_record)

        step["overall_ok"] = True
        try:
            shell.close()
        except:
            pass
        REPORT_DATA["step_cli"] = step
        return True

    except Exception as e:
        step["error"] = str(e)
        print(f"   [CLI] Error: {e}")
        REPORT_DATA["step_cli"] = step
        return False
    finally:
        try:
            client.close()
        except:
            pass
        print(f"{'=' * 55}\n")



# ------------------------------------------------------------
# CASB POPUP SCREENSHOT
# ------------------------------------------------------------

def capture_popup_screenshot(win, script_dir: str, tag: str = ""):
    """
    Capture a screenshot of the Versa AlertWindow popup.
    Tries three methods in order:
      1. ``PrintWindow`` (win32ui + ``PW_RENDERFULLCONTENT``, then legacy flags) —
         works when the popup is not foregrounded; preferred for CASB toasts/modals.
      2. pywinauto ``capture_as_image()`` on the window handle.
      3. PIL ``ImageGrab.grab(bbox=…)`` using the window rectangle.
    Saves PNG to script_dir, returns (base64_str, filepath).
    Returns (None, None) on failure.
    """
    import os
    import base64
    import time

    if win is None:
        return None, None

    filename = f"{tag}_casb_popup_screenshot.png" if tag else "casb_popup_screenshot.png"
    filepath = os.path.join(script_dir, filename)
    img = None

    # ── Method 1: PrintWindow via win32ui (preferred — works without active desktop) ──
    try:
        import win32gui
        import win32ui
        from PIL import Image
        import ctypes

        hwnd = win.handle
        rect = win32gui.GetWindowRect(hwnd)
        w = max(rect[2] - rect[0], 1)
        h = max(rect[3] - rect[1], 1)

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap  = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bitmap)

        # PW_RENDERFULLCONTENT=2 (Win 8.1+); then 0 / PW_CLIENTONLY=1 for older builds.
        pw_flags = (
            (2, "PW_RENDERFULLCONTENT(2)"),
            (0, "PrintWindow(0)"),
            (1, "PW_CLIENTONLY(1)"),
        )
        result_flag = 0
        used_lbl = ""
        for flag, lbl in pw_flags:
            result_flag = int(
                ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), int(flag))
            )
            used_lbl = lbl
            if result_flag:
                break

        bmpinfo = bitmap.GetInfo()
        bmpstr  = bitmap.GetBitmapBits(True)
        img     = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                                   bmpstr, "raw", "BGRX", 0, 1)
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        if result_flag:
            print(f"   [POPUP SS] Method 1 (PrintWindow) succeeded via {used_lbl}")
        else:
            print(
                f"   [POPUP SS] Method 1 (PrintWindow) all flags returned 0 "
                f"(last={used_lbl}) — image may be blank; keeping for fallback chain"
            )
    except Exception as e:
        print(f"   [POPUP SS] Method 1 failed: {e}")

    # ── Method 2: pywinauto capture_as_image() ────────────────────
    if img is None:
        try:
            img = win.capture_as_image()
            print(f"   [POPUP SS] Method 2 (capture_as_image) succeeded")
        except Exception as e:
            print(f"   [POPUP SS] Method 2 failed: {e}")

    # ── Method 3: PIL ImageGrab with window bounding rect ─────────
    if img is None:
        try:
            from PIL import ImageGrab
            rect = win.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            img = ImageGrab.grab(bbox=bbox)
            print(f"   [POPUP SS] Method 3 (ImageGrab bbox) succeeded")
        except Exception as e:
            print(f"   [POPUP SS] Method 3 failed: {e}")
            return None, None

    # ── Save and encode ───────────────────────────────────────────
    try:
        img.save(filepath)
        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        print(f"   [POPUP SS] Screenshot saved: {filepath}")
        return b64, filepath
    except Exception as e:
        print(f"   [POPUP SS] Save/encode failed: {e}")
        return None, None


# ------------------------------------------------------------
# VERSA ALERTWINDOW POPUP
# ------------------------------------------------------------

def find_versa_popup():
    """Find the Versa AlertWindow on the desktop."""
    if Desktop is None:
        return None
    try:
        desktop = Desktop(backend="win32")
        for win in desktop.windows():
            try:
                if (win.window_text() == "AlertWindow" and
                        "VersaSecureAccessClient.Alerts" in win.class_name()):
                    return win
            except Exception:
                continue
    except Exception:
        pass
    return None


def extract_popup_data(win):
    """Extract application, activity, URL and full text from the popup window."""
    popup_data = {
        "window_title": "", "application": "", "activity": "",
        "url": "", "full_text": "", "raw_elements": []
    }
    try:
        popup_data["window_title"] = win.window_text()
        all_text = []
        try:
            app = Application(backend="uia").connect(handle=win.handle)
            dlg = app.window(handle=win.handle)
            for elem in dlg.descendants():
                try:
                    t = elem.window_text().strip()
                    if t:
                        all_text.append(t)
                except:
                    pass
        except:
            try:
                for child in win.children():
                    try:
                        t = child.window_text().strip()
                        if t:
                            all_text.append(t)
                    except:
                        pass
            except:
                pass

        seen, deduped = set(), []
        for t in all_text:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        all_text = deduped
        popup_data["raw_elements"] = all_text
        popup_data["full_text"]    = " | ".join(all_text)

        for text in all_text:
            t = text.lower().strip()
            if "ms_teams" in t or "msteams" in t:
                popup_data["application"] = text
            elif "instagram" in t:
                popup_data["application"] = text
            elif "trello" in t:
                popup_data["application"] = text
            elif t == "post":
                popup_data["activity"] = text
            elif t == "logout" or "logout" in t:
                popup_data["activity"] = text
            elif "teams.live.com" in t or "teams.microsoft.com" in t:
                popup_data["url"] = text

        print("\n   ------------------------------")
        print("   CASB POPUP DATA")
        print("   ------------------------------")
        print(f"   window_title : {popup_data['window_title']}")
        print(f"   application  : {popup_data['application']}")
        print(f"   activity     : {popup_data['activity']}")
        print(f"   url          : {popup_data['url']}")
        print(f"   full_text    : {popup_data['full_text']}")
        print(f"   raw_elements : {popup_data['raw_elements']}")
        print("   ------------------------------\n")
    except Exception as e:
        print(f"   Error extracting popup data: {e}")
    return popup_data


def validate_popup_data(popup_data):
    """Validate popup fields against expected values from config (read at call time so run.py can set per-app)."""
    import config as _cfg

    exp_app = _cfg.EXPECTED_APPLICATION
    exp_act = _cfg.EXPECTED_ACTIVITY
    exp_blk = _cfg.EXPECTED_BLOCKED_BY
    full_lower        = popup_data["full_text"].lower()
    application_match = exp_app.lower() in full_lower
    activity_match    = exp_act.lower() in full_lower
    ea = (exp_act or "").lower().strip()
    # Versa UI strings vs YAML (Trello logout, download/upload activities).
    if not activity_match and ea == "logout":
        activity_match = any(
            x in full_lower for x in ("logout", "log out", "sign out", "sign-out")
        )
    if not activity_match and ea == "download_file":
        activity_match = ("download_file" in full_lower) or (
            "download" in full_lower and "trello" in full_lower
        )
    if not activity_match and ea == "upload_file":
        activity_match = ("upload_file" in full_lower) or (
            "upload" in full_lower and "trello" in full_lower
        )
    by_casb           = exp_blk.lower() in full_lower
    by_other          = any(x in full_lower for x in ["atp", "ip filter", "ipfilter", "threat protection"])
    blocked_by_casb   = by_casb and not by_other
    print(f"   Validation:")
    print(f"   Application '{exp_app}' : {'MATCH' if application_match else 'NOT FOUND'}")
    print(f"   Activity    '{exp_act}'    : {'MATCH' if activity_match else 'NOT FOUND'}")
    print(f"   Blocked by CASB                      : {'CONFIRMED' if blocked_by_casb else 'NOT CONFIRMED'}")
    return {
        "application_match": application_match,
        "activity_match"   : activity_match,
        "blocked_by_casb"  : blocked_by_casb,
    }


def wait_until_popup_appears(timeout_seconds=None):
    """Poll until the classic Versa AlertWindow appears (or timeout)."""
    if timeout_seconds is None:
        timeout_seconds = CASB_POPUP_WAIT_TIMEOUT
    print(f"   Watching for Versa AlertWindow (timeout: {timeout_seconds}s)...")
    start_time = time.time()
    poll_s = 0.2
    while time.time() - start_time < timeout_seconds:
        win = find_versa_popup()
        if win:
            print("   ✓ Versa AlertWindow (CASB block page) appeared!")
            return win
        time.sleep(poll_s)
    print(f"\n   ✗ TIMEOUT: Versa AlertWindow did not appear within {timeout_seconds}s\n")
    return None


def wait_until_popup_disappears(timeout_seconds=None):
    """Poll until the AlertWindow is gone (or timeout). Returns elapsed seconds or -1."""
    if timeout_seconds is None:
        timeout_seconds = CASB_POPUP_DISAPPEAR_TIMEOUT
    print(f"   Waiting for Versa AlertWindow to AUTO-EXPIRE (timeout: {timeout_seconds}s)...")
    start_time = time.time()
    poll_s = 0.2
    while time.time() - start_time < timeout_seconds:
        if not find_versa_popup():
            elapsed = int(time.time() - start_time)
            print(f"   ✓ Versa AlertWindow auto-expired after {elapsed}s.")
            return elapsed
        time.sleep(poll_s)
    print(f"\n   ✗ TIMEOUT: Versa AlertWindow did not auto-expire within {timeout_seconds}s\n")
    return -1
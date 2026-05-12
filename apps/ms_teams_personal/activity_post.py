"""
apps/ms_teams/activity_post.py — PostMixin
All 5 MS Teams post TCs in one class:
  TC1 — _do_post           : Direct chat → send text
  TC2 — _do_meet_now_post  : Meet Now → meeting chat → send
  TC3 — _do_forward        : Hybrid API forward
  TC4 — _do_reply          : Hybrid API reply
  TC5 — _do_community_post : Community channel post with file
"""

import json
import os
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

from core.vos_info_dump import vos_dump_file_stem_from_result

_API_BASE                = "https://teams.live.com/api/chatsvc/consumer/v1"
_TC3_SOURCE_CHAT         = "AMRUTA LONI"
_TC3_FORWARD_MESSAGE     = "this is sent text for forward"
_TC3_SENDER_DISPLAY_NAME = "Casb Automation1"
_TC4_REPLY_CHAT          = "AMRUTA LONI"
_TC4_REPLY_TO_MSG        = "this is sent text for forward"
_TC5_COMMUNITY_NAME      = "School"
_TC5_SUBJECT_PREFIX      = "CASB AUTOMATION SUBJECT1"
_TC5_FILE_PATH           = (
    r"C:\\Users\\admin\\Documents"
    r"\\casb automation files and folders dont edit delete"
    r"\\casb automation word file dont delete.docx"
)


class PostMixin:
    """All MS Teams post-category TCs (TC1-TC5)."""

    # ================================================================
    # TC1 — Direct chat → send text
    # ================================================================

    def _do_post(self, page, result, recipient, message, **kwargs):
        print(f"\n   [TC1] Sending message to: {recipient}")

        clicked = False
        for strategy in [
            lambda: page.locator(f"xpath=//span[normalize-space(text())='{recipient}']").first.click(timeout=5000),
            lambda: page.get_by_text(recipient, exact=True).first.click(timeout=5000),
            lambda: page.get_by_text(recipient).first.click(timeout=5000),
        ]:
            try:
                strategy(); clicked = True; break
            except Exception:
                continue

        if not clicked:
            result["fail_reason"].append(f"Could not open chat with {recipient}"); return False

        page.wait_for_timeout(3000)

        typed = False
        for sel in [
            lambda: page.get_by_placeholder("Type a message"),
            lambda: page.locator("div[contenteditable='true']").last,
        ]:
            try:
                box = sel(); box.wait_for(state="visible", timeout=5000)
                box.click(); page.wait_for_timeout(500); box.type(message, delay=80); typed = True; break
            except Exception:
                continue

        if not typed:
            result["fail_reason"].append("Could not type message in chat"); return False

        vsmd_prep, har = self._before_send(page, vos_dump_file_stem_from_result(result))
        result["_har"] = har

        sent = False
        try:
            page.get_by_role("button", name="Send").click(timeout=5000); sent = True
        except Exception:
            page.keyboard.press("Control+Enter"); sent = True

        page.wait_for_timeout(3000)
        self._after_send(page, result, vsmd_prep, har, vos_dump_file_stem_from_result(result), None)

        ss, _ = self._screenshot(page, "TC1_step1_sent")
        self._add_step(result, "TC1-b", f"Message Sent to {recipient}",
                       "pass" if sent else "fail",
                       [f"Recipient : {recipient}", f"Message   : '{message}'",
                        f"Result    : {'Sent ✓' if sent else 'FAILED ✗'}"], ss)

        if not sent:
            result["fail_reason"].append("Could not send message"); return False

        self._check_delivery_generic(page, result, message, "TC1-c", tag="TC1")
        return True

    # ================================================================
    # TC2 — Meet Now → meeting chat → send
    # ================================================================

    def _do_meet_now_post(self, page, result, message, **kwargs):
        print(f"\n   [TC2] Meet Now post: '{message}'")

        clicked = False
        for sel in [
            "button[aria-label='Meet Now']", "button[aria-label='Meet now']",
            "xpath=//button[@aria-label='Meet Now']", "xpath=//button[@aria-label='Meet now']",
            "xpath=//button[.//span[text()='Meet now']]", "[data-tid='meet-now-button']",
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=4000)
                page.locator(sel).first.click(); clicked = True; break
            except Exception:
                continue

        page.wait_for_timeout(2000)
        self._dismiss_windows_firewall()
        ss1, _ = self._screenshot(page, "TC2_step1_meet_now_icon")
        self._add_step(result, "TC2-a", "Clicked Meet Now Icon", "pass" if clicked else "fail",
                       ["Clicked Meet Now icon near Chat button"], ss1)
        if not clicked:
            result["fail_reason"].append("Could not find Meet Now icon"); return False

        started = False
        for sel in [
            "button:has-text('Start meeting')", "xpath=//button[normalize-space(text())='Start meeting']",
            "[data-tid='start-meeting-button']", "text=Start meeting",
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=8000)
                page.locator(sel).first.click(); started = True; break
            except Exception:
                continue

        page.wait_for_timeout(5000)
        ss2, _ = self._screenshot(page, "TC2_step2_start_meeting")
        self._add_step(result, "TC2-b", "Clicked Start Meeting", "pass" if started else "fail",
                       ["Clicked Start meeting to launch meeting window"], ss2)
        if not started:
            result["fail_reason"].append("Could not find Start meeting button"); return False

        self._dismiss_meeting_popups(page)

        chat_clicked = False
        for sel in [
            "xpath=(//button[@aria-label='Chat'])[last()]",
            "xpath=(//button[.//span[text()='Chat']])[last()]",
            "xpath=//div[contains(@class,'toolbar')]//button[@aria-label='Chat']",
        ]:
            try:
                btn = page.locator(sel).last; btn.wait_for(state="visible", timeout=8000)
                btn.click(); chat_clicked = True; break
            except Exception:
                continue

        page.wait_for_timeout(2000)
        self._add_step(result, "TC2-c", "Clicked Chat Tab in Meeting",
                       "pass" if chat_clicked else "fail", ["Clicked Chat tab in meeting toolbar"])
        if not chat_clicked:
            result["fail_reason"].append("Could not find Chat tab in meeting"); return False

        page.wait_for_timeout(3000)
        typed = False
        for sel in [
            "xpath=//div[contains(@class,'meeting-chat')]//div[@contenteditable='true']",
            "xpath=//aside//div[@contenteditable='true']",
            "xpath=(//div[@contenteditable='true'])[last()]",
        ]:
            try:
                box = page.locator(sel).last; box.wait_for(state="visible", timeout=5000)
                box.click(); page.wait_for_timeout(500); box.type(message, delay=80); typed = True; break
            except Exception:
                continue

        if not typed:
            result["fail_reason"].append("Could not type in meeting chat"); return False

        vsmd_prep, har = self._before_send(page, vos_dump_file_stem_from_result(result))
        result["_har"] = har

        sent = False
        for send_sel in ["button[aria-label='Send']", "xpath=//button[@aria-label='Send']"]:
            try:
                page.locator(send_sel).first.click(timeout=3000); sent = True; break
            except Exception:
                continue
        if not sent:
            page.keyboard.press("Enter"); sent = True

        page.wait_for_timeout(3000)
        self._after_send(page, result, vsmd_prep, har, vos_dump_file_stem_from_result(result), None)

        ss3, _ = self._screenshot(page, "TC2_step3_message_sent")
        self._add_step(result, "TC2-d", "Message Posted in Meeting Chat",
                       "pass" if sent else "fail",
                       [f"Message : '{message}'", f"Result  : {'Sent ✓' if sent else 'Failed ✗'}"], ss3)
        if not sent:
            result["fail_reason"].append("Could not send message in meeting chat"); return False

        delivered = False
        is_pending_ui = False
        has_ts = False
        has_sent_check = False
        detail = "Delivery status inconclusive — assuming CASB blocked"
        try:
            page.wait_for_timeout(3000)
            bubble = page.evaluate(
                """
                (msg) => {
                    function analyzeMyMessage(row, bubbleEl) {
                        const scope = row || bubbleEl;
                        if (!scope) return null;
                        const html = (scope.outerHTML || '').toLowerCase();
                        const text = (scope.innerText || '').toLowerCase();

                        let pending = text.includes('sending') || html.includes('retrying');

                        let sentCheck = false;
                        const icons = scope.querySelectorAll('i[data-icon-name], svg[data-icon-name]');
                        for (const node of icons) {
                            const n = (node.getAttribute('data-icon-name') || '').toLowerCase();
                            if (!n) continue;
                            if (n.includes('check') && (n.includes('circle') || n.includes('skype')))
                                sentCheck = true;
                            if (n.includes('circlering') || n.includes('statuscirclering')
                                || n.includes('statuscircleouter'))
                                pending = true;
                        }

                        let ts = false;
                        if (row && row.querySelector('time[datetime]')) ts = true;
                        else if (bubbleEl && bubbleEl.querySelector('time[datetime]')) ts = true;

                        if (pending && sentCheck) pending = false;

                        return {
                            pending,
                            hasTimestamp: ts,
                            hasSentCheck: sentCheck,
                        };
                    }

                    /* Consumer chat: [data-tid="chat-pane-message"] + [data-message-content] */
                    for (const el of document.querySelectorAll('[data-tid="chat-pane-message"]')) {
                        const c = el.querySelector('[data-message-content]');
                        if (!c || !c.innerText.includes(msg)) continue;
                        const row = el.closest('[class*="ChatMyMessage"]')
                            || el.closest('[class*="chatMyMessage"]');
                        const r = analyzeMyMessage(row, el);
                        if (r) return r;
                    }

                    /* Meeting / PWA: captures show [data-testid="message-wrapper"]; body in role=heading */
                    for (const wrap of document.querySelectorAll('[data-testid="message-wrapper"]')) {
                        if (!wrap.innerText.includes(msg)) continue;
                        const row = wrap.querySelector('[class*="ChatMyMessage"]')
                            || wrap.querySelector('[class*="chatMyMessage"]');
                        const r = analyzeMyMessage(row || wrap, wrap);
                        if (r) return r;
                    }

                    return null;
                }
                """,
                message,
            )
            if bubble is None:
                detail = "Message bubble not found — CASB blocked ✓"
                result["message_not_delivered"] = True
            else:
                is_pending_ui = bool(bubble.get("pending"))
                has_ts = bool(bubble.get("hasTimestamp"))
                has_sent_check = bool(bubble.get("hasSentCheck"))
                if is_pending_ui:
                    detail = "Sending / hollow status or no sent check → not delivered — CASB blocked ✓"
                    result["message_not_delivered"] = True
                elif has_sent_check or (has_ts and not is_pending_ui):
                    delivered = True
                    detail = "Sent check or per-message timestamp → DELIVERED — CASB did NOT block ✗"
                    result["message_not_delivered"] = False
                    result["fail_reason"].append(
                        "Meeting chat message was delivered — CASB did not block"
                    )
                else:
                    detail = "No sent check and no per-message timestamp — treating as blocked ✓"
                    result["message_not_delivered"] = True
        except Exception as e:
            detail = f"Delivery check error: {e} — assuming blocked"
            result["message_not_delivered"] = True

        ss4, _ = self._screenshot(page, "TC2_step4_delivery_check")
        self._add_step(
            result,
            "TC2-e",
            "Message Delivery Check (Meeting Chat)",
            "pass" if result["message_not_delivered"] else "fail",
            [
                detail,
                f"pending/sending UI: {is_pending_ui}",
                f"has per-msg time: {has_ts}",
                f"sent check icon: {has_sent_check}",
            ],
            ss4,
        )
        return True

    def _dismiss_meeting_popups(self, page):
        self._dismiss_windows_firewall()
        for sel in ["button:has-text('Block')", "xpath=//button[normalize-space(text())='Block']"]:
            try: page.locator(sel).first.click(timeout=3000); break
            except Exception: continue
        page.wait_for_timeout(1000)
        for sel in ["xpath=//div[contains(text(),'No Microphone')]/..//button"]:
            try: page.locator(sel).first.click(timeout=2000); page.wait_for_timeout(500); break
            except Exception: continue
        page.wait_for_timeout(1000)
        for sel in ["xpath=//div[@role='dialog']//button[@aria-label='Close']",
                    "xpath=(//button[@aria-label='Close'])[1]"]:
            try: page.locator(sel).first.click(timeout=3000); break
            except Exception:
                try: page.keyboard.press("Escape")
                except Exception: pass
        page.wait_for_timeout(2000)

    # ================================================================
    # TC3 — Hybrid API forward
    # ================================================================

    def _do_forward(self, page, result, recipient, message, **kwargs):
        print(f"\n   [TC3] Hybrid forward → to: {recipient}")
        time.sleep(3)

        forward_message  = _TC3_FORWARD_MESSAGE or message
        source_chat_name = _TC3_SOURCE_CHAT

        source_clicked = self._click_chat_by_name(page, source_chat_name)
        page.wait_for_timeout(3000)
        ss_a, _ = self._screenshot(page, "TC3_step1_source_chat")
        self._add_step(result, "TC3-a", f"Opened source chat: {source_chat_name}",
                       "pass" if source_clicked else "fail",
                       [f"Source chat : {source_chat_name}", f"Clicked     : {source_clicked}"], ss_a)
        if not source_clicked:
            result["fail_reason"].append(f"Could not open source chat: {source_chat_name}"); return False

        source_thread_id = self._extract_thread_id(page, source_chat_name)
        if not source_thread_id:
            source_thread_id = self._find_thread_id_via_api(page, source_chat_name)
        self._add_step(result, "TC3-b", "Extracted source thread ID",
                       "pass" if source_thread_id else "warn",
                       [f"Thread ID : {source_thread_id or 'not found'}"])
        if not source_thread_id:
            result["fail_reason"].append("Could not extract source thread ID"); return False

        sender_mri, sender_name = self._get_sender_identity(page)
        sender_name = sender_name or _TC3_SENDER_DISPLAY_NAME
        self._add_step(result, "TC3-c", "Got sender identity",
                       "pass" if sender_mri else "warn",
                       [f"MRI : {sender_mri or 'not found'}", f"Name: {sender_name}"])

        message_id, msg_detail = self._get_message_id_to_forward(page, source_thread_id, forward_message)
        self._add_step(result, "TC3-d", "Located message to forward",
                       "pass" if message_id else "fail",
                       [f"Message ID : {message_id or 'not found'}", f"Detail     : {msg_detail}"])
        if not message_id:
            result["fail_reason"].append("Could not find a message ID to forward"); return False

        target_thread_id = None
        if source_chat_name.lower().strip() != recipient.lower().strip():
            if self._click_chat_by_name(page, recipient):
                page.wait_for_timeout(2500)
                target_thread_id = self._extract_thread_id(page, recipient)
        if not target_thread_id:
            target_thread_id = self._find_thread_id_via_api(page, recipient)
        self._add_step(result, "TC3-e", f"Got target thread ID for {recipient}",
                       "pass" if target_thread_id else "fail",
                       [f"Thread ID : {target_thread_id or 'not found'}"])
        if not target_thread_id:
            result["fail_reason"].append(f"Could not find target thread ID for: {recipient}"); return False

        if source_chat_name.lower().strip() != recipient.lower().strip():
            self._click_chat_by_name(page, source_chat_name)
            page.wait_for_timeout(2000)

        vsmd_prep, har = self._before_send(page, vos_dump_file_stem_from_result(result))
        result["_har"] = har

        api_status, api_error = self._call_forward_api(
            page=page, source_thread_id=source_thread_id, target_thread_id=target_thread_id,
            message_id=message_id, sender_mri=sender_mri or "", sender_name=sender_name,
        )
        sent = api_status in (200, 201, 202, 403, "CASB_BLOCKED")
        page.wait_for_timeout(3000)
        self._after_send(page, result, vsmd_prep, har, vos_dump_file_stem_from_result(result), None)

        ss_f, _ = self._screenshot(page, "TC3_step2_api_called")
        self._add_step(result, "TC3-f", "Forward API called",
                       "pass" if sent else "fail",
                       [f"HTTP status : {api_status}", f"Error       : {api_error or 'none'}",
                        f"Result      : {'Sent ✓' if sent else 'Failed ✗'}"], ss_f)
        if not sent:
            result["fail_reason"].append(f"Forward API failed — HTTP {api_status}: {api_error}"); return False

        if api_status == "CASB_BLOCKED":
            result["message_not_delivered"] = True
            self._add_step(result, "TC3-g", "Delivery", "pass", ["CASB ECONNRESET — message never sent ✓"])
        elif api_status in (200, 201, 202):
            result["message_not_delivered"] = False
            result["fail_reason"].append(f"Forward returned HTTP {api_status} — CASB did not block")
            self._add_step(result, "TC3-g", "Delivery", "fail", [f"HTTP {api_status} — CASB did NOT block ✗"])
        elif api_status == 403:
            result["message_not_delivered"] = True
            self._add_step(result, "TC3-g", "Delivery", "pass", ["HTTP 403 — CASB blocked at server ✓"])
        else:
            page.wait_for_timeout(2000); self._click_chat_by_name(page, recipient); page.wait_for_timeout(2000)
            self._check_delivery_generic(page, result, "Forwarded a message", "TC3-g", tag="TC3")
        return True

    def _get_message_id_to_forward(self, page, thread_id: str, message_text: str) -> tuple:
        try:
            url  = f"{_API_BASE}/users/ME/conversations/{quote(thread_id, safe='')}/messages?startTime=0&pageSize=50&view=msnp24Equivalent"
            resp = page.request.get(url, headers=self._api_headers(page))
            if not resp.ok:
                return None, f"Messages API returned {resp.status}"
            messages = resp.json().get("messages", [])
            if not messages:
                return None, "No messages returned"
            if message_text:
                for msg in reversed(messages):
                    if message_text in (msg.get("content") or ""):
                        mid = str(msg.get("id") or msg.get("sequenceId") or "")
                        if mid: return mid, f"Matched text '{message_text[:40]}'"
            for msg in reversed(messages):
                t = (msg.get("type") or msg.get("messagetype") or "").lower()
                if "message" in t and "event" not in t:
                    mid = str(msg.get("id") or msg.get("sequenceId") or "")
                    if mid: return mid, "Latest non-system message"
            return None, "No usable message ID found"
        except Exception as e:
            return None, f"API error: {e}"

    def _call_forward_api(self, page, source_thread_id, target_thread_id, message_id, sender_mri, sender_name):
        try:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            cmi     = str(random.randint(10**18, 10**19 - 1))
            api_url = f"{_API_BASE}/users/ME/conversations/{quote(source_thread_id, safe='')}/messages/forward"
            body = {
                "targetThreadIds": [target_thread_id], "messageIds": [str(message_id)],
                "additionalMessage": {
                    "id": "-1", "type": "Message", "conversationid": target_thread_id,
                    "conversationLink": f"{_API_BASE}/users/ME/conversations/{target_thread_id}",
                    "from": sender_mri, "fromUserId": sender_mri, "composetime": now_iso,
                    "originalarrivaltime": now_iso, "content": "", "messagetype": "RichText/Html",
                    "contenttype": "Text", "imdisplayname": sender_name, "clientmessageid": cmi,
                    "callId": "", "state": 0, "version": "0", "amsreferences": [],
                    "properties": {"importance": "", "subject": "", "title": "", "cards": "[]",
                                   "links": "[]", "mentions": "[]", "onbehalfof": None,
                                   "policyViolation": None, "formatVariant": "TEAMS"},
                    "crossPostChannels": [],
                },
                "templateId": "basic_forward_message_template",
            }
            resp   = page.request.post(api_url, headers=self._api_headers(page, {"Content-Type": "application/json"}), data=json.dumps(body))
            status = resp.status
            return (status, None) if (resp.ok or status == 403) else (status, f"HTTP {status}")
        except Exception as e:
            if any(x in str(e) for x in ["ECONNRESET", "ECONNREFUSED", "Connection reset", "ERR_CONNECTION_RESET"]):
                return "CASB_BLOCKED", None
            return None, str(e)

    # ================================================================
    # TC4 — Hybrid API reply
    # ================================================================

    def _do_reply(self, page, result, recipient, message, **kwargs):
        ts         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"REPLYING {_TC4_REPLY_CHAT} VIA AUTOMATION ({ts})"
        target_msg = _TC4_REPLY_TO_MSG or message
        print(f"\n   [TC4] Hybrid reply to: {_TC4_REPLY_CHAT}")
        time.sleep(3)

        chat_opened = self._open_chat_via_search(page, _TC4_REPLY_CHAT)
        page.wait_for_timeout(3000)
        ss_a, _ = self._screenshot(page, "TC4_step1_chat")
        self._add_step(result, "TC4-a", f"Opened chat: {_TC4_REPLY_CHAT}",
                       "pass" if chat_opened else "fail", [], ss_a)
        if not chat_opened:
            result["fail_reason"].append(f"Could not open chat: {_TC4_REPLY_CHAT}"); return False

        thread_id = self._extract_thread_id(page, _TC4_REPLY_CHAT)
        if not thread_id:
            thread_id = self._find_thread_id_via_api(page, _TC4_REPLY_CHAT)
        self._add_step(result, "TC4-b", "Thread ID", "pass" if thread_id else "warn",
                       [f"ID: {thread_id or 'not found'}"])
        if not thread_id:
            result["fail_reason"].append("No thread ID"); return False

        msg_id, msg_mri, msg_name, msg_preview, _ = self._get_message_to_reply(page, thread_id, target_msg)
        self._add_step(result, "TC4-c", "Message located", "pass" if msg_id else "fail",
                       [f"ID: {msg_id or 'not found'}"])
        if not msg_id:
            result["fail_reason"].append("No message ID"); return False

        self._hover_message_and_click_reply(page, target_msg)
        vsmd_prep, har = self._before_send(page, vos_dump_file_stem_from_result(result))
        result["_har"] = har

        api_status, api_error = self._call_reply_api(
            page=page, thread_id=thread_id, quoted_msg_id=msg_id,
            quoted_sender_mri=msg_mri or "", quoted_sender_name=msg_name or _TC4_REPLY_CHAT,
            quoted_preview=msg_preview or target_msg or "", reply_text=reply_text,
        )
        sent = api_status in (200, 201, 202, 403, "CASB_BLOCKED")
        page.wait_for_timeout(3000)
        self._after_send(page, result, vsmd_prep, har, vos_dump_file_stem_from_result(result), None)
        ss_c, _ = self._screenshot(page, "TC4_step3_api")
        self._add_step(result, "TC4-e", "Reply API", "pass" if sent else "fail",
                       [f"HTTP: {api_status}", f"Text: {reply_text[:50]}"], ss_c)
        if not sent:
            result["fail_reason"].append(f"Reply API failed — {api_status}: {api_error}"); return False

        if api_status == "CASB_BLOCKED":
            result["message_not_delivered"] = True
            self._add_step(result, "TC4-f", "Delivery", "pass", ["CASB block CONFIRMED ✓"])
        elif api_status in (200, 201, 202):
            result["message_not_delivered"] = False
            result["fail_reason"].append("Reply delivered — CASB did not block")
            self._add_step(result, "TC4-f", "Delivery", "fail", ["CASB did NOT block ✗"])
        elif api_status == 403:
            result["message_not_delivered"] = True
            self._add_step(result, "TC4-f", "Delivery", "pass", ["HTTP 403 — CASB blocked ✓"])
        else:
            self._check_delivery_generic(page, result, reply_text, "TC4-f", tag="TC4")
        return True

    def _get_message_to_reply(self, page, thread_id, message_text):
        try:
            url  = f"{_API_BASE}/users/ME/conversations/{quote(thread_id, safe='')}/messages?startTime=0&pageSize=50&view=msnp24Equivalent"
            resp = page.request.get(url, headers=self._api_headers(page))
            if not resp.ok: return None, None, None, None, f"API {resp.status}"
            messages = resp.json().get("messages", [])
            if not messages: return None, None, None, None, "No messages"
            target = None
            if message_text:
                for msg in reversed(messages):
                    c     = msg.get("content", "") or ""
                    plain = re.sub(r'<[^>]+>', '', c)
                    if message_text.lower() in plain.lower() or message_text.lower() in c.lower():
                        target = msg; break
            if not target:
                for msg in reversed(messages):
                    t = (msg.get("type") or msg.get("messagetype") or "").lower()
                    if "message" in t and "event" not in t and "control" not in t:
                        target = msg; break
            if not target: return None, None, None, None, "No suitable message"
            mid     = str(target.get("id") or target.get("sequenceId") or "")
            s_mri   = target.get("from") or target.get("fromUserId") or ""
            s_name  = target.get("imdisplayname") or ""
            preview = re.sub(r'<[^>]+>', '', target.get("content", "") or "").strip()[:100]
            return mid, s_mri, s_name, preview, "Matched"
        except Exception as e:
            return None, None, None, None, f"Error: {e}"

    def _call_reply_api(self, page, thread_id, quoted_msg_id, quoted_sender_mri,
                        quoted_sender_name, quoted_preview, reply_text):
        try:
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            cmi  = str(random.randint(10**18, 10**19 - 1))
            url  = f"{_API_BASE}/users/ME/conversations/{quote(thread_id, safe='')}/messages"
            mri, name = self._get_sender_identity(page)
            name = name or _TC3_SENDER_DISPLAY_NAME
            sp   = quoted_preview.replace("<", "&lt;").replace(">", "&gt;")
            sr   = reply_text.replace("<", "&lt;").replace(">", "&gt;")
            cb   = (f'<blockquote itemscope itemtype="http://schema.skype.com/Reply" itemid="{quoted_msg_id}">'
                    f'<strong itemprop="mri" itemid="{quoted_sender_mri}">{quoted_sender_name}</strong>'
                    f'<span itemprop="time" itemid="{quoted_msg_id}"></span>'
                    f'<p itemprop="preview">{sp}</p></blockquote><p>{sr}</p>')
            qtd  = json.dumps([{"messageId": quoted_msg_id, "sender": quoted_sender_mri,
                                "time": int(quoted_msg_id) if quoted_msg_id.isdigit() else 0}])
            body = {"type": "Message", "conversationid": thread_id,
                    "conversationLink": f"{_API_BASE}/users/ME/conversations/{thread_id}",
                    "from": mri or "", "fromUserId": mri or "", "composetime": now,
                    "originalarrivaltime": now, "content": cb, "messagetype": "RichText/Html",
                    "contenttype": "Text", "imdisplayname": name, "clientmessageid": cmi,
                    "callId": "", "state": 0, "version": "0", "amsreferences": [],
                    "properties": {"importance": "", "subject": "", "title": "", "cards": "[]",
                                   "links": "[]", "mentions": "[]", "onbehalfof": None,
                                   "files": "[]", "qtdMsgs": qtd, "policyViolation": None,
                                   "formatVariant": "TEAMS"},
                    "crossPostChannels": []}
            resp   = page.request.post(url, headers=self._api_headers(page, {"Content-Type": "application/json"}), data=json.dumps(body))
            status = resp.status
            return (status, None) if (resp.ok or status == 403) else (status, f"HTTP {status}")
        except Exception as e:
            if any(x in str(e) for x in ["ECONNRESET", "ECONNREFUSED", "Connection reset", "ERR_CONNECTION_RESET"]):
                return "CASB_BLOCKED", None
            return None, str(e)

    def _hover_message_and_click_reply(self, page, target_msg: str) -> bool:
        hovered = False
        for msg_sel in [f"xpath=//p[contains(text(),'{target_msg}')]", f"text={target_msg}"]:
            try:
                el = page.locator(msg_sel).last; el.wait_for(state="visible", timeout=5000)
                el.scroll_into_view_if_needed(); el.hover(); page.wait_for_timeout(800); hovered = True; break
            except Exception:
                continue
        if not hovered: return False
        for r in ["[data-tid='message-actions-quoted-reply']", "button[aria-label='Reply']"]:
            try:
                btn = page.locator(r).first; btn.wait_for(state="visible", timeout=3000)
                btn.click(); page.wait_for_timeout(500); return True
            except Exception:
                continue
        return False

    # ================================================================
    # TC5 — Community channel post with subject + file
    # ================================================================

    def _do_community_post(self, page, result, recipient, message, **kwargs):
        ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"{_TC5_SUBJECT_PREFIX} ({ts})"
        print(f"\n   [TC5] Community post: {subject}")
        time.sleep(3)

        ok = self._click_communities_tab(page); page.wait_for_timeout(2000)
        ss, _ = self._screenshot(page, "TC5_step1")
        self._add_step(result, "TC5-a", "Communities tab", "pass" if ok else "fail", [], ss)
        if not ok: result["fail_reason"].append("Communities tab failed"); return False

        ok = self._search_community(page, _TC5_COMMUNITY_NAME); page.wait_for_timeout(2000)
        ss, _ = self._screenshot(page, "TC5_step2")
        self._add_step(result, "TC5-b", f"Search: {_TC5_COMMUNITY_NAME}", "pass" if ok else "fail", [], ss)
        if not ok: result["fail_reason"].append("Search failed"); return False

        self._click_communities_filter_tab(page); page.wait_for_timeout(2000)

        ok = self._click_community_result(page, _TC5_COMMUNITY_NAME); page.wait_for_timeout(3000)
        ss, _ = self._screenshot(page, "TC5_step4")
        self._add_step(result, "TC5-c", f"Community: {_TC5_COMMUNITY_NAME}", "pass" if ok else "fail", [], ss)
        if not ok: result["fail_reason"].append("Community click failed"); return False

        ok = self._click_posts_tab(page); page.wait_for_timeout(2000)
        ss, _ = self._screenshot(page, "TC5_step5")
        self._add_step(result, "TC5-d", "Posts tab", "pass" if ok else "fail", [], ss)
        if not ok: result["fail_reason"].append("Posts tab failed"); return False

        thread_id = self._extract_thread_id(page, _TC5_COMMUNITY_NAME)
        if not thread_id:
            thread_id = self._find_thread_id_via_api(page, _TC5_COMMUNITY_NAME)
        self._add_step(result, "TC5-e", "Thread ID", "pass" if thread_id else "warn",
                       [f"ID: {thread_id or 'not yet'}"])

        ok = self._click_post_in_channel(page)
        if not ok:
            draft_discarded = self._discard_draft_if_present(page, result)
            ss, _ = self._screenshot(page, "TC5_step6_draft_check")
            self._add_step(result, "TC5-f0", "Stale draft discarded",
                           "pass" if draft_discarded else "warn",
                           [f"Draft discarded: {draft_discarded}"], ss)
            page.wait_for_timeout(1500)
            ok = self._click_post_in_channel(page)

        page.wait_for_timeout(2000)
        ss, _ = self._screenshot(page, "TC5_step7")
        self._add_step(result, "TC5-f", "Post in channel", "pass" if ok else "fail", [], ss)
        if not ok: result["fail_reason"].append("Post in channel failed"); return False

        ok = self._fill_post_subject(page, subject)
        ss, _ = self._screenshot(page, "TC5_step8")
        self._add_step(result, "TC5-g", "Subject", "pass" if ok else "fail", [f"Subject: {subject}"], ss)
        if not ok: result["fail_reason"].append("Subject fill failed"); return False

        file_meta = {}
        def _on_resp(resp):
            if "graph.microsoft.com" in resp.url and "drive" in resp.url:
                try:
                    d = resp.json()
                    if d.get("id") and d.get("name"): file_meta["graph_response"] = d
                except Exception: pass
        page.on("response", _on_resp)
        file_ok, upload_ok = self._attach_file_to_post(page, _TC5_FILE_PATH)
        page.wait_for_timeout(3000)
        try: page.remove_listener("response", _on_resp)
        except Exception: pass
        ss, _ = self._screenshot(page, "TC5_step9")
        self._add_step(result, "TC5-h", "File attached", "pass" if file_ok else "warn",
                       [f"File: {os.path.basename(_TC5_FILE_PATH)}",
                        f"Uploaded: {'Yes' if upload_ok else 'Pending'}"], ss)

        if not thread_id:
            thread_id = self._extract_thread_id(page, _TC5_COMMUNITY_NAME)
        if not thread_id:
            thread_id = self._find_thread_id_via_api(page, _TC5_COMMUNITY_NAME)
        if not thread_id: result["fail_reason"].append("No thread ID"); return False

        vsmd_prep, har = self._before_send(page, vos_dump_file_stem_from_result(result))
        result["_har"] = har
        graph_data = file_meta.get("graph_response", {})
        files_json = self._build_file_metadata(graph_data, _TC5_FILE_PATH)

        api_status, api_error = self._call_community_post_api(
            page=page, thread_id=thread_id, subject=subject, files_json=files_json)
        sent = api_status in (200, 201, 202, 403, "CASB_BLOCKED")
        page.wait_for_timeout(3000)
        self._after_send(page, result, vsmd_prep, har, vos_dump_file_stem_from_result(result), None)
        ss, _ = self._screenshot(page, "TC5_step12")
        self._add_step(result, "TC5-i", "Community post API", "pass" if sent else "fail",
                       [f"HTTP: {api_status}", f"Subject: {subject}"], ss)
        if not sent: result["fail_reason"].append(f"Post API failed — {api_status}: {api_error}"); return False

        if api_status == "CASB_BLOCKED":
            result["message_not_delivered"] = True
            self._add_step(result, "TC5-j", "Delivery", "pass", ["CASB block CONFIRMED ✓"])
        elif api_status in (200, 201, 202):
            delivered = self._check_community_post_delivery(page, thread_id, subject)
            result["message_not_delivered"] = not delivered
            if delivered:
                result["fail_reason"].append("Post visible — CASB did NOT block ✗")
                self._add_step(result, "TC5-j", "Delivery", "fail", ["CASB did NOT block ✗"])
            else:
                self._add_step(result, "TC5-j", "Delivery", "pass", ["Post not visible — likely blocked ✓"])
        elif api_status == 403:
            result["message_not_delivered"] = True
            self._add_step(result, "TC5-j", "Delivery", "pass", ["HTTP 403 — CASB blocked ✓"])
        else:
            result["message_not_delivered"] = True
            self._add_step(result, "TC5-j", "Delivery", "pass", [f"HTTP {api_status}"])
        return True

    # ── TC5 helpers ────────────────────────────────────────────────

    def _discard_draft_if_present(self, page, result) -> bool:
        draft_visible = False
        for sel in ["text=Continue your draft",
                    "xpath=//*[contains(normalize-space(text()),'Continue your draft')]"]:
            try: page.locator(sel).first.wait_for(state="visible", timeout=3000); draft_visible = True; break
            except Exception: continue
        if not draft_visible: return False
        for sel in ["[data-tid='discard-new-draft-message']", "button[aria-label='Discard']",
                    "button[aria-label='Delete draft']",
                    "xpath=//*[contains(normalize-space(text()),'Continue your draft')]/ancestor::div[1]//button[last()]"]:
            try:
                btn = page.locator(sel).first; btn.wait_for(state="visible", timeout=3000)
                btn.click(); page.wait_for_timeout(1000); return True
            except Exception: continue
        try: page.keyboard.press("Escape"); page.wait_for_timeout(500); return True
        except Exception: pass
        return False

    def _click_communities_tab(self, page) -> bool:
        for sel in ["button[aria-label='Communities']", "text=Communities"]:
            try: el=page.locator(sel).first; el.wait_for(state="visible",timeout=4000); el.click(); return True
            except Exception: continue
        return False

    def _search_community(self, page, name: str) -> bool:
        for sel in ["[data-tid='AUTOSUGGEST_INPUT']", "#ms-searchux-input"]:
            try:
                box=page.locator(sel).first; box.wait_for(state="visible",timeout=5000)
                box.click(); page.wait_for_timeout(300); box.fill(""); box.type(name,delay=80)
                page.wait_for_timeout(1500); page.keyboard.press("Enter"); page.wait_for_timeout(2000); return True
            except Exception: continue
        return False

    def _click_communities_filter_tab(self, page) -> bool:
        for sel in ["xpath=//div[@role='tablist']//span[normalize-space(text())='Communities']",
                    "[role='tab']:has-text('Communities')"]:
            try: el=page.locator(sel).first; el.wait_for(state="visible",timeout=4000); el.click(); page.wait_for_timeout(1500); return True
            except Exception: continue
        return False

    def _click_community_result(self, page, name: str) -> bool:
        for sel in [f"[data-tid='highlighted']:has-text('{name}')",
                    f"xpath=//span[normalize-space(text())='{name}']"]:
            try: el=page.locator(sel).first; el.wait_for(state="visible",timeout=5000); el.click(); page.wait_for_timeout(3000); return True
            except Exception: continue
        return False

    def _click_posts_tab(self, page) -> bool:
        for sel in ["[data-tid='tab-item-posts']", "button[value='posts']", "text=Posts"]:
            try: el=page.locator(sel).first; el.wait_for(state="visible",timeout=5000); el.click(); page.wait_for_timeout(1500); return True
            except Exception: continue
        return False

    def _click_post_in_channel(self, page) -> bool:
        for sel in ["button:has-text('Post in channel')",
                    "xpath=//button[.//span[normalize-space(text())='Post in channel']]",
                    "text=Post in channel"]:
            try: el=page.locator(sel).first; el.wait_for(state="visible",timeout=5000); el.click(); page.wait_for_timeout(1500); return True
            except Exception: continue
        return False

    def _fill_post_subject(self, page, subject: str) -> bool:
        page.wait_for_timeout(2000)
        for sel in ["[data-tid='post-compose-subject-editor']", "[aria-label='Add a subject']",
                    "input[placeholder='Add a subject']",
                    "xpath=//div[@role='textbox'][@aria-label='Add a subject']"]:
            try:
                inp = page.locator(sel).first; inp.wait_for(state="visible", timeout=5000)
                inp.click(); page.wait_for_timeout(300)
                try: inp.fill(subject)
                except Exception: inp.type(subject, delay=50)
                page.wait_for_timeout(300); return True
            except Exception: continue
        return False

    def _attach_file_to_post(self, page, file_path: str) -> tuple:
        attach_clicked = False
        for sel in ["[data-tid='post-compose-layout'] button[aria-label*='ttach']",
                    "[data-tid='post-compose-layout'] button[aria-label*='ile']"]:
            try:
                el=page.locator(sel).first; el.wait_for(state="visible",timeout=4000)
                el.click(); attach_clicked=True; page.wait_for_timeout(800); break
            except Exception: continue
        if not attach_clicked: return False, False

        file_set = False
        for upload_sel in ["text=Upload from this device",
                           "xpath=//span[normalize-space(text())='Upload from this device']",
                           "[role='menuitem']:has-text('Upload')"]:
            try:
                el=page.locator(upload_sel).first; el.wait_for(state="visible",timeout=4000)
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    el.click()
                fc_info.value.set_files(file_path); file_set=True; break
            except Exception: continue
        if not file_set:
            try:
                with page.expect_file_chooser(timeout=3000) as fc_info:
                    page.locator("input[type='file']").first.click()
                fc_info.value.set_files(file_path); file_set=True
            except Exception: pass
        if not file_set: return False, False

        self._close_os_file_dialog_if_open()
        upload_complete = False
        for _ in range(25):
            page.wait_for_timeout(1000)
            for csel in ["[data-tid='post-compose-layout'] [class*='chiclet']",
                         "[data-tid='post-compose-layout'] [aria-label*='.docx']"]:
                try:
                    if page.locator(csel).count() > 0: upload_complete=True; break
                except Exception: pass
            if upload_complete: break
        return True, upload_complete

    def _close_os_file_dialog_if_open(self):
        import time as _t
        try:
            from pywinauto import Desktop
            desk=Desktop(backend="win32"); _t.sleep(0.3)
            for win in desk.windows():
                try:
                    title=win.window_text()
                    if title in ("Open", "Choose File to Upload", "File Upload"):
                        win.close(); _t.sleep(0.3); return
                except Exception: continue
        except Exception: pass

    def _build_file_metadata(self, graph_data: dict, file_path: str) -> str:
        file_name = os.path.basename(file_path)
        file_ext  = os.path.splitext(file_name)[1].lstrip(".").lower()
        if not graph_data: return "[]"
        item_id  = graph_data.get("id", ""); guid = item_id.replace("-", "").lower()
        web_url  = graph_data.get("webUrl", "")
        pref     = graph_data.get("parentReference", {}) or {}
        drive_id = pref.get("driveId", "")
        site_url = f"https://my.microsoftpersonalcontent.com/personal/{drive_id.lower()}" if drive_id else ""
        fmt_id   = f"{drive_id.upper()}!s{guid}" if drive_id and guid else item_id
        return json.dumps([{
            "itemid": item_id, "fileName": file_name, "fileType": file_ext,
            "fileInfo": {"itemId": fmt_id, "fileUrl": web_url, "siteUrl": site_url,
                         "serverRelativeUrl": "", "shareUrl": "", "shareId": ""},
            "fileChicletState": {"serviceName": "p2p", "state": "active"},
            "@type": "http://schema.skype.com/File", "version": 2, "id": item_id,
            "baseUrl": site_url, "objectUrl": web_url, "type": file_ext,
            "title": file_name, "state": "active",
        }])

    def _call_community_post_api(self, page, thread_id, subject, files_json):
        try:
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            cmi  = str(random.randint(10**18, 10**19 - 1))
            url  = f"{_API_BASE}/users/ME/conversations/{quote(thread_id, safe='')}/messages"
            mri, name = self._get_sender_identity(page)
            name = name or _TC3_SENDER_DISPLAY_NAME
            body = {"type": "Message", "conversationid": thread_id,
                    "conversationLink": f"blah/{thread_id}", "from": mri or "", "fromUserId": mri or "",
                    "composetime": now, "originalarrivaltime": now, "content": "",
                    "messagetype": "RichText/Html", "contenttype": "Text", "imdisplayname": name,
                    "clientmessageid": cmi, "callId": "", "state": 0, "version": "0",
                    "amsreferences": [],
                    "properties": {"importance": "", "subject": subject, "title": "", "cards": "[]",
                                   "links": "[]", "mentions": "[]", "onbehalfof": None,
                                   "files": files_json, "policyViolation": None, "formatVariant": "TEAMS"},
                    "postType": "Standard", "crossPostChannels": []}
            resp   = page.request.post(url, headers=self._api_headers(page, {"Content-Type": "application/json"}), data=json.dumps(body))
            status = resp.status
            return (status, None) if (resp.ok or status == 403) else (status, f"HTTP {status}")
        except Exception as e:
            if any(x in str(e) for x in ["ECONNRESET", "ECONNREFUSED", "Connection reset", "ERR_CONNECTION_RESET"]):
                return "CASB_BLOCKED", None
            return None, str(e)

    def _check_community_post_delivery(self, page, thread_id, subject) -> bool:
        try:
            url  = f"https://teams.live.com/api/csa/api/v2/teams/{thread_id}/channels/{thread_id}"
            resp = page.request.get(url, headers=self._api_headers(page))
            if not resp.ok: return False
            for chain in resp.json().get("replyChains", []):
                for msg in (chain.get("messages") or [chain]):
                    sub = (msg.get("properties", {}) or {}).get("subject", "") or ""
                    if subject.lower() in sub.lower(): return True
            return False
        except Exception: return False
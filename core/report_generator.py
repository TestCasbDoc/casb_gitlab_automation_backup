"""
report_generator.py — HTML and JSON report generation.
"""
import json
import config
from config import (
    REPORT_DATA,
    SSH_USER, SSH_HOST, FAST_LOG, SSH_REQUIRED_FOR_PASS,
    DECRYPTION_CHECK_URL, DECRYPTION_ISSUER_CN_KEYWORD, DECRYPTION_REQUIRED_FOR_PASS,
    RECIPIENTS, LOG_MATCH_KEYWORDS,
)


def save_report(all_results):
    # Save combined report: config metadata + all TC results
    report = {
        "run_timestamp": REPORT_DATA.get("run_timestamp", ""),
        "run_status"   : REPORT_DATA.get("run_status", "UNKNOWN"),
        "config"       : REPORT_DATA.get("config", {}),
        "results"      : all_results,
    }
    with open(config.REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report saved: {config.REPORT_FILE}")


def generate_html_report(all_results):
    run_ts   = REPORT_DATA["run_timestamp"]
    cli_step = REPORT_DATA.get("step_cli", {})
    total    = len(all_results)
    passed   = sum(1 for r in all_results if r.get("status") == "PASS")
    failed   = total - passed
    overall  = "PASS" if failed == 0 else "FAIL"

    def badge(status):
        s = (status or "").upper()
        colors = {"PASS": "#00c853", "FAIL": "#d50000", "INFO": "#0288d1",
                  "SKIPPED": "#ff6f00", "WARN": "#ff6f00"}
        c = colors.get(s, "#555")
        return f'<span class="badge" style="background:{c}">{s}</span>'

    def step_card(num, title, status, details, screenshot_b64=None):
        borders = {"pass": "#00c853", "fail": "#d50000", "info": "#0288d1",
                   "skipped": "#ff6f00", "warn": "#ff6f00"}
        icons   = {"pass": "✓", "fail": "✗", "info": "i", "skipped": "~", "warn": "!"}
        border  = borders.get(status, "#444")
        icon    = icons.get(status, "•")
        rows    = "".join(f'<div class="drow">{d}</div>' for d in details)
        img_html = (
            f'<div class="ss-wrap"><div class="ss-label">Screenshot</div>'
            f'<img src="data:image/png;base64,{screenshot_b64}" '
            f'class="ss-img" onclick="openModal(this.src)"/></div>'
        ) if screenshot_b64 else ""
        return (
            f'<div class="scard" style="border-left:4px solid {border}">'
            f'<div class="scard-hdr">'
            f'<span class="sico" style="background:{border}">{icon}</span>'
            f'<span class="snum">{num}</span>'
            f'<span class="stitle">{title}</span>'
            f'{badge(status)}'
            f'</div>'
            f'<div class="scard-body">{rows}{img_html}</div>'
            f'</div>'
        )

    cli_cards = ""  # kept for compatibility — content moved to fastlog_clear_cards (Step 3)

    # ── Pre-test clear step cards (VOS stats + fast.log) ───────────
    vos_clear      = REPORT_DATA.get("step_vos_clear", {})
    vos_clear_cards = ""
    if vos_clear:
        vos_clear_cards += step_card(
            "PRE · SSH", "SSH Connection to VOS Branch",
            "pass" if vos_clear.get("success") else "fail",
            [f"Host      : {SSH_USER}@{SSH_HOST}",
             f"Success   : {'Yes' if vos_clear.get('success') else 'No'}"]
            + ([f"Error     : {vos_clear['error']}"] if vos_clear.get("error") else [])
        )
        for i, label in enumerate(vos_clear.get("cleared", []), 1):
            ok = "(response unclear)" not in label
            vos_clear_cards += step_card(
                f"PRE · {i}", f"Clear: {label.replace(' (response unclear)', '')}",
                "pass" if ok else "warn",
                [f"Result : {'Cleared ✓' if ok else 'Response unclear — may not have cleared'}"]
            )
        fl_ok  = vos_clear.get("fastlog_cleared", False)
        fl_err = vos_clear.get("fastlog_error")
        vos_clear_cards += step_card(
            "PRE · fast.log", "Clear fast.log",
            "pass" if fl_ok else "warn",
            [f"Command : request clear log idp/fast.log",
             f"Result  : {'Cleared ✓' if fl_ok else 'Response unclear'}"]
            + ([f"Response: {fl_err}"] if fl_err else [])
        )

    # ── Decryption step card ─────────────────────────────────────────
    dec      = REPORT_DATA.get("step_decryption", {})
    dec_card = ""
    if dec:
        dec_status  = dec.get("status", "warn")
        dec_details = dec.get("details", [
            f"Target        : {DECRYPTION_CHECK_URL}",
            f"Issuer keyword: {DECRYPTION_ISSUER_CN_KEYWORD}",
            f"Required      : {'Yes' if DECRYPTION_REQUIRED_FOR_PASS else 'No (warn only)'}",
            f"Result        : {dec.get('status_label', 'N/A')}",
        ])
        dec_card = step_card(
            "PRE · TLS", "TLS Decryption Check (SSL Inspection)",
            dec_status,
            dec_details,
        )

    # ── Load TC metadata dynamically from app.yaml ───────────────────────────
    # Zero hardcoding: add/rename a TC only in app.yaml — report auto-updates.
    import os as _os
    import yaml as _yaml

    def _load_activity_meta():
        """
        Read the app's app.yaml and return a dict keyed by activity_name:
          {
            "post":           {"tc_label":"TC1","tc_num":1,"activity":"Post","nav":"Sign in → …"},
            "community_post": {"tc_label":"TC5","tc_num":5,"activity":"Post","nav":"Sign in → …"},
            …
          }
        Falls back to an empty dict if the yaml cannot be loaded.
        """
        app_id   = REPORT_DATA.get("config", {}).get("app_id", "")
        app_name = REPORT_DATA.get("config", {}).get("app_name", "App")
        if not app_id:
            return {}, app_name

        # app.yaml lives at  <repo_root>/apps/<app_id>/app.yaml
        yaml_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "apps", app_id, "app.yaml"
        )
        try:
            with open(yaml_path, encoding="utf-8") as _f:
                _cfg = _yaml.safe_load(_f)
        except Exception as _e:
            print(f"[report] Warning: could not load {yaml_path}: {_e}")
            return {}, app_name

        resolved_app_name = _cfg.get("name", app_name)
        meta = {}
        for act_key, act_val in (_cfg.get("activities") or {}).items():
            tc_label = act_val.get("tc_label", act_key.upper())
            tc_num   = int(tc_label.replace("TC", "")) if tc_label.startswith("TC") else 0
            category = act_val.get("category", act_key)
            activity = category.capitalize()
            nav      = str(act_val.get("nav") or "").strip()
            meta[act_key.lower()] = {
                "tc_label" : tc_label,
                "tc_num"   : tc_num,
                "activity" : activity,
                "nav"      : nav,
                "app_name" : resolved_app_name,
            }
        return meta, resolved_app_name

    _ACT_META, _APP_NAME = _load_activity_meta()

    def _get_meta(result):
        """Return the yaml-driven meta dict for this result (fallback to first entry)."""
        aname = (result.get("activity_name") or "").lower().strip()
        if aname in _ACT_META:
            return _ACT_META[aname]
        # Substring fallback — sort by key length descending so longer (more specific)
        # keys like "community_post" win over shorter ones like "post".
        candidates = sorted(
            [(key, m) for key, m in _ACT_META.items() if key in aname or aname in key],
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        if candidates:
            return candidates[0][1]
        # last resort: return the TC with the lowest tc_num
        if _ACT_META:
            return min(_ACT_META.values(), key=lambda m: m["tc_num"])
        return {"tc_label": "TC?", "tc_num": 0, "activity": "Post",
                "nav": "", "app_name": _APP_NAME}

    def _tc_block(tc_idx, result):
        meta     = _get_meta(result)
        tc_label = meta["tc_label"]
        act      = meta["activity"]
        nav_full = meta["nav"]
        st       = result.get("status", "FAIL")
        ts       = result.get("timestamp", "")
        fails    = result.get("fail_reason", [])
        steps_html = "".join(
            step_card(s["number"], s["name"], s["status"], s["details"], s.get("screenshot_b64"))
            for s in result.get("steps", [])
        )
        fails_html = (
            '<div class="tc-fails"><b>Fail Reasons:</b><ul>'
            + "".join(f"<li>{fr}</li>" for fr in fails)
            + '</ul></div>'
        ) if fails else ""
        return (
            f'<div class="tc-block">'
            f'<div class="tc-hdr">'
            f'<div class="tc-left">'
            f'<span class="tc-badge">{tc_label}</span>'
            f'<div class="tc-info">'
            f'<span class="tc-act">Activity: <b>{act}</b></span>'
            f'<span class="tc-nav">&#8594; {nav_full}</span>'
            f'</div></div>'
            f'<div class="tc-right">'
            f'<span class="tc-ts">{ts}</span>'
            f'{badge(st)}'
            f'</div></div>'
            f'{fails_html}'
            f'<div class="tc-steps">{steps_html}</div>'
            f'</div>'
        )

    from collections import defaultdict
    _ACTIVITY_ICONS = {"Post": "📤", "Share": "🔗", "Forward": "↪️", "Reply": "↩️"}
    _ACTIVITY_ORDER = ["Post", "Share", "Forward", "Reply"]

    activity_groups = defaultdict(list)
    for res in all_results:
        act_name = _get_meta(res)["activity"]
        activity_groups[act_name].append(res)

    sorted_activities = sorted(
        activity_groups.keys(),
        key=lambda a: (_ACTIVITY_ORDER.index(a) if a in _ACTIVITY_ORDER else 99, a)
    )

    rec_html = ""
    for act_name in sorted_activities:
        act_results = activity_groups[act_name]
        act_pass    = sum(1 for r in act_results if r.get("status") == "PASS")
        act_total   = len(act_results)
        act_fail    = act_total - act_pass
        act_overall = "PASS" if act_fail == 0 else "FAIL"
        act_color   = "#00c853" if act_overall == "PASS" else "#ff1744"
        act_icon    = _ACTIVITY_ICONS.get(act_name, "🔹")
        tcs_html    = "".join(_tc_block(i + 1, res) for i, res in enumerate(act_results))
        rec_html += (
            f'<div class="act-group">'
            f'<div class="act-hdr">'
            f'<span class="act-icon">{act_icon}</span>'
            f'<span class="act-name">{_APP_NAME} &mdash; {act_name} Activity</span>'
            f'<span class="act-count">{act_pass}/{act_total} passed</span>'
            f'<span class="act-status" style="color:{act_color}">{act_overall}</span>'
            f'</div>'
            f'<div class="act-tcs">{tcs_html}</div>'
            f'</div>'
        )

    sum_rows = ""
    for r in all_results:
        st   = r.get("status", "FAIL")
        sc   = "#00c853" if st == "PASS" else "#d50000"
        fl   = r.get("fast_log_confirmed", False)
        fls  = r.get("fast_log_skipped", False)
        flok = "Skipped"      if fls else ("Verified" if fl else "Not Verified")
        flc  = "#ff6f00"      if fls else ("#00c853" if fl else "#d50000")
        _ui_blk = r.get("ui_activity_blocked")
        if _ui_blk is not None:
            dval = "Verified" if _ui_blk else "Not Verified"
            dclr = "#00c853" if _ui_blk else "#d50000"
        else:
            dval = "Verified" if r.get("message_not_delivered") else "Not Verified"
            dclr = "#00c853" if r.get("message_not_delivered") else "#d50000"
        casb_popup = "Verified" if r.get("blocked_by_casb") else "Not Verified"
        cbclr      = "#00c853"  if r.get("blocked_by_casb") else "#d50000"
        false_sigs = r.get("false_sig_ids", [])
        false_cell = ", ".join(false_sigs) if false_sigs else "None"
        false_clr  = "#d50000" if false_sigs else "#00c853"
        ck   = lambda v: "✓" if v else "✗"
        _m         = _get_meta(r)
        nav_detail = f"{_m['tc_num']}. {_m['nav']}"
        app_name   = _m["app_name"]
        act_name   = _m["activity"]
        # Actual sig IDs captured from fast.log during this TC run
        sig_ids       = r.get("fast_log_sig_ids", [])
        multi_sigs    = r.get("fast_log_multi_sigs", False)
        if not sig_ids:
            sig_id_cell = '<span style="color:var(--mut)">—</span>'
        elif multi_sigs:
            ids_str = ", ".join(sig_ids)
            sig_id_cell = (
                f'<span style="color:#ff6f00" title="Multiple sig IDs hit — not validated">' +
                f'⚠ {ids_str}</span>'
            )
        else:
            sig_id_cell = sig_ids[0]
        sum_rows += (
            f'<tr>'
            f'<td>{r.get("timestamp","")}</td>'
            f'<td style="font-weight:600">{app_name}</td>'
            f'<td style="font-weight:600">{act_name}</td>'
            f'<td style="font-family:var(--mono);font-size:11px;max-width:320px;white-space:normal">{nav_detail}</td>'
            f'<td style="font-family:var(--mono);font-size:11px">{sig_id_cell}</td>'
            f'<td style="color:{cbclr};font-weight:600">{casb_popup}</td>'
            f'<td style="color:{dclr};font-weight:600">{dval}</td>'
            f'<td style="color:{flc};font-weight:600">{flok}</td>'
            f'<td style="color:{false_clr};font-family:var(--mono);font-size:11px">{false_cell}</td>'
            f'<td style="color:{sc};font-weight:700">{st}</td>'
            f'</tr>'
        )

    ov_cls = "ov-pass" if overall == "PASS" else "ov-fail"
    ov_ico = "✓" if overall == "PASS" else "✗"

    dashboard_url = REPORT_DATA.get("server_url", "") or "/"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CASB Test Report — {run_ts}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap');
:root{{--bg:#0d0f14;--sur:#161921;--sur2:#1e2330;--bdr:#2a2f3d;--acc:#00e5ff;--acc2:#7b61ff;--pass:#00c853;--fail:#ff1744;--txt:#e2e8f0;--mut:#8892a4;--mono:'JetBrains Mono',monospace;--sans:'Syne',sans-serif;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--txt);font-family:var(--sans);min-height:100vh}}
.hdr{{background:linear-gradient(135deg,#0d0f14,#161921 50%,#1a1f2e);border-bottom:1px solid var(--bdr);padding:36px 48px 28px;position:relative;overflow:hidden}}.back-btn{{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);color:#fff;text-decoration:none;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;margin-bottom:16px;transition:background 0.15s}}.back-btn:hover{{background:rgba(255,255,255,0.15)}}
.hdr::before{{content:'';position:absolute;top:-80px;right:-80px;width:320px;height:320px;background:radial-gradient(circle,rgba(0,229,255,.07) 0%,transparent 70%);pointer-events:none}}
.hdr-top{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-ico{{width:46px;height:46px;background:linear-gradient(135deg,var(--acc),var(--acc2));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px}}
.brand h1{{font-size:22px;font-weight:800;letter-spacing:-.5px;color:#fff}}
.brand p{{font-size:11px;color:var(--mut);font-family:var(--mono);margin-top:3px}}
.meta{{font-family:var(--mono);font-size:11px;color:var(--mut);text-align:right;line-height:2}}
.sbar{{display:flex;gap:12px;margin-top:28px;flex-wrap:wrap;align-items:center}}
.chip{{background:var(--sur2);border:1px solid var(--bdr);border-radius:8px;padding:10px 18px;display:flex;flex-direction:column;align-items:center}}
.chip .val{{font-size:26px;font-weight:800;line-height:1}}
.chip .lbl{{font-size:10px;color:var(--mut);margin-top:3px;font-family:var(--mono);text-transform:uppercase;letter-spacing:.5px}}
.ov{{padding:12px 28px;border-radius:8px;font-size:20px;font-weight:800;letter-spacing:1px;display:flex;align-items:center;gap:8px}}
.ov-pass{{background:rgba(0,200,83,.12);border:1px solid var(--pass);color:var(--pass)}}
.ov-fail{{background:rgba(255,23,68,.12);border:1px solid var(--fail);color:var(--fail)}}
.main{{padding:32px 48px;max-width:1200px;margin:0 auto}}
.sec-title{{font-size:12px;font-family:var(--mono);color:var(--acc);text-transform:uppercase;letter-spacing:2px;margin:36px 0 14px;display:flex;align-items:center;gap:10px}}
.sec-title::after{{content:'';flex:1;height:1px;background:var(--bdr)}}
.scard{{background:var(--sur);border:1px solid var(--bdr);border-radius:10px;margin-bottom:10px;overflow:hidden}}
.scard-hdr{{display:flex;align-items:center;gap:10px;padding:13px 16px}}
.sico{{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;flex-shrink:0}}
.snum{{font-family:var(--mono);font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}}
.stitle{{flex:1;font-size:13px;font-weight:600}}
.scard-body{{padding:0 16px 14px 52px;border-top:1px solid var(--bdr)}}
.drow{{font-family:var(--mono);font-size:11px;color:var(--mut);padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03);word-break:break-all}}
.drow:last-of-type{{border-bottom:none}}
.ss-wrap{{margin-top:12px}}
.ss-label{{font-size:10px;font-family:var(--mono);color:var(--mut);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px}}
.ss-img{{max-width:100%;border-radius:6px;border:1px solid var(--bdr);cursor:zoom-in;transition:opacity .2s}}
.ss-img:hover{{opacity:.9}}
.rblock{{background:var(--sur);border:1px solid var(--bdr);border-radius:12px;margin-bottom:24px;overflow:hidden}}
.rhdr{{display:flex;justify-content:space-between;align-items:center;padding:16px 22px;background:var(--sur2);border-bottom:1px solid var(--bdr);flex-wrap:wrap;gap:10px}}
.rtitle{{display:flex;align-items:center;gap:8px;font-size:17px;font-weight:700}}
.rico{{font-size:20px}}
.rmeta{{display:flex;align-items:center;gap:10px}}
.rts{{font-family:var(--mono);font-size:11px;color:var(--mut)}}
.rsteps{{padding:18px 22px}}
.fails{{background:rgba(255,23,68,.07);border-left:3px solid var(--fail);padding:10px 18px;font-family:var(--mono);font-size:11px;color:#ff8a80}}
.fails ul{{margin-top:5px;padding-left:14px}}
.fails li{{margin:2px 0}}
.badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;font-family:var(--mono);letter-spacing:1px;color:#fff}}
.stbl{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;margin-bottom:40px}}
.stbl th{{background:var(--sur2);color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:1px;padding:11px 14px;text-align:left;border-bottom:1px solid var(--bdr)}}
.stbl td{{padding:11px 14px;border-bottom:1px solid var(--bdr)}}
.stbl tr:last-child td{{border-bottom:none}}
.stbl tr:hover td{{background:var(--sur2)}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:9999;align-items:center;justify-content:center;cursor:zoom-out}}
.modal.open{{display:flex}}
.modal img{{max-width:95vw;max-height:95vh;border-radius:8px;box-shadow:0 20px 80px rgba(0,0,0,.8)}}
.footer{{text-align:center;padding:20px;font-family:var(--mono);font-size:10px;color:var(--mut);border-top:1px solid var(--bdr)}}
.act-group{{margin-bottom:32px}}
.act-hdr{{display:flex;align-items:center;gap:12px;padding:14px 20px;background:var(--sur2);border:1px solid var(--bdr);border-radius:10px 10px 0 0;border-bottom:2px solid var(--acc)}}
.act-icon{{font-size:20px}}
.act-name{{font-size:15px;font-weight:700;flex:1;color:#fff}}
.act-count{{font-family:var(--mono);font-size:11px;color:var(--mut)}}
.act-status{{font-family:var(--mono);font-size:12px;font-weight:700}}
.act-tcs{{border:1px solid var(--bdr);border-top:none;border-radius:0 0 10px 10px;overflow:hidden}}
.tc-block{{border-bottom:1px solid var(--bdr);background:var(--sur)}}
.tc-block:last-child{{border-bottom:none}}
.tc-hdr{{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;background:rgba(255,255,255,.02);flex-wrap:wrap;gap:8px}}
.tc-left{{display:flex;align-items:center;gap:12px}}
.tc-badge{{background:var(--acc2);color:#fff;font-family:var(--mono);font-size:11px;font-weight:700;padding:4px 10px;border-radius:5px;letter-spacing:.5px}}
.tc-info{{display:flex;flex-direction:column;gap:2px}}
.tc-act{{font-size:12px;font-weight:600;color:var(--txt)}}
.tc-nav{{font-family:var(--mono);font-size:11px;color:var(--mut)}}
.tc-right{{display:flex;align-items:center;gap:10px}}
.tc-ts{{font-family:var(--mono);font-size:10px;color:var(--mut)}}
.tc-steps{{padding:12px 18px 16px}}
.tc-fails{{background:rgba(255,23,68,.07);border-left:3px solid var(--fail);padding:8px 18px;font-family:var(--mono);font-size:11px;color:#ff8a80}}
.tc-fails ul{{margin-top:4px;padding-left:14px}}
</style>
</head>
<body>
<div class="hdr">
  <a href="{dashboard_url}" class="back-btn">&#8592; Dashboard</a>
  <div class="hdr-top">
    <div class="brand">
      <div class="brand-ico">&#128737;</div>
      <div>
        <h1>CASB Block Verification Report</h1>
        <p>{_APP_NAME} &middot; Versa SASE &middot; fast.log + recipient browser verification</p>
      </div>
    </div>
    <div class="meta">
      <div>Run timestamp : {run_ts}</div>
      <div>SSH target    : {SSH_USER}@{SSH_HOST}</div>
      <div>Log file      : {FAST_LOG}</div>
      <div>Recipients    : {", ".join(RECIPIENTS)}</div>
      <div>SSH required  : {"Yes" if SSH_REQUIRED_FOR_PASS else "No (optional)"}</div>
    </div>
  </div>
  <div class="sbar">
    <div class="ov {ov_cls}">{ov_ico} OVERALL: {overall}</div>
    <div class="chip"><span class="val">{total}</span><span class="lbl">Total</span></div>
    <div class="chip"><span class="val" style="color:var(--pass)">{passed}</span><span class="lbl">Passed</span></div>
    <div class="chip"><span class="val" style="color:var(--fail)">{failed}</span><span class="lbl">Failed</span></div>
  </div>
</div>
<div class="main">
  <div class="sec-title">Step 0 &mdash; Pre-Test: TLS Decryption Check</div>
  {dec_card}
  <div class="sec-title">Step 1 &mdash; Pre-Test: Clear Versa CLI Logs</div>
  {cli_cards}
  <div class="sec-title">Step 2 &mdash; Pre-Test: Clear VOS Stats + fast.log</div>
  {vos_clear_cards}
  <div class="sec-title">Step 3 &mdash; Recipient Test Cases</div>
  {rec_html}
  <div class="sec-title">Final Summary</div>
  <table class="stbl">
    <thead><tr>
      <th>Timestamp</th><th>Application</th><th>Activity</th><th>Navigation Detail</th>
      <th>Sig ID</th><th>CASB Block Popup</th><th>Activity Blocked</th><th>Fast Log Signature</th>
      <th>False Sig ID Hits</th><th>Result</th>
    </tr></thead>
    <tbody>
      {sum_rows}
      <tr style="background:var(--sur2);font-weight:700;border-top:2px solid var(--bdr)">
        <td colspan="4" style="color:var(--acc)">TOTAL</td>
        <td colspan="5" style="color:var(--mut);font-size:11px">
          Navigations: {passed} passed, {failed} failed out of {total}
        </td>
        <td style="color:{'var(--pass)' if failed==0 else 'var(--fail)'};">{passed}/{total} PASS ({int(passed/total*100) if total else 0}%)</td>
      </tr>
    </tbody>
  </table>
</div>
<div class="modal" id="modal" onclick="closeModal()"><img id="mimg" src="" alt="screenshot"/></div>
<div class="footer">Generated by CASB Automation Script &middot; {run_ts}</div>
<script>
function openModal(src){{document.getElementById('mimg').src=src;document.getElementById('modal').classList.add('open');}}
function closeModal(){{document.getElementById('modal').classList.remove('open');}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});
</script>
</body>
</html>"""

    with open(config.HTML_REPORT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML report saved: {config.HTML_REPORT}")
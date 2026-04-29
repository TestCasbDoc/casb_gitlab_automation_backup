"""
CASB Results Server — MS Teams CASB Block Verification Dashboard
Run: python app.py
Access: http://0.0.0.0:4012/

Stores run results uploaded from ms_teams_personal_send_post.py.
Each run is a folder under RESULTS_DIR containing:
  - test_report.json
  - test_report.html
  - vos_dumps/
  - har_files/
  - *.png screenshots
"""

import os
import json
import zipfile
import shutil
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, abort, jsonify
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload

# ── Storage ──────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)
PINS_FILE = os.path.join(RESULTS_DIR, ".pinned_runs.json")

def _load_pins():
    """Return set of pinned run_ids."""
    if not os.path.exists(PINS_FILE):
        return set()
    try:
        with open(PINS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_pins(pins):
    with open(PINS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(pins), f)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_run(run_id):
    """Load test_report.json for a run. Returns dict or None."""
    path = os.path.join(RESULTS_DIR, run_id, "test_report.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Normalise: new format is {run_timestamp, config, results:[...]}
        # Old format is just a list
        if isinstance(data, list):
            return {"results": data, "config": {}, "run_timestamp": "", "run_status": "UNKNOWN"}
        return data
    except Exception:
        return None


def _run_summary(run_id):
    """Return a lightweight summary dict for the runs list page."""
    data    = _load_run(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)

    try:
        _run_id_clean = run_id.replace("_PINNED", "")
        # Strip username suffix: run_YYYYMMDD_HHMMSS_username → run_YYYYMMDD_HHMMSS
        _parts = _run_id_clean.split("_")
        _run_id_ts = "_".join(_parts[:3])  # run, YYYYMMDD, HHMMSS
        ts_fmt = datetime.strptime(_run_id_ts, "run_%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts_fmt = run_id.replace("_PINNED", "")

    if data is None:
        return {
            "run_id": run_id, "timestamp": ts_fmt,
            "total": 0, "passed": 0, "failed": 0, "status": "UNKNOWN",
            "sig_ids": [], "has_html": False, "config": {}, "trigger_pct": "0%",
        }

    results = data.get("results", [])
    cfg     = data.get("config", {})
    total   = len(results)
    passed  = sum(1 for r in results if r.get("status") == "PASS")
    failed  = total - passed
    status  = "PASS" if failed == 0 and total > 0 else "FAIL"

    sig_ids = []
    seen = set()
    for r in results:
        for sid in r.get("fast_log_sig_ids", []):
            if sid not in seen:
                seen.add(sid)
                sig_ids.append(sid)

    has_html = os.path.exists(os.path.join(run_dir, "test_report.html"))

    pins = _load_pins()
    return {
        "run_id"      : run_id,
        "timestamp"   : ts_fmt,
        "total"       : total,
        "passed"      : passed,
        "failed"      : failed,
        "status"      : status,
        "sig_ids"     : sig_ids,
        "has_html"    : has_html,
        "trigger_pct" : f"{(passed/total*100):.1f}%" if total else "0%",
        "config"      : cfg,
        "pinned"      : run_id in pins,
    }


def _all_runs():
    """Return list of run summary dicts sorted newest first."""
    runs = []
    for name in os.listdir(RESULTS_DIR):
        if os.path.isdir(os.path.join(RESULTS_DIR, name)):
            runs.append(_run_summary(name))
    runs.sort(key=lambda r: (not r["pinned"], r["run_id"]), reverse=False)
    runs.sort(key=lambda r: r["run_id"], reverse=True)
    runs.sort(key=lambda r: not r["pinned"])
    return runs


def _load_app_yaml_meta(app_id):
    """
    Load activity metadata from apps/<app_id>/app.yaml.
    Returns dict keyed by activity_name (lowercase):
      { "post": {"tc_label":"TC1","tc_num":1,"activity":"Post","nav":"Sign in → …"}, … }
    Falls back to empty dict if yaml cannot be found/parsed.
    The server sits at  casb_server/  — app.yaml is at  ../apps/<app_id>/app.yaml
    """
    import yaml as _yaml
    if not app_id:
        return {}
    yaml_path = os.path.join(
        os.path.dirname(__file__),   # casb_server/
        "..",                         # repo root
        "apps", app_id, "app.yaml"
    )
    try:
        with open(yaml_path, encoding="utf-8") as _f:
            cfg = _yaml.safe_load(_f)
    except Exception as _e:
        print(f"[casb_server] Warning: could not load {yaml_path}: {_e}")
        return {}
    meta = {}
    for act_key, act_val in (cfg.get("activities") or {}).items():
        tc_label = act_val.get("tc_label", act_key.upper())
        tc_num   = int(tc_label.replace("TC", "")) if tc_label.startswith("TC") else 0
        category = act_val.get("category", act_key)
        activity = category.capitalize()
        nav      = str(act_val.get("nav") or "").strip()
        meta[act_key.lower()] = {
            "tc_label": tc_label,
            "tc_num"  : tc_num,
            "activity": activity,
            "nav"     : nav,
        }
    return meta


def _resolve_tc_meta(activity_name, act_meta, tc_label=None):
    """
    Look up activity metadata from the yaml-driven dict.
    1. Direct match on activity_name key (e.g. "community_post")
    2. Substring fallback on activity_name
    3. Match by tc_label (e.g. "TC5") — handles old saved JSONs that
       have tc_label but no activity_name field
    4. Last resort: lowest tc_num
    """
    aname = (activity_name or "").lower().strip()
    if aname and aname in act_meta:
        return act_meta[aname]
    # Substring fallback — sort by key length descending so longer (more specific)
    # keys like "community_post" win over shorter ones like "post".
    if aname:
        candidates = sorted(
            [(key, m) for key, m in act_meta.items() if key in aname or aname in key],
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        if candidates:
            return candidates[0][1]
    # tc_label fallback — for old results saved before activity_name was persisted
    if tc_label:
        tl = tc_label.strip().upper()
        for m in act_meta.values():
            if m["tc_label"].upper() == tl:
                return m
    # last resort: lowest tc_num
    if act_meta:
        return min(act_meta.values(), key=lambda m: m["tc_num"])
    return {"tc_label": "TC?", "tc_num": 0, "activity": "Post", "nav": ""}


def _tc_table(run_id):
    """Return per-TC rows for the run detail page."""
    import re as _re
    data = _load_run(run_id)
    if not data:
        return []
    results = data.get("results", []) if isinstance(data, dict) else data

    # Load nav metadata from app.yaml — zero hardcoding
    app_id   = data.get("config", {}).get("app_id", "") if isinstance(data, dict) else ""
    act_meta = _load_app_yaml_meta(app_id)

    rows = []
    for r in results:
        meta     = _resolve_tc_meta(r.get("activity_name"), act_meta, tc_label=r.get("tc_label"))
        tc_label = meta["tc_label"]
        activity = meta["activity"]
        nav      = meta["nav"]

        sig_ids      = r.get("fast_log_sig_ids", [])
        multi_sigs   = r.get("fast_log_multi_sigs", False)
        casb_blocked = r.get("blocked_by_casb", False)
        _uib = r.get("ui_activity_blocked")
        if _uib is not None:
            delivered = not _uib
        else:
            delivered = not r.get("message_not_delivered", True)
        fast_log_ok  = r.get("fast_log_confirmed", False)
        fast_skipped = r.get("fast_log_skipped", False)
        status       = r.get("status", "FAIL")
        fail_reasons = r.get("fail_reason", [])

        # Build sig_id → matching log lines map
        matched_lines = r.get("fast_log_matches", [])
        sig_to_lines = {}
        for line in matched_lines:
            for sid in _re.findall(r'1:(\d{7,}):\d+', line):
                if sid not in sig_to_lines:
                    sig_to_lines[sid] = []
                sig_to_lines[sid].append(line)

        # Build false_sig_id → non-matching log lines map
        false_sig_ids   = r.get("false_sig_ids", [])
        all_log_lines   = r.get("fast_log_matches", []) + []
        # false lines are stored separately if available
        false_sig_to_lines = {}
        for line in r.get("fast_log_all_lines", []):
            for sid in _re.findall(r'1:(\d{7,}):\d+', line):
                if sid in false_sig_ids and sid not in sig_to_lines:
                    if sid not in false_sig_to_lines:
                        false_sig_to_lines[sid] = []
                    false_sig_to_lines[sid].append(line)

        rows.append({
            "tc"              : tc_label,
            "activity"        : activity,
            "nav"             : nav,
            "sig_ids"         : sig_ids,
            "multi_sigs"      : multi_sigs,
            "casb_blocked"    : casb_blocked,
            "delivered"       : delivered,
            "fast_log_ok"     : fast_log_ok,
            "fast_skipped"    : fast_skipped,
            "status"          : status,
            "fail_reasons"    : fail_reasons,
            "false_sig_ids"   : false_sig_ids,
            "sig_to_lines"    : sig_to_lines,
            "false_sig_to_lines": false_sig_to_lines,
            "lef_confirmed"      : r.get("lef_confirmed",      False),
            "lef_skipped"        : r.get("lef_skipped",        True),
            "session_verified"   : r.get("session_verified",   False),
            "session_skipped"    : r.get("session_skipped",    True),
            "vos_stats_verified" : r.get("vos_stats_verified", False),
            "vos_stats_skipped"  : r.get("vos_stats_skipped",  True),
            "vos_stats_verified": r.get("vos_stats_verified", False),
            "vos_stats_skipped" : r.get("vos_stats_skipped",  True),
        })
    return rows


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    runs = _all_runs()
    total_runs   = len(runs)
    total_pass   = sum(1 for r in runs if r["status"] == "PASS")
    total_fail   = total_runs - total_pass
    return render_template("index.html",
                           runs=runs,
                           total_runs=total_runs,
                           total_pass=total_pass,
                           total_fail=total_fail)


@app.route("/run/<run_id>")
def run_detail(run_id):
    run_id = secure_filename(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)
    if not os.path.isdir(run_dir):
        abort(404)
    summary = _run_summary(run_id)
    rows    = _tc_table(run_id)
    # VOS dump files
    dump_dir   = os.path.join(run_dir, "vos_dumps")
    dump_files = sorted(os.listdir(dump_dir)) if os.path.isdir(dump_dir) else []
    # HAR files
    har_dir    = os.path.join(run_dir, "har_files")
    har_files  = sorted(os.listdir(har_dir)) if os.path.isdir(har_dir) else []
    # LEF logs
    lef_dir   = os.path.join(run_dir, "lef_logs")
    lef_files = sorted(os.listdir(lef_dir)) if os.path.isdir(lef_dir) else []
    # Screenshots
    screenshots = sorted([
        f for f in os.listdir(run_dir)
        if f.lower().endswith(".png")
    ])
    return render_template("run_detail.html",
                           summary=summary,
                           rows=rows,
                           run_id=run_id,
                           dump_files=dump_files,
                           har_files=har_files,
                           lef_files=lef_files,
                           screenshots=screenshots)


@app.route("/run/<run_id>/report")
def view_report(run_id):
    run_id   = secure_filename(run_id)
    html_path = os.path.join(RESULTS_DIR, run_id, "test_report.html")
    if not os.path.exists(html_path):
        abort(404)
    return send_file(html_path)


@app.route("/run/<run_id>/download")
def download_run(run_id):
    run_id  = secure_filename(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)
    if not os.path.isdir(run_dir):
        abort(404)
    zip_path = os.path.join(RESULTS_DIR, f"{run_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(run_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                arc_name = os.path.relpath(abs_path, RESULTS_DIR)
                zf.write(abs_path, arc_name)
    return send_file(zip_path, as_attachment=True, download_name=f"{run_id}.zip")


@app.route("/run/<run_id>/file/<path:filename>")
def download_file(run_id, filename):
    run_id   = secure_filename(run_id)
    run_dir  = os.path.join(RESULTS_DIR, run_id)
    file_path = os.path.join(run_dir, filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(run_dir)):
        abort(403)
    if not os.path.exists(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True)


@app.route("/run/<run_id>/view/<path:filename>")
def view_file(run_id, filename):
    run_id    = secure_filename(run_id)
    run_dir   = os.path.join(RESULTS_DIR, run_id)
    file_path = os.path.join(run_dir, filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(run_dir)):
        abort(403)
    if not os.path.exists(file_path):
        abort(404)

    import base64, html as _html
    ext      = os.path.splitext(filename)[1].lower()
    fname    = os.path.basename(filename)
    back_url = url_for("run_detail", run_id=run_id)
    home_url = url_for("index")
    dl_url   = url_for("download_file", run_id=run_id, filename=filename)

    nav = f'''<div style="position:sticky;top:0;z-index:999;background:#0d5fa3;
        padding:10px 20px;display:flex;align-items:center;gap:10px;
        font-family:Segoe UI,Arial,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.3)">
        <a href="{home_url}" style="color:#fff;text-decoration:none;font-size:13px;
            font-weight:700;background:rgba(255,255,255,.15);padding:5px 12px;border-radius:4px">
            &#8962; Home</a>
        <a href="{back_url}" style="color:#fff;text-decoration:none;font-size:13px;
            font-weight:700;background:rgba(255,255,255,.15);padding:5px 12px;border-radius:4px">
            &#8592; Back to Run</a>
        <span style="color:#90caf9;font-family:Consolas,monospace;font-size:12px;
            flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{fname}</span>
        <a href="{dl_url}" style="color:#fff;text-decoration:none;font-size:13px;
            font-weight:700;background:rgba(255,255,255,.15);padding:5px 12px;border-radius:4px">
            &#8659; Download</a>
    </div>'''

    if ext in (".png", ".jpg", ".jpeg"):
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        html = (f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{fname}</title>
<style>body{{margin:0;background:#1a2540}}
img{{max-width:100%;display:block;margin:24px auto;
    box-shadow:0 4px 20px rgba(0,0,0,.5);border-radius:6px}}</style>
</head><body>{nav}
<img src="data:image/png;base64,{b64}" alt="{fname}"/>
</body></html>''')
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    if ext in (".txt", ".log", ".json", ".har"):
        with open(file_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        escaped = _html.escape(raw)
        html = (f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{fname}</title>
<style>body{{margin:0;background:#0d0f14;color:#e0e0e0;
    font-family:Consolas,monospace;font-size:13px}}
pre{{padding:20px;white-space:pre-wrap;word-break:break-all;margin:0;line-height:1.6}}</style>
</head><body>{nav}
<pre>{escaped}</pre>
</body></html>''')
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    return send_file(file_path, as_attachment=False)


@app.route("/run/<run_id>/raw/<path:filename>")
def raw_file(run_id, filename):
    """Serve raw file inline for embedding in viewer (images)."""
    run_id    = secure_filename(run_id)
    run_dir   = os.path.join(RESULTS_DIR, run_id)
    file_path = os.path.join(run_dir, filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(run_dir)):
        abort(403)
    if not os.path.exists(file_path):
        abort(404)
    return send_file(file_path, as_attachment=False)


@app.route("/run/<run_id>/pin", methods=["POST"])
def pin_run(run_id):
    run_id  = secure_filename(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)
    # Rename folder to add _PINNED suffix if not already there
    if not run_id.upper().endswith("_PINNED") and os.path.isdir(run_dir):
        new_id  = run_id + "_PINNED"
        new_dir = os.path.join(RESULTS_DIR, new_id)
        try:
            os.rename(run_dir, new_dir)
            run_id = new_id  # use new name for pins file
        except Exception as e:
            print(f"[PIN] Could not rename folder: {e}")
    pins = _load_pins()
    pins.add(run_id)
    _save_pins(pins)
    return redirect(url_for("index"))


@app.route("/run/<run_id>/unpin", methods=["POST"])
def unpin_run(run_id):
    run_id  = secure_filename(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)
    # Rename folder to remove _PINNED suffix if present
    if run_id.upper().endswith("_PINNED") and os.path.isdir(run_dir):
        new_id  = run_id[:-7]  # strip _PINNED
        new_dir = os.path.join(RESULTS_DIR, new_id)
        try:
            os.rename(run_dir, new_dir)
            run_id = new_id
        except Exception as e:
            print(f"[UNPIN] Could not rename folder: {e}")
    pins = _load_pins()
    pins.discard(run_id)
    pins.discard(run_id + "_PINNED")  # discard both variants
    _save_pins(pins)
    return redirect(url_for("index"))


@app.route("/run/<run_id>/delete", methods=["POST"])
def delete_run(run_id):
    run_id  = secure_filename(run_id)

    # Guard: refuse to delete pinned runs
    pins = _load_pins()
    if run_id in pins or run_id + "_PINNED" in pins:
        return jsonify({"error": "Cannot delete a pinned run. Unpin it first."}), 403

    run_dir = os.path.join(RESULTS_DIR, run_id)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    zip_path = os.path.join(RESULTS_DIR, f"{run_id}.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    return redirect(url_for("index"))


# ── Upload API (called from ms_teams_personal_send_post.py) ──────────────────

@app.route("/api/upload", methods=["POST"])
def upload_run():
    """
    POST a zip of the entire run folder.
    The zip should have run_YYYYMMDD_HHMMSS/ as its root folder.

    curl example:
      curl -X POST http://HOST:4012/api/upload \
           -F "file=@run_20260318_140357.zip"
    """
    if "file" not in request.files:
        return jsonify({"error": "No file field"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".zip"):
        return jsonify({"error": "Must be a .zip file"}), 400

    tmp_path = os.path.join(RESULTS_DIR, "_upload_tmp.zip")
    f.save(tmp_path)

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # Detect run folder name from zip root
            names = zf.namelist()
            if not names:
                return jsonify({"error": "Empty zip"}), 400
            run_id = names[0].split("/")[0]
            if not run_id.startswith("run_"):
                return jsonify({"error": f"Unexpected root folder: {run_id}"}), 400
            zf.extractall(RESULTS_DIR)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # Auto-pin if run folder ends with _PINNED (from --pin CLI flag)
    if run_id.upper().endswith("_PINNED"):
        pins = _load_pins()
        pins.add(run_id)
        _save_pins(pins)

    return jsonify({"status": "ok", "run_id": run_id,
                    "url": f"/run/{run_id}"}), 200


@app.route("/api/disk")
def api_disk():
    import shutil
    usage = shutil.disk_usage(RESULTS_DIR)
    def human(b):
        for unit in ["B","KB","MB","GB","TB"]:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
    resp = jsonify({
        "free_human" : human(usage.free),
        "used_human" : human(usage.used),
        "total_human": human(usage.total),
        "used_pct"   : round(usage.used / usage.total * 100, 1),
    })
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/send_email/<run_id>", methods=["POST"])
def send_email(run_id):
    """Send HTML report email for a run to given recipients."""
    run_id  = secure_filename(run_id)
    run_dir = os.path.join(RESULTS_DIR, run_id)
    if not os.path.isdir(run_dir):
        return jsonify({"error": "Run not found"}), 404

    data = request.get_json()
    recipients = data.get("recipients", []) if data else []
    if not recipients:
        return jsonify({"error": "No recipients provided"}), 400

    # Load run data
    report_json = os.path.join(run_dir, "test_report.json")
    report_html = os.path.join(run_dir, "test_report.html")

    try:
        with open(report_json, encoding="utf-8") as f:
            run_data = json.load(f)
        all_results  = run_data.get("results", [])
        overall      = "PASS" if all(r.get("status") == "PASS" for r in all_results) else "FAIL"
        run_ts       = run_data.get("run_timestamp", run_id)
    except Exception as e:
        return jsonify({"error": f"Could not load report: {e}"}), 500

    # Read config for SMTP credentials
    try:
        import sys, os as _os
        server_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        import config as _cfg

        # Build email body
        import smtplib, zipfile as _zipfile, tempfile, base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text      import MIMEText
        from email.mime.base      import MIMEBase
        from email                import encoders

        # Simple HTML summary table
        status_emoji = "✅" if overall == "PASS" else "❌"
        subject = f"{status_emoji} CASB Test Report — {overall} — {run_ts}"

        # Build rows
        rows_html = ""
        for r in all_results:
            st   = r.get("status", "FAIL")
            sc   = "#2e7d32" if st == "PASS" else "#c62828"
            cb   = "Verified"     if r.get("blocked_by_casb")      else "Not Verified"
            ab   = "Verified"     if r.get("message_not_delivered") else "Not Verified"
            fl   = r.get("fast_log_confirmed", False)
            fls  = r.get("fast_log_skipped", False)
            flv  = "Skipped"      if fls else ("Verified" if fl else "Not Verified")
            sids = ", ".join(r.get("fast_log_sig_ids", [])) or "—"
            false_sids = ", ".join(r.get("false_sig_ids", [])) or "None"
            aname = (r.get("activity_name") or "post").lower()
            rows_html += f"""<tr>
              <td style="padding:8px;border-bottom:1px solid #eee">{r.get("tc_label","TC")}</td>
              <td style="padding:8px;border-bottom:1px solid #eee">Post</td>
              <td style="padding:8px;border-bottom:1px solid #eee;font-family:monospace;font-size:11px">{sids}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;color:{'#2e7d32' if r.get('blocked_by_casb') else '#c62828'}">{cb}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;color:{'#2e7d32' if r.get('message_not_delivered') else '#c62828'}">{ab}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;color:{'#e65100' if fls else ('#2e7d32' if fl else '#c62828')}">{flv}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;color:{'#c62828' if r.get('false_sig_ids') else '#2e7d32'}">{false_sids}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;font-weight:700;color:{sc}">{st}</td>
            </tr>"""

        total  = len(all_results)
        passed = sum(1 for r in all_results if r.get("status") == "PASS")
        failed = total - passed
        overall_bg = "#2e7d32" if overall == "PASS" else "#c62828"

        html_body = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:Arial,sans-serif">
<div style="max-width:800px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:#1565c0;padding:20px 24px">
    <div style="font-size:18px;font-weight:700;color:#fff">🛡 CASB Block Verification Report</div>
    <div style="font-size:12px;color:#90caf9;margin-top:4px">MS Teams · Versa SASE · {run_ts}</div>
    <div style="margin-top:12px;display:inline-block;background:{overall_bg};color:#fff;font-weight:700;padding:6px 16px;border-radius:4px">{status_emoji} {overall} — {passed}/{total} passed</div>
  </div>
  <div style="padding:20px 24px">
    <table width="100%" style="border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#dbeeff">
        <th style="padding:8px;text-align:left">TC</th>
        <th style="padding:8px;text-align:left">Activity</th>
        <th style="padding:8px;text-align:left">Sig ID</th>
        <th style="padding:8px;text-align:left">CASB Block Popup</th>
        <th style="padding:8px;text-align:left">Activity Blocked</th>
        <th style="padding:8px;text-align:left">Fast Log Signature</th>
        <th style="padding:8px;text-align:left">False Sig ID Hits</th>
        <th style="padding:8px;text-align:left">Result</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <div style="padding:12px 24px;background:#f5f5f5;text-align:center;font-size:11px;color:#999">
    Sent from CASB Results Dashboard · {run_id}
  </div>
</div>
</body></html>"""

        msg = MIMEMultipart("mixed")
        msg["From"]    = _cfg.SENDER_EMAIL
        msg["To"]      = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Attach zip
        try:
            tmp = tempfile.mktemp(suffix=".zip")
            with _zipfile.ZipFile(tmp, "w", _zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(run_dir):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        arc_name = os.path.join(run_id, os.path.relpath(abs_path, run_dir))
                        zf.write(abs_path, arc_name)
            with open(tmp, "rb") as f:
                part = MIMEBase("application", "zip")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            zip_name = f"CASB_Report_{run_id}.zip"
            part.add_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            msg.attach(part)
        except Exception as e:
            pass  # Send without attachment if zip fails

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(_cfg.SENDER_EMAIL, _cfg.SENDER_GMAIL_APP_PASSWORD)
            server.sendmail(_cfg.SENDER_EMAIL, recipients, msg.as_string())

        return jsonify({"status": "ok", "sent_to": recipients}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sig_lines/<run_id>/<sig_id>")
def api_sig_lines(run_id, sig_id):
    """Return fast.log lines matching a specific sig ID for a run."""
    import re as _re
    run_id = secure_filename(run_id)
    data   = _load_run(run_id)
    if not data:
        return jsonify({"error": "Run not found"}), 404

    results     = data.get("results", [])
    matched     = []
    non_matched = []

    for r in results:
        for line in r.get("fast_log_matches", []):
            if sig_id in line and line not in matched:
                matched.append(line)
        for line in r.get("fast_log_all_lines", []):
            if sig_id in line and line not in matched and line not in non_matched:
                non_matched.append(line)

    lines = matched if matched else non_matched
    return jsonify({"sig_id": sig_id, "lines": lines, "count": len(lines)})


@app.route("/api/runs")
def api_runs():
    return jsonify(_all_runs())


if __name__ == "__main__":
    print("=" * 55)
    print("  CASB Results Server")
    print("  http://0.0.0.0:4012/")
    print("  Results stored in:", os.path.abspath(RESULTS_DIR))
    print("=" * 55)
    app.run(host="0.0.0.0", port=4012, debug=False)
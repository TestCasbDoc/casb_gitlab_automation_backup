# CASB Results Server

Flask web server for storing and viewing MS Teams CASB Block Verification run results.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Server runs at: http://0.0.0.0:4012/

## Features

- All runs list with Pass/Fail/Trigger% stats
- Per-run TC breakdown: Sig IDs, CASB Block, Not Delivered, fast.log
- Download full ZIP of any run
- View the HTML report inline
- Download VOS dumps, HAR files, screenshots per run
- Delete old runs
- REST API for auto-upload from the automation script

## Auto-upload from automation script

Add this to the end of ms_teams_personal_send_post.py after generate_html_report():

```python
import requests, zipfile, tempfile, os

def upload_to_server(run_folder, server="http://SERVER_IP:4012"):
    tmp = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        run_name = os.path.basename(run_folder)
        for root, dirs, files in os.walk(run_folder):
            for file in files:
                abs_path = os.path.join(root, file)
                arc_name = os.path.join(run_name, os.path.relpath(abs_path, run_folder))
                zf.write(abs_path, arc_name)
    with open(tmp, "rb") as f:
        r = requests.post(f"{server}/api/upload", files={"file": (run_name+".zip", f)})
    print(f"[UPLOAD] {r.json()}")
    os.remove(tmp)

upload_to_server(SCRIPT_DIR)
```

Replace SERVER_IP with the IP of the machine running this server.

## API

POST /api/upload     — Upload a run zip (used by automation script)
GET  /api/runs       — JSON list of all runs

## Directory structure

casb_server/
  app.py              — Flask server
  requirements.txt    — Dependencies
  results/            — Run folders stored here (auto-created)
    run_YYYYMMDD_HHMMSS/
      test_report.json
      test_report.html
      vos_dumps/
      har_files/
      *.png

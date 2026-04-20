# CASB Automation Framework

Automated CASB block verification framework for Versa SASE.
Tests that MS Teams (and future apps) are correctly blocked by CASB policy.

Built with: Playwright · Paramiko · pywinauto · Flask

---

## Folder Structure

```
casb_new_structure/
├── run.py                          ← Entry point. Add 1 line here per new app.
├── config.py                       ← All credentials, SSH settings, VOS config.
├── debug_casb_block_alert_popup_finder.py  ← Debug tool for popup detection.
├── core/
│   ├── base_activity.py            ← Base class for all app activities.
│   ├── browser_handler.py          ← Browser helpers (tabs, screenshots, HAR).
│   ├── runner.py                   ← Generic test orchestrator.
│   ├── versa_handler.py            ← CASB popup + SSH fast.log capture.
│   ├── vos_info_dump.py            ← VOS SSH commands (clear, dump, qosmos).
│   ├── decryption_check.py         ← TLS inspection verification.
│   └── report_generator.py         ← JSON + HTML report generation.
└── apps/
    └── ms_teams/
        ├── app.yaml                ← App definition (keywords, activities).
        ├── activities.py           ← MS Teams UI automation (TC1-TC4).
        └── login_handler.py        ← MS Teams login flow.
```

---

## Setup & Installation

### Option 1 — Virtual Environment (Recommended)

**Windows:**
```powershell
setup_venv.bat
```

**Linux:**
```bash
chmod +x setup_venv.sh && ./setup_venv.sh
```

This will:
- Create a `.venv` virtual environment
- Install all dependencies from `requirements.txt`
- Install Playwright Chromium browser
- Install `casb-automation` as a CLI command

### Option 2 — Manual Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
pip install -e .
```

---

## Activating the Virtual Environment

**Windows (PowerShell):**
```powershell
.venv\Scripts\activate
```
> **If you see `UnauthorizedAccess` error**, PowerShell execution policy is blocking the script.
> Run this once to enable it:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Run the below activate command again:
**Windows (PowerShell):**
```powershell
.venv\Scripts\activate
```




---

## Running as CLI Tool

After activating the virtual environment, use `casb-automation` directly:

**Windows:**
```powershell
casb-automation --applications "MS_Teams" --account_type personal --host 172.20.4.5 --pwd versa123 --ssh-user admin --activities "post"
```

**Linux:**
```bash
casb-automation --applications "MS_Teams" --account_type personal --host 172.20.4.5 --pwd versa123 --ssh-user admin --activities "post"
```

---

## Building a Standalone Binary (Optional)

Use PyInstaller to create a single executable — no Python needed on target machine.

**Windows → `dist/casb-automation.exe`:**
```powershell
build.bat
```

**Linux → `dist/casb-automation`:**
```bash
chmod +x build.sh && ./build.sh
```

> **Note:** Playwright Chromium must still be installed on the target machine:
> `playwright install chromium`

---

## How to Run

```bash
python run.py
  --applications "MS_Teams"
  --account_type personal
  --host 172.20.4.5
  --pwd versa123
  --ssh-user admin
  --org "ENDTOEND-Tenant-2"
  --access-policy "Default-Policy"
  --decrypt-policy "Default-Policy"
  --decrypt-rule "decryption_rule_casb"
  --decrypt-profile "decrypt_profile"
  --casb-profile "casb_mobile_test_rule"
  --casb-access-policy-rule "mobile_test_rule"
  --report-dir "C:\Users\admin\Downloads\CASB_Reports"
  --qosmos True
  --send-email "user1@versa-networks.com,user2@versa-networks.com"
  --activities "post"
  --server-url "http://10.196.3.26:4012"
```

### Arguments

| Argument | Purpose | Example |
|---|---|---|
| `--applications` | Comma-separated apps | `MS_Teams` / `MS_Teams,Instagram` |
| `--account_type` | Account type(s) | `personal` / `corporate` / `personal,corporate` |
| `--host` | VOS branch IP | `172.20.4.5` |
| `--pwd` | SSH password | `versa123` |
| `--ssh-user` | SSH username | `admin` |
| `--org` | VOS org name | `ENDTOEND-Tenant-2` |
| `--activities` | TCs to run | see below |
| `--qosmos` | appid report_metadata | `True` / `False` |
| `--report-dir` | Report output folder | `C:\Users\admin\Downloads\CASB_Reports` |
| `--server-url` | CASB Results dashboard URL | `http://10.196.3.26:4012` |
| `--send-email` | Email report recipients | `a@versa.com,b@versa.com` |
| `--access-policy` | VOS access policy name | `Default-Policy` |
| `--decrypt-policy` | VOS decryption policy name | `Default-Policy` |
| `--decrypt-rule` | VOS decryption rule name | `decryption_rule_casb` |
| `--decrypt-profile` | VOS decryption profile name | `decrypt_profile` |
| `--casb-profile` | VOS CASB profile name | `casb_mobile_test_rule` |
| `--casb-access-policy-rule` | VOS CASB rule name | `mobile_test_rule` |

### --activities combos

```
all                      -> run all activities and all TCs
post                     -> run all post TCs (TC1, TC2, TC3, TC4)
post[1]                  -> run TC1 only
post[2]                  -> run TC2 only
post[3]                  -> run TC3 only
post[4]                  -> run TC4 only
post[1,2]                -> run TC1 and TC2
post[1,2,3]              -> run TC1, TC2 and TC3
post[1,2,3,4]            -> run all 4 TCs explicitly
post[2,4]                -> run TC2 and TC4 (any combo works)
"post[1,3] share[1,4]"  -> run post TC1,TC3 AND share TC1,TC4
"post share"             -> run all TCs for both post and share
```

---

## Adding a New App

Only 3 things needed — core framework is never touched.

**Step 1 — Create `apps/{app_id}/app.yaml`**
```yaml
name: Instagram
app_id: instagram
app_url: https://www.instagram.com
log_match:
  keywords: [instagram, post, app-activity for casb]
expected:
  application: instagram
  activity: post
  blocked_by: casb
activities:
  post:
    tc_label: TC1
    category: post
    nav: "Home -> New Post -> Share"
```

**Step 2 — Create `apps/{app_id}/activities.py`**
```python
from core.base_activity import BaseActivity

class InstagramActivity(BaseActivity):
    def _open_fresh_tab(self): ...
    def _wait_for_app(self, page): ...
    def _do_post(self, page, result, **kwargs):
        vsmd, har = self._before_send(page, "TC1")
        # ... UI clicks only ...
        self._after_send(page, result, vsmd, har, "TC1", None)
```

**Step 3 — Add 1 line to `run.py`**
```python
_APP_MAP = {
    "ms_teams" : ["personal", "corporate"],
    "instagram": ["any"],   # <- this line
}
```

Then run:
```bash
python run.py --applications "Instagram" --host 172.20.4.5 --pwd versa123 --ssh-user admin
```

---

## Debug — CASB Popup Window Finder

When setting up a **new app** or on a **new machine**, run this tool first to identify
the exact Versa CASB AlertWindow title and class name.

```bash
python debug_casb_block_alert_popup_finder.py
```

**Steps:**
1. Run the script — it captures a baseline of all open windows
2. Go to your app and manually perform the activity that CASB should block
3. Script detects and prints any new windows that appear
4. Look for the window marked `<- CASB POPUP (use this)` in the output

**Example output:**
```
[15s] *** NEW WINDOW(S) DETECTED ***
   TITLE   : 'AlertWindow'  <- CASB POPUP (use this)
   CLASS   : 'HwndWrapper[VersaSecureAccessClient.Alerts.exe;;...]'
   BACKEND : win32

   TITLE   : 'MediaContextNotificationWindow'  <- noise (ignore)
   TITLE   : 'SystemResourceNotifyWindow'  <- noise (ignore)
```

Works for **any app, any activity** — you trigger the block manually.

---

## Results Dashboard

Accessible at: **http://10.196.3.26:4012**

- View all runs with Pass/Fail, TC count, Trigger %, Sig IDs
- Per-TC breakdown — CASB Block, Not Delivered, fast.log, fail reasons
- Download ZIP, view HTML report, browse VOS dumps, HAR files, screenshots
- Auto-upload via `--server-url` flag — no manual steps needed

---

## Git Workflow

### Branches
```
main              <- stable, tested code only
├── amruta/apps   <- Amruta's work
├── lisari/apps   <- Lisari's work
├── lankesh/apps  <- Lankesh's work
└── hrutuja/apps  <- Hrutuja's work
```

### First time setup
```bash
git clone https://github.com/TestCasbDoc/casb-automation.git
cd casb-automation
git checkout lankesh/apps    # use your own branch name
```

### Daily workflow
```bash
# Before starting — get latest
git pull

# After making changes — save to GitHub
git add .
git commit -m "describe what you changed"
git push
```

### Rules
- Always `git pull` before starting work
- Only work on your own branch
- Never push directly to `main`
- When your app is ready -> raise a Pull Request to merge into `main`
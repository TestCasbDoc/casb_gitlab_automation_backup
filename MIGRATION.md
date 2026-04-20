# Migration Guide — Old Structure → New Structure

## New folder structure

```
casb_automation/
├── core/                        ← framework (never edit when adding apps)
│   ├── __init__.py              ← NEW (empty)
│   ├── base_activity.py         ← NEW
│   ├── browser_handler.py       ← NEW
│   ├── runner.py                ← NEW
│   ├── versa_handler.py         ← MOVE from root (no changes needed)
│   ├── vos_info_dump.py         ← MOVE from root (no changes needed)
│   ├── decryption_check.py      ← MOVE from root (no changes needed)
│   └── report_generator.py      ← MOVE from root (no changes needed)
│
├── apps/
│   ├── __init__.py              ← NEW (empty)
│   └── ms_teams/
│       ├── __init__.py          ← NEW (empty)
│       ├── app.yaml             ← NEW
│       ├── activities.py        ← NEW (replaces teams_activities.py)
│       └── login_handler.py     ← MOVE login_handler.py from root here
│
├── config.py                    ← UNCHANGED (stays at root)
└── run.py                       ← REPLACED with new version
```

## Step-by-step migration

### Step 1 — Create new folders
```
mkdir core
mkdir apps
mkdir apps\ms_teams
```

### Step 2 — Move core files (no changes needed inside them)
```
move versa_handler.py     core\versa_handler.py
move vos_info_dump.py     core\vos_info_dump.py
move decryption_check.py  core\decryption_check.py
move report_generator.py  core\report_generator.py
move login_handler.py     apps\ms_teams\login_handler.py
```

### Step 3 — Update imports in moved core files
In each moved file, change imports from:
```python
from versa_handler import ...
from vos_info_dump import ...
import config
```
To:
```python
from core.versa_handler import ...
from core.vos_info_dump import ...
import config
```

Or add this at the top of each file (simpler approach):
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```
This adds the project root to the path so `import config` etc. keep working unchanged.

### Step 4 — Place new files
Copy these new files from this package:
```
core\__init__.py
core\base_activity.py
core\browser_handler.py
core\runner.py
apps\__init__.py
apps\ms_teams\__init__.py
apps\ms_teams\app.yaml
apps\ms_teams\activities.py
run.py   ← replace existing
```

### Step 5 — Update login_handler.py
The login_handler at `apps/ms_teams/login_handler.py` needs to expose a `login(browser, account_type, cfg)` function.

Wrap the existing `navigate_to_teams_chat` call in:
```python
def login(browser, account_type, cfg):
    page = browser.pages[0] if browser.pages else browser.new_page()
    navigate_to_teams_chat(page, cfg.SENDER_EMAIL, cfg.SENDER_PASSWORD)
```

### Step 6 — Test with a single TC
```
python run.py --applications "MS_Teams[personal]" --host 172.20.4.5 --pwd versa123 --ssh-user admin --activities "post[1]"
```

### Step 7 — Delete old files (after confirming all TCs pass)
```
del ms_teams_personal_send_post.py
del ms_teams_corporate_send_post.py
del teams_activities.py
del teams_handler.py
```

---

## Adding a new app (e.g. Instagram) after migration

1. Create `apps/instagram/app.yaml`  — describe keywords, activities
2. Create `apps/instagram/activities.py`  — subclass BaseActivity, UI only
3. Add one line to `run.py`:
   ```python
   _APP_MAP = {
       "ms_teams" : ["personal", "corporate"],
       "instagram": ["any"],   # ← this line
   }
   ```
4. Run:
   ```
   python run.py --applications "Instagram" --host ... --pwd ... --ssh-user ...
   ```

**Files modified: 1. Files created: 2. Core framework: untouched.**

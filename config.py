"""
config.py — All test configuration settings.
Updated: March 17, 2026
"""

import os
from datetime import datetime

# ------------------------------------------------------------
# TEST CONFIGURATION
# ------------------------------------------------------------
RECIPIENTS = ["Casb Automation2"]
MESSAGE = f"Hi from CASB Test Automation {datetime.now().strftime('%Y%m%d_%H%M%S')}"

EXPECTED_APPLICATION = "ms_teams"
EXPECTED_ACTIVITY    = "post"
EXPECTED_BLOCKED_BY  = "casb"
SCRIPT_DIR  = r"C:\Users\admin\Downloads\CASB_Reports"
os.makedirs(SCRIPT_DIR, exist_ok=True)
BASE_DIR    = r"C:\Users\admin\Downloads\CASB_Reports"
RUN_FOLDER  = datetime.now().strftime("run_%Y%m%d_%H%M%S")
SCRIPT_DIR  = os.path.join(BASE_DIR, RUN_FOLDER)
os.makedirs(SCRIPT_DIR, exist_ok=True)
REPORT_FILE = os.path.join(SCRIPT_DIR, "test_report.json")
HTML_REPORT = os.path.join(SCRIPT_DIR, "test_report.html")

WAIT_BETWEEN_RECIPIENTS = 30
SSH_REQUIRED_FOR_PASS = True

# ------------------------------------------------------------
# CASB POPUP VALIDATION TIMEOUTS
# ------------------------------------------------------------
CASB_POPUP_WAIT_TIMEOUT = 180
CASB_POPUP_DISAPPEAR_TIMEOUT = 180

# ------------------------------------------------------------
# CREDENTIALS (SIMPLE — NO .ENV FILE)
# ------------------------------------------------------------
SENDER_EMAIL = "casbautomation1@gmail.com"
SENDER_PASSWORD = "Casb@Auto123"
SENDER_GMAIL_APP_PASSWORD = "gszk fref fuum wrpn"  # Your 16-char Gmail App Password

RECIPIENT_CREDENTIALS = {
    "Casb Automation2": {
        "email"      : "casbautomation2@gmail.com",
        "password"   : "Casb@Auto321",
        "profile_dir": r"C:\Users\admin\AppData\Local\Temp\pw_recipient_casb2",
        "sender_name": "Casb Automation1",
    },
}

SENDER_PROFILE_DIR = r"C:\Users\admin\AppData\Local\Temp\pw_sender_casb1"
RECIPIENT_CHECK_TIMEOUT = 5

# ------------------------------------------------------------
# SSH / FAST.LOG CONFIGURATION
# ------------------------------------------------------------
SSH_HOST     = "172.20.4.5"
SSH_PORT     = 22
SSH_USER     = "admin"
SSH_PASSWORD = "versa123"
SSH_KEY_PATH = None
FAST_LOG     = "/var/log/versa/idp/fast.log"

LOG_MATCH_KEYWORDS = ["ms_teams", "post", "app-activity for casb"]

# ------------------------------------------------------------
# VOS BRANCH CONFIGURATION
# ------------------------------------------------------------
VOS_ORG_NAME            = "ENDTOEND-Tenant-2"
VOS_ACCESS_POLICY_NAME  = "Default-Policy"
VOS_DECRYPTION_POLICY_NAME = "Default-Policy"
VOS_DECRYPTION_RULE_NAME   = "decryption_rule_casb"
VOS_DECRYPT_PROFILE_NAME   = "decrypt_profile"
VOS_CASB_PROFILE_NAME      = "casb_mobile_test_rule"
VOS_CASB_RULE_NAME         = "mobile_test_rule"

# ------------------------------------------------------------
# APPID REPORT METADATA CONFIGURATION
# ------------------------------------------------------------
VOS_APPID_REPORT_METADATA = "disable"

# ------------------------------------------------------------
# TLS DECRYPTION CHECK CONFIGURATION
# ------------------------------------------------------------
DECRYPTION_CHECK_URL          = "https://teams.live.com"
DECRYPTION_ISSUER_CN_KEYWORD  = "VOS Certificate"
DECRYPTION_REQUIRED_FOR_PASS  = True

# ------------------------------------------------------------
# REPORT DATA (populated at runtime)
# ------------------------------------------------------------
REPORT_DATA = {
    "run_timestamp": "",
    "run_status"   : "UNKNOWN",
    "config"       : {},
    "step_decryption": {},
    "step_vos_clear" : {},
    "step_vos_dump"  : {},
    "step_cli"     : {},
    "recipients"   : [],
}

_recipient_browsers = {}


# ------------------------------------------------------------
# CREDENTIAL LOOKUP
# ------------------------------------------------------------
def get_recipient_creds(recipient_name):
    """Get recipient credentials by name (case-insensitive lookup)."""
    if recipient_name in RECIPIENT_CREDENTIALS:
        return RECIPIENT_CREDENTIALS[recipient_name]
    for key, val in RECIPIENT_CREDENTIALS.items():
        if key.lower() == recipient_name.lower():
            return val
    return None
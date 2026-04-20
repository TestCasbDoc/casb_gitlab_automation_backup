"""
Instagram app package.

For Instagram runs we want fast.log validation to look for the
current EXPECTED_APPLICATION / EXPECTED_ACTIVITY instead of the
hard-coded ms_teams/post defaults used by FastLogCapture.

We override FastLogCapture._is_match here so that when Instagram
is loaded, subsequent log validation uses the dynamic values from
config.py. Other apps continue to work as before.
"""

from core import versa_handler as _vh
import config as _cfg


def _instagram_is_match(self, line: str) -> bool:
    low = line.lower()
    app = getattr(_cfg, "EXPECTED_APPLICATION", "ms_teams").lower()
    act = getattr(_cfg, "EXPECTED_ACTIVITY", "post").lower()
    return app in low and act in low and "app-activity for casb" in low


_vh.FastLogCapture._is_match = _instagram_is_match

"""
apps/instagram/activities.py — Case 2 (account_types: [any]).

Auto-discovers activity_*.py mixins (activity_post, activity_share, activity_upload, …)
and merges them into InstagramActivity — same pattern as MS Teams (one file per category group).

CASB `EXPECTED_ACTIVITY` is set from app.yaml `category` via activity_common.py (no per-TC
expected_activity keys in YAML).
"""

import glob
import importlib.util
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.base_activity import BaseActivity
from apps.instagram.login_handler import BrowserMixin


def _discover_mixins():
    mixins = []
    for path in sorted(glob.glob(os.path.join(_HERE, "activity_*.py"))):
        mod_name = os.path.splitext(os.path.basename(path))[0]
        full_name = f"apps.instagram.{mod_name}"
        spec = importlib.util.spec_from_file_location(full_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        for attr_name in sorted(dir(mod)):
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and attr_name.endswith("Mixin"):
                mixins.append(obj)
                print(f"   [instagram] loaded mixin: {attr_name} <- {mod_name}.py")
    return mixins


class InstagramActivityBase(BaseActivity):
    """
    Same as BaseActivity.run_activity, plus:
      - preflight (upload assets) after app load, before SSH log capture
      - passes tc_label into kwargs for _do_* methods
    """

    def run_activity(self, activity_name: str, tc_label: str, **kwargs):
        import config as _cfg
        from apps.instagram import navigations as nav

        result = self._make_result(activity_name, tc_label)

        pre_clear = kwargs.pop("pre_clear_result", None)
        if pre_clear is not None:
            self._add_pre_clear_steps(result, pre_clear, tc_label)

        page = self._open_fresh_tab()
        if not self._wait_for_app(page):
            result["fail_reason"].append(f"{self.app_name} did not load in browser")
            self._register_to_report(result)
            return result, None

        try:
            nav.preflight_activity(activity_name)
        except Exception as ex:
            err = f"preflight: {ex}"
            print(f"   [SKIP TC] {err}")
            result["fail_reason"].append(err)
            self._register_to_report(result)
            return result, None

        kwargs["tc_label"] = tc_label

        self._apply_category_log_match(activity_name)
        self._sync_config_expected_from_app()

        cap = self._start_log_capture()
        self._add_step(
            result,
            f"{tc_label}-a",
            "SSH Log Capture Started",
            "pass" if cap._connected else "warn",
            [
                f"Target   : {_cfg.SSH_USER}@{_cfg.SSH_HOST}:{_cfg.SSH_PORT}",
                f"Log file : {_cfg.FAST_LOG}",
                f"Keywords : {self.keywords}",
                f"Connected: {'Yes' if cap._connected else 'No — ' + str(cap._error)}",
            ],
        )

        method = getattr(self, f"_do_{activity_name}", None)
        if method is None:
            result["fail_reason"].append(
                f"Activity '{activity_name}' not implemented in {self.__class__.__name__}"
            )
            cap.stop()
            self._register_to_report(result)
            return result, None

        send_attempted = method(page, result, **kwargs)

        poller = result.pop("_poller", None)
        poller_label = result.pop("_poller_label", tc_label)
        session_thread = result.pop("_session_thread", None)

        if send_attempted:
            self._wait_casb_popup(page, result, tag=tc_label)
            # Instagram UI validation runs after AlertWindow is gone (toast at bottom can lag)
            from apps.instagram import ui_validators as _ui

            _ui.run_ui_validator(activity_name, page, result, tc_label, self)
            time.sleep(5)

        if poller:
            from core.vos_info_dump import _append_session_output
            from datetime import datetime as _dt

            _, sess_hdl, attempts, session_lines = poller["get_result"](join_timeout=60)
            print(f"   [SESSION-INFO] Poller result: sess_hdl={sess_hdl}, attempts={attempts}")
            if session_lines:
                _append_session_output(poller_label, session_lines)
            else:
                _append_session_output(
                    poller_label,
                    [
                        "",
                        "=" * 70,
                        "  SESSION INFO — not captured",
                        f"  Timestamp : {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        "=" * 70,
                        "",
                        f"sess_hdl = 0 after {attempts} poll attempt(s)",
                    ],
                )

        self._finish_log_capture(cap, result, f"{tc_label}-log")

        result["status"] = "PASS" if not result["fail_reason"] else "FAIL"

        self._register_to_report(result)
        return result, session_thread


_mixins = _discover_mixins()

InstagramActivity = type(
    "InstagramActivity",
    tuple(_mixins + [BrowserMixin, InstagramActivityBase]),
    {"__doc__": "Instagram CASB — Case 2 (account_types: any)."},
)

"""
apps/ms_teams_personal/activities.py
Auto-discovers activity_*.py mixin files and builds MsTeamsPersonalActivity.
"""

import os
import glob
import importlib.util
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.base_activity import BaseActivity
from apps.ms_teams_personal.login_handler import BrowserMixin


def _discover_mixins():
    mixins = []
    for path in sorted(glob.glob(os.path.join(_HERE, "activity_*.py"))):
        mod_name = os.path.splitext(os.path.basename(path))[0]
        full_name = f"apps.ms_teams_personal.{mod_name}"
        spec = importlib.util.spec_from_file_location(full_name, path)
        mod  = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        for attr_name in sorted(dir(mod)):
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and attr_name.endswith("Mixin"):
                mixins.append(obj)
                print(f"   [ms_teams_personal] loaded mixin: {attr_name} <- {mod_name}.py")
    return mixins


_mixins = _discover_mixins()

# Class name must match app_id convention: ms_teams_personal -> MsTeamsPersonalActivity
MsTeamsPersonalActivity = type(
    "MsTeamsPersonalActivity",
    tuple(_mixins + [BrowserMixin, BaseActivity]),
    {"__doc__": "MS Teams Personal CASB activity handler."},
)
"""
Shared Instagram navigation runner and CASB popup `EXPECTED_ACTIVITY` handling.

Same idea as MS Teams: each activity row in app.yaml has a `category`; that maps to the
Versa AlertWindow activity string — no per-TC `expected_activity` in YAML.
"""

try:
    import config as _cfg
except Exception:  # pragma: no cover
    _cfg = None

from apps.instagram import navigations as nav

# app.yaml `category` → config.EXPECTED_ACTIVITY (Versa / fast.log alignment)
_CATEGORY_TO_EXPECTED_ACTIVITY = {
    "post": "post",
    "share": "share",
    "upload": "upload_file",
    "profile_picture": "upload_file",
    "delete": "delete",
    "edit": "edit",
    "like": "like",
    "logout": "logout",
}


def apply_expected_activity_for_category(self, activity_name: str) -> None:
    """Set _cfg EXPECTED_* from app.yaml ``categories`` when present, else legacy map."""
    if _cfg is None:
        return
    meta = (self.app_config.get("activities") or {}).get(activity_name) or {}
    cat = (meta.get("category") or "").strip().lower()
    cats = self.app_config.get("categories") or {}
    if cat in cats:
        yexp = cats[cat].get("expected") or {}
        if yexp.get("application"):
            _cfg.EXPECTED_APPLICATION = yexp["application"]
        if yexp.get("activity"):
            _cfg.EXPECTED_ACTIVITY = yexp["activity"]
        if yexp.get("blocked_by"):
            _cfg.EXPECTED_BLOCKED_BY = yexp["blocked_by"]
        print(
            f"   [CASB expect] category={cat!r} · "
            f"app={getattr(_cfg, 'EXPECTED_APPLICATION', '')!r} · "
            f"activity={getattr(_cfg, 'EXPECTED_ACTIVITY', '')!r} ({activity_name})"
        )
        return
    exp = _CATEGORY_TO_EXPECTED_ACTIVITY.get(cat)
    if exp is None:
        exp = (self.app_config.get("expected") or {}).get("activity", "post")
    _cfg.EXPECTED_ACTIVITY = exp
    print(
        f"   [CASB expect] activity={exp!r} (category={cat or '—'} · {activity_name})"
    )


def insta_run(self, page, result, kwargs, activity_name, nav_fn):
    """Run navigation + HAR after applying expected activity from category."""
    apply_expected_activity_for_category(self, activity_name)
    tc_label = kwargs.get("tc_label", "TC")
    vsmd_prep, har = self._before_send(page, tc_label)
    try:
        if activity_name == "change_profile_picture":
            nav.change_profile_picture(page, result)
        elif activity_name == "delete_chat":
            nav.delete_chat(page, result)
        elif activity_name == "delete_comment_home":
            nav.delete_comment_home(page, result)
        elif activity_name == "delete_comment_own_post":
            nav.delete_comment_own_post(page, result)
        elif activity_name == "delete_group_chat":
            nav.delete_group_chat(page, result)
        elif activity_name == "delete_note_messages":
            nav.delete_note_messages(page, result)
        elif activity_name == "delete_own_post":
            nav.delete_own_post(page, result)
        elif activity_name == "delete_own_story":
            nav.delete_own_story(page, result)
        elif activity_name == "edit_highlight":
            nav.edit_highlight(page, result)
        elif activity_name == "edit_own_post":
            nav.edit_own_post(page, result)
        elif activity_name in (
            "like_comment",
            "like_message",
            "like_own_post",
            "like_post_home",
            "like_post_search",
            "like_reel_explore",
            "like_saved_post",
            "like_story_home",
        ):
            getattr(nav, activity_name)(page, result)
        elif activity_name in (
            "share_image_messages",
            "share_note_messages",
            "share_story",
            "upload_image_messages",
        ):
            getattr(nav, activity_name)(page, result)
        elif activity_name == "logout":
            nav.logout(page, result)
        else:
            nav_fn(page)
    except Exception as ex:
        print(f"   [NAVIGATION ERROR] {activity_name}: {ex}")
        result["fail_reason"].append(f"{activity_name}: {ex}")
        try:
            har.stop()
        except Exception:
            pass
        return False
    self._after_send(page, result, vsmd_prep, har, tc_label, None)
    return True

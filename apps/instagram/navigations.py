"""
Instagram CASB activity functions - All navigations (7-39).
Uses SVG aria-label selectors (icon-only sidebar).
Uses expect_file_chooser() for file uploads.
Test media: put any real images/video under uploads/ (see TEST_* names below).
  Each file must be >= 1 KB. Content can be stock photos, short MP4s, etc.
"""
__author__ = "Lisari"
import os
import re
import time
from typing import Tuple

from playwright.sync_api import Page

import config as _cfg


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(SCRIPT_DIR, "uploads")

# Fixed names so you can drop in any suitable files (rename after download).
TEST_IMAGE_1 = os.path.join(UPLOADS_DIR, "test_image_1.jpg")
TEST_IMAGE_2 = os.path.join(UPLOADS_DIR, "test_image_2.jpg")
TEST_VIDEO = os.path.join(UPLOADS_DIR, "test_video.mp4")

# TC25 share_story: prefer options whose text matches this (e.g. "Carlos Sainz" vs carlossainz).
_STORY_DM_RECIPIENT_REGEX = (
    r"therealissmess|thereallissmess|liss|casb|carlos\s*sainz|carlossainz|automation|test\.user"
)

# Story tray: generic labels that are never another user's story (not account-specific).
_STORY_TRAY_GENERIC_SKIP = re.compile(
    r"your\s+story|add\s+(a\s+)?story|^\s*new\s+story|create\s+story",
    re.I,
)

# Optional: logged-in IG handle (no @) — skip that user's \"…'s profile picture\" ring.
# Env INSTAGRAM_LOGGED_IN_USERNAME overrides this when set (Instagram-only; not in shared config.py).
_STORY_TRAY_SKIP_HANDLE = ""


def _story_tray_logged_in_handle() -> str:
    return (
        os.environ.get("INSTAGRAM_LOGGED_IN_USERNAME", "") or _STORY_TRAY_SKIP_HANDLE or ""
    ).strip().lstrip("@")


def _story_tray_skip_profile_picture_label(label: str) -> bool:
    """Skip tray rings that are Add/Your story, or optional logged-in handle (see above)."""
    if not (label or "").strip():
        return False
    if _STORY_TRAY_GENERIC_SKIP.search(label):
        return True
    h = _story_tray_logged_in_handle().lower()
    if not h:
        return False
    return h in label.lower()


# ---------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------
def _check_test_files():
    for path in [TEST_IMAGE_1, TEST_IMAGE_2, TEST_VIDEO]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing: {path}")
        if os.path.getsize(path) < 1024:
            raise ValueError(f"Too small (<1KB): {path}")


# Activities that call _check_test_files() — must run preflight before SSH tail (fail fast).
_UPLOAD_ASSET_ACTIVITIES = frozenset(
    {
        "post_image",
        "post_video",
        "post_multiple_images",
        "change_profile_picture",
        "upload_image_messages",
        "share_image_messages",
    }
)


def preflight_activity(activity_name: str) -> None:
    """Raise before log capture if this TC needs upload files that are missing (Windows/RDP friendly path in error)."""
    if activity_name in _UPLOAD_ASSET_ACTIVITIES:
        _check_test_files()


def _dismiss_popups(page: Page):
    for text in ["Not Now", "Not now", "Close", "Cancel", "Decline",
                 "No Thanks", "Discard", "Save Info",
                 "Allow all cookies", "Allow essential and optional cookies"]:
        try:
            btn = page.get_by_role("button", name=text)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass


def _nav(page: Page, url: str):
    """Navigate to a URL, wait for load, dismiss popups."""
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    _dismiss_popups(page)
    page.wait_for_timeout(1000)


def _go_home(page: Page):
    _nav(page, "https://www.instagram.com/")


def _go_profile(page: Page):
    _nav(page, "https://www.instagram.com/casb.test3/")


def _go_messages(page: Page):
    _nav(page, "https://www.instagram.com/direct/inbox/")


def _go_saved_collection(page: Page) -> None:
    """
    Open Saved via sidebar (Playwright-recorded flow): More → Saved.
    Uses flexible name patterns ("Settings More", "Saved Saved") and falls back to /saved/ URL.
    """
    _go_home(page)
    page.wait_for_timeout(2000)
    try:
        page.get_by_role("link", name=re.compile(r"settings\s+more", re.I)).first.click(
            timeout=15000
        )
        page.wait_for_timeout(1500)
    except Exception:
        try:
            _click_sidebar(page, "More")
            page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        page.get_by_role("link", name=re.compile(r"saved\s+saved|^saved$", re.I)).first.click(
            timeout=15000
        )
        page.wait_for_timeout(2500)
    except Exception:
        try:
            page.get_by_role("link", name=re.compile(r"\bsaved\b", re.I)).first.click(
                timeout=12000
            )
            page.wait_for_timeout(2500)
        except Exception:
            pass

    u = (page.url or "").lower()
    if "/saved" not in u:
        _nav(page, "https://www.instagram.com/casb.test3/saved/")


def _go_dm_chat(page: Page):
    _nav(page, "https://www.instagram.com/direct/t/17842019184172650/")


def dm_thread_message_count(page: Page) -> int:
    """
    Approximate number of DM thread items for before/after CASB checks.
    Instagram Web often does not use div[role='row'] in the open chat; try several patterns.
    """
    page.wait_for_timeout(1000)
    best = 0
    for sel in (
        "div[role='log'] div[role='row']",
        "main section div[role='row']",
        "main div[role='row']",
        "div[role='row']",
    ):
        try:
            n = page.locator(sel).count()
            if n > best:
                best = n
        except Exception:
            continue
    if best > 0:
        return best
    for sel in (
        "main [role='grid'] > div",
        "main article",
        "[role='log'] article",
    ):
        try:
            n = page.locator(sel).count()
            if 0 < n < 500:
                best = max(best, n)
        except Exception:
            continue
    return best


def _click_share_compose(page: Page):
    """Share button on post composer (caption screen); Instagram labels vary."""
    page.wait_for_timeout(2000)
    last_exc = None
    for _ in range(3):
        try:
            page.get_by_role("button", name=re.compile(r"^Share$", re.I)).click(
                timeout=20000
            )
            page.wait_for_timeout(5000)
            return
        except Exception as e:
            last_exc = e
        try:
            page.locator("div[role='dialog']").get_by_role(
                "button", name=re.compile(r"Share", re.I)
            ).last.click(timeout=15000)
            page.wait_for_timeout(5000)
            return
        except Exception as e:
            last_exc = e
        try:
            page.locator("svg[aria-label='Share']").last.click(timeout=15000)
            page.wait_for_timeout(5000)
            return
        except Exception as e:
            last_exc = e
        try:
            page.locator("div[role='button']").filter(
                has_text=re.compile(r"^Share$", re.I)
            ).last.click(timeout=15000)
            page.wait_for_timeout(5000)
            return
        except Exception as e:
            last_exc = e
        page.wait_for_timeout(1500)
    raise TimeoutError(f"Could not click Share on compose: {last_exc}")


def _dump_svg_labels(page: Page):
    labels = []
    svgs = page.locator("svg[aria-label]")
    for i in range(svgs.count()):
        try:
            labels.append(svgs.nth(i).get_attribute("aria-label"))
        except Exception:
            pass
    return labels


def _click_sidebar(page: Page, *labels):
    """Click a sidebar icon by SVG aria-label."""
    for label in labels:
        try:
            svg = page.locator(f"svg[aria-label='{label}']")
            if svg.count() > 0 and svg.first.is_visible():
                svg.first.click()
                return
        except Exception:
            continue
    all_labels = _dump_svg_labels(page)
    raise Exception(f"Sidebar not found. Tried: {labels}. Available: {all_labels}")


def _click_new_post(page: Page):
    """Click '+' Create in sidebar, then select 'Post' from sub-menu."""
    _click_sidebar(page, "New post", "Create", "New Post", "create")
    page.wait_for_timeout(1500)
    # Instagram now shows a sub-menu: Post, Reel, Story, etc.
    for name in ["Post Post", "Post"]:
        try:
            link = page.get_by_role("link", name=name)
            if link.count() > 0 and link.first.is_visible():
                link.first.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue
    # Sub-menu might not appear (older UI) — continue anyway


def _click_first_post(page: Page):
    """Click the first post or reel on any profile/grid page."""
    page.locator("a[href*='/p/'], a[href*='/reel/']").first.click()


def _ig_media_path_from_url(url: str) -> str:
    """Normalize /p/SHORTCODE/ or /reel/SHORTCODE/ from a full URL."""
    if not url:
        return ""
    m = re.search(r"(/p/[^/?#]+|/reel/[^/?#]+)", url)
    return m.group(1) if m else ""


def _open_first_post_from_profile_grid(page: Page, timeout_ms: int = 25000) -> None:
    """
    Open the first grid tile on a profile. Prefer /p/ or /reel/ links — `article a` is brittle on
    current Instagram (grid may not wrap links in article).
    """
    page.wait_for_timeout(1500)
    try:
        page.get_by_role("tab", name=re.compile(r"^\s*posts\s*$", re.I)).click(timeout=5000)
        page.wait_for_timeout(2000)
    except Exception:
        try:
            page.get_by_role("link", name=re.compile(r"posts", re.I)).first.click(timeout=3000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    loc = page.locator("a[href*='/p/'], a[href*='/reel/']").first
    loc.wait_for(state="visible", timeout=timeout_ms)
    loc.click()


def _story_viewer_opened(page: Page) -> bool:
    try:
        u = page.url or ""
    except Exception:
        u = ""
    return "/stories/" in u


def _wait_story_viewer_ready(page: Page, timeout_ms: int = 35000) -> None:
    """Ensure we left the home feed and story chrome can render before tapping share/Direct."""
    try:
        page.wait_for_url(re.compile(r".*instagram\.com/.*stories.*"), timeout=timeout_ms)
    except Exception:
        pass
    if not _story_viewer_opened(page):
        raise TimeoutError(
            "Story viewer did not open (URL has no /stories/). "
            "Open any story from the home tray, or check login/story tray visibility."
        )
    page.wait_for_timeout(4000)


def _click_story_direct_for_dm(page: Page) -> None:
    """
    Story viewer: open **Direct** (paper plane) to forward the **story** to a DM recipient.

    Do **not** use the generic **Share** control here — that opens Instagram's share sheet
    (add post to your story, copy link, etc.) and is a different activity than forwarding
    the current story via DM. CASB policy / Versa activity for TC25 expects the Direct flow.
    """
    page.wait_for_timeout(1500)
    last_exc = None
    # Direct / paper-plane only — no Share / hare / repost fallbacks.
    for factory in (
        lambda: page.get_by_role("button", name=re.compile(r"^direct$", re.I)).first,
        lambda: page.get_by_role("button", name=re.compile(r"\bdirect\b", re.I)).first,
        lambda: page.locator("header").get_by_role("button", name=re.compile(r"direct", re.I)).first,
        lambda: page.locator("main svg[aria-label='Direct']").first,
        lambda: page.locator("svg[aria-label='Direct']").first,
        lambda: page.locator("main [aria-label='Direct']").first,
        lambda: page.locator("[aria-label='Direct']").first,
        lambda: page.locator("svg[aria-label*='irect']").first,
        lambda: page.locator("main a[aria-label*='irect']").first,
    ):
        try:
            loc = factory()
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=8000)
            loc.click(timeout=20000)
            page.wait_for_timeout(2000)
            return
        except Exception as e:
            last_exc = e
            continue
    raise TimeoutError(
        "Could not click Direct on the story viewer (paper plane). "
        "Stay on /stories/ and use Direct — not Share — to forward the story via DM."
    ) from last_exc


def _story_dm_option_radio_check(opt) -> None:
    """
    Instagram share-to-DM list uses role=option rows with an inner 'Radio selection' control
    (recorded: get_by_label('Radio selection').check()), not a plain text click.
    """
    try:
        opt.get_by_label("Radio selection").check(timeout=12000)
        return
    except Exception:
        pass
    try:
        opt.get_by_label(re.compile(r"radio\s*selection", re.I)).check(timeout=10000)
        return
    except Exception:
        pass
    try:
        rad = opt.locator("input[type='radio']").first
        if rad.count() > 0:
            rad.check(timeout=10000)
            return
    except Exception:
        pass
    opt.click(timeout=12000)


def _story_dm_option_label(raw: str) -> str:
    line = (raw or "").strip().splitlines()
    return (line[0] if line else "").strip()[:200]


def _story_dm_skip_option_label(t: str) -> bool:
    if not t or len(t.strip()) < 2:
        return True
    one = t.splitlines()[0].strip()
    if re.match(
        r"^(send|search|share to|share|cancel|done|close|back|next|copy link|new message)\b",
        one,
        re.I,
    ):
        return True
    return False


def _select_story_dm_recipient(page: Page) -> str:
    """
    Pick a recipient in the share-to-DM sheet. Prefer IG's role=option + Radio selection
    (matches codegen); else regex on option name; else first plausible option; last resort
    dialog text/buttons. Returns visible label for _tc25_recipient.
    """
    page.wait_for_timeout(1500)
    dlg = page.get_by_role("dialog")
    try:
        dlg.wait_for(state="visible", timeout=20000)
    except Exception:
        dlg = page.locator("[role='dialog']").first
        try:
            dlg.wait_for(state="visible", timeout=8000)
        except Exception:
            pass

    # --- 1) Primary: listbox options + radio (same pattern as Playwright codegen for Direct share)
    try:
        opts = dlg.get_by_role("option")
        if opts.count() == 0:
            opts = page.get_by_role("option")
    except Exception:
        opts = page.get_by_role("option")
    n_opt = opts.count()
    if n_opt > 0:
        rx_pref = re.compile(_STORY_DM_RECIPIENT_REGEX, re.I)
        for pass_rx in (rx_pref, None):
            for i in range(min(n_opt, 35)):
                opt = opts.nth(i)
                try:
                    if not opt.is_visible():
                        continue
                    raw = (opt.inner_text() or opt.get_attribute("aria-label") or "").strip()
                    if _story_dm_skip_option_label(raw):
                        continue
                    if pass_rx is not None and not pass_rx.search(raw):
                        continue
                    opt.scroll_into_view_if_needed(timeout=8000)
                    _story_dm_option_radio_check(opt)
                    return _story_dm_option_label(raw)
                except Exception:
                    continue
            if pass_rx is not None:
                continue

    # --- 2) Legacy: substring in dialog + button rows
    pat = _STORY_DM_RECIPIENT_REGEX
    try:
        loc = dlg.get_by_text(re.compile(pat, re.I)).first
        if loc.count() > 0:
            loc.scroll_into_view_if_needed(timeout=8000)
            loc.click(timeout=15000)
            try:
                label = (loc.inner_text() or "").strip()
            except Exception:
                label = ""
            return _story_dm_option_label(label or pat)
    except Exception:
        pass

    skip_re = re.compile(
        r"^(send|search|share to|share|cancel|done|close|back|next|copy link)\b",
        re.I,
    )
    for container in (dlg, page):
        try:
            btns = container.get_by_role("button")
            n = btns.count()
            for i in range(min(n, 30)):
                el = btns.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    t = (el.inner_text() or el.get_attribute("aria-label") or "").strip()
                    t_one = t.splitlines()[0].strip() if t else ""
                    if len(t_one) < 2 or skip_re.search(t_one):
                        continue
                    if not re.search(r"[a-zA-Z]", t_one):
                        continue
                    el.scroll_into_view_if_needed(timeout=8000)
                    el.click(timeout=12000)
                    return t_one[:200]
                except Exception:
                    continue
        except Exception:
            continue

    raise TimeoutError(
        "Could not select a story DM recipient — share sheet may have no contacts or a new UI."
    )


def _after_story_click_from_home(page: Page) -> bool:
    page.wait_for_timeout(2000)
    try:
        page.wait_for_url(re.compile(r".*instagram\.com/.*stories.*"), timeout=22000)
    except Exception:
        pass
    return _story_viewer_opened(page)


def _open_story_via_tray_profile_picture_links(page: Page, timeout_ms: int) -> bool:
    """
    Recorded IG Web flow: home → story tray → link named \"{user}'s profile picture\"
    (not /stories/ hrefs only). Skips own account / Your story / Add story style rings.
    """
    _dismiss_popups(page)
    tray = page.locator("main")
    try:
        links = tray.get_by_role(
            "link",
            name=re.compile(r".+['\u2019]s profile picture", re.I),
        )
        n = links.count()
    except Exception:
        return False
    if n == 0:
        return False
    order = (list(range(1, n)) + [0]) if n > 1 else [0]
    for i in order:
        try:
            link = links.nth(i)
            if not link.is_visible():
                continue
            label = (
                link.get_attribute("aria-label")
                or link.get_attribute("title")
                or ""
            )
            if not label:
                try:
                    label = (link.inner_text() or "")[:400]
                except Exception:
                    label = ""
            if _story_tray_skip_profile_picture_label(label):
                continue
            link.scroll_into_view_if_needed(timeout=8000)
            link.click(timeout=min(20000, timeout_ms))
            if _after_story_click_from_home(page):
                return True
        except Exception:
            continue
    return False


def _try_open_story_main_tray_hrefs(page: Page, timeout_ms: int) -> bool:
    """
    Only `main` story-tray deep links (`/stories/<user>/...`). Tries ring index 1..n then 0
    so we skip 'Your story' at index 0 when another account exists. Avoids page-wide `.first`
    on `a[href*='stories']` / global links that open Explore, DMs, or the wrong profile.
    """
    _dismiss_popups(page)
    tray_links = page.locator("main").locator("a[href*='/stories/']")
    try:
        tray_links.first.wait_for(state="visible", timeout=min(28000, timeout_ms))
    except Exception:
        if tray_links.count() == 0:
            return False

    n = tray_links.count()
    order = (list(range(1, n)) + [0]) if n > 1 else [0]
    for i in order:
        try:
            link = tray_links.nth(i)
            if not link.is_visible():
                continue
            link.scroll_into_view_if_needed(timeout=8000)
            link.click(timeout=15000)
            if _after_story_click_from_home(page):
                return True
        except Exception:
            continue
    return False


def _open_first_story_from_home(page: Page, timeout_ms: int = 45000) -> None:
    """
    Home feed story tray: open someone else's story (not own). Prefer codegen-style
    \"{name}'s profile picture\" links in `main`, then /stories/ hrefs, then canvas / Story by…
    """
    page.wait_for_timeout(1500)
    last_exc = None

    if _open_story_via_tray_profile_picture_links(page, timeout_ms):
        return

    if _try_open_story_main_tray_hrefs(page, timeout_ms):
        return

    def _after_story_click() -> bool:
        return _after_story_click_from_home(page)

    # --- 1) Same tray links, extra selectors (lazy-rendered / nested sections) ---
    for sel in (
        "main section a[href*='/stories/']",
        "main header ~ div a[href*='/stories/']",
        "main a[href*='/stories/']",
    ):
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            n = min(loc.count(), 16)
            order = (list(range(1, n)) + [0]) if n > 1 else [0]
            for i in order:
                try:
                    link = loc.nth(i)
                    if not link.is_visible():
                        continue
                    link.scroll_into_view_if_needed(timeout=6000)
                    link.click(timeout=15000)
                    if _after_story_click():
                        return
                except Exception as e:
                    last_exc = e
                    continue
        except Exception as e:
            last_exc = e
            continue

    # --- 2) Story rings without href (keep under main / presentation; order matters) ---
    for sel in (
        "main section div[role='presentation'] div[role='button']",
        "main div[role='presentation'] div[role='button']",
        "main header ~ div div[role='button']",
        "main div[role='presentation'] button",
        "[role='presentation'] div[tabindex='0']",
    ):
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=12000)
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(timeout=12000)
            if _after_story_click():
                return
        except Exception as e:
            last_exc = e
            continue

    # --- 3) Canvas rings (index 1 first — 0 is often own avatar) ---
    for idx in (1, 0, 2, 3):
        try:
            canv = page.locator("main canvas").nth(idx)
            if canv.count() == 0:
                continue
            canv.scroll_into_view_if_needed(timeout=5000)
            canv.click(timeout=12000)
            page.wait_for_timeout(1500)
            if _after_story_click():
                return
        except Exception as e:
            last_exc = e
            continue

    # --- 4) Codegen-style: 'Story by …' in main only ---
    try:
        page.locator("main").get_by_role(
            "link",
            name=re.compile(r"story\s+by", re.I),
        ).first.click(timeout=12000)
        if _after_story_click():
            return
    except Exception as e:
        last_exc = e

    raise TimeoutError(
        "Could not open any story from home — tray may be empty, blocked, or DOM changed (see screenshot)."
    ) from last_exc


def _try_open_instagram_official_story_from_home(page: Page) -> bool:
    """
    Best-effort: open @instagram's story from the tray (deep link in href).
    Returns True if the story viewer URL is active.
    """
    try:
        loc = page.locator("main a[href*='/stories/instagram/']").first
        if loc.count() == 0:
            return False
        loc.scroll_into_view_if_needed(timeout=5000)
        loc.click(timeout=15000)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_url(re.compile(r".*instagram\.com/.*stories.*"), timeout=18000)
        except Exception:
            pass
        return _story_viewer_opened(page)
    except Exception:
        return False


def _click_reload_posts_if_present(page: Page) -> None:
    """Saved / collections: stale UI until reload — label may be 'Reload posts' or 'Reload page'."""
    for attempt in (
        lambda: page.get_by_role("button", name=re.compile(r"reload\s*posts", re.I)).click(
            timeout=8000
        ),
        lambda: page.get_by_role("button", name=re.compile(r"reload\s*page", re.I)).click(
            timeout=8000
        ),
        lambda: page.get_by_role("link", name=re.compile(r"reload\s*posts", re.I)).click(
            timeout=8000
        ),
        lambda: page.get_by_text(re.compile(r"reload\s*posts", re.I)).first.click(timeout=6000),
        lambda: page.get_by_text(re.compile(r"reload\s*page", re.I)).first.click(timeout=6000),
    ):
        try:
            attempt()
            page.wait_for_timeout(3500)
            return
        except Exception:
            continue


def _click_first_visible_saved_link(page: Page, selectors: Tuple[str, ...]) -> bool:
    """
    Try each selector; for each matching anchor, prefer a visible node (not display:none).
    Returns True if a link was clicked and navigation likely started.
    """
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = loc.count()
        except Exception:
            continue
        for i in range(min(n, 36)):
            link = loc.nth(i)
            try:
                if not link.is_visible():
                    continue
                link.scroll_into_view_if_needed(timeout=5000)
                link.click(timeout=15000)
                return True
            except Exception:
                continue
    return False


def _open_first_saved_grid_post(page: Page, timeout_ms: int = 45000) -> None:
    """
    /username/saved/ — optional 'Reload posts', 'All posts', then first grid tile with /p/ or /reel/.
    Scopes to main where possible (avoids hidden/header matches). Scrolls to lazy-load the grid.
    If nothing is saved, the grid never appears (account must have at least one saved item).
    """
    page.wait_for_timeout(2000)
    _click_reload_posts_if_present(page)
    try:
        page.get_by_role("link", name=re.compile(r"all\s*posts", re.I)).first.click(timeout=8000)
        page.wait_for_timeout(2000)
    except Exception:
        try:
            page.get_by_role("tab", name=re.compile(r"all\s*posts", re.I)).first.click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    _click_reload_posts_if_present(page)

    # Prefer links inside main — unscoped `.first` can match a hidden or wrong /p/ node.
    link_selectors = (
        "main a[href*='/p/']",
        "main a[href*='/reel/']",
        "[role='main'] a[href*='/p/']",
        "[role='main'] a[href*='/reel/']",
        "section a[href*='/p/']",
        "a[href*='/p/']",
        "a[href*='/reel/']",
    )

    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_exc = None
    scroll_round = 0

    while time.monotonic() < deadline:
        try:
            if _click_first_visible_saved_link(page, link_selectors):
                page.wait_for_timeout(1200)
                return
        except Exception as e:
            last_exc = e

        scroll_round += 1
        try:
            page.mouse.wheel(0, min(350 + scroll_round * 120, 1400))
        except Exception:
            pass
        page.wait_for_timeout(550)
        if scroll_round % 4 == 0:
            _click_reload_posts_if_present(page)

    msg = (
        "Saved grid: no visible post/reel link opened. "
        "Ensure casb.test3 has at least one saved post/reel, Saved loads, and try Reload posts."
    )
    raise TimeoutError(msg) from last_exc


def _upload_file(page: Page, file_paths):
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    with page.expect_file_chooser() as fc_info:
        page.get_by_role("button", name="Select from computer").click()
    fc_info.value.set_files(file_paths)


# ===============================================================
#  7. LOGOUT
# ===============================================================
def logout(page: Page, result=None):
    _go_home(page)
    if result is not None:
        try:
            result["_logout_url_before"] = page.url
        except Exception:
            result["_logout_url_before"] = ""
    _click_sidebar(page, "More", "Settings", "more")
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="Log out").click()
    page.wait_for_timeout(3000)
    print("Activity: Logout")
    print("Navigation: home/more(three dash)/logout")


# ===============================================================
#  8. POST IMAGE
# ===============================================================
def post_image(page: Page):
    _check_test_files()
    _go_home(page)
    _click_new_post(page)
    page.wait_for_timeout(2000)
    _upload_file(page, TEST_IMAGE_1)
    page.wait_for_timeout(3000)
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    try:
        _click_share_compose(page)
    except Exception:
        try:
            page.get_by_role("button", name="Share").click(timeout=15000)
            page.wait_for_timeout(8000)
        except Exception:
            pass
    try:
        page.get_by_role("button", name="Close").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    print("Activity: Upload Image")
    print("Navigation: home/+(create)/post/upload image/next/next/share")


# ===============================================================
#  9. POST VIDEO
# ===============================================================
def post_video(page: Page):
    _check_test_files()
    _go_home(page)
    _click_new_post(page)
    page.wait_for_timeout(2000)
    _upload_file(page, TEST_VIDEO)
    page.wait_for_timeout(5000)
    try:
        err = page.locator("text=File couldn't be uploaded")
        if err.count() > 0 and err.first.is_visible():
            print("  [!] Instagram rejected video file")
            return
    except Exception:
        pass
    try:
        page.get_by_role("button", name="OK").click()
        page.wait_for_timeout(2000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Next").click()
    except Exception:
        page.locator("div").filter(has_text=re.compile(r"^Next$")).nth(1).click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    try:
        _click_share_compose(page)
    except Exception:
        try:
            page.get_by_role("button", name="Share").click(timeout=15000)
            page.wait_for_timeout(8000)
        except Exception:
            pass
    try:
        page.get_by_role("button", name="Close").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    print("Activity: Upload Video")
    print("Navigation: home/+(create)/post/upload video/next/next/share")


# ===============================================================
#  10. CHANGE PROFILE PICTURE
# ===============================================================
def change_profile_picture(page: Page, result=None):
    _check_test_files()
    _nav(page, "https://www.instagram.com/accounts/edit/")
    page.wait_for_timeout(1500)
    # Baseline for TC5 UI validation: avatar URL before upload attempt (reload should match if CASB blocked)
    if result is not None:
        try:
            im = page.locator("img[alt*='profile picture']").first
            if im.count():
                result["_profile_avatar_src_before"] = (im.get_attribute("src") or "").strip()
            else:
                result["_profile_avatar_src_before"] = ""
        except Exception:
            result["_profile_avatar_src_before"] = ""
    clicked = False
    for sel_fn in [
        lambda: page.get_by_role("button", name=re.compile(r"change profile photo", re.IGNORECASE)),
        lambda: page.locator("img[alt*='profile picture']").first,
        lambda: page.locator("button:has(img[alt*='profile'])").first,
    ]:
        try:
            el = sel_fn()
            el.wait_for(state="visible", timeout=5000)
            el.click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        raise Exception(f"Profile pic edit not found. SVGs: {_dump_svg_labels(page)}")
    page.wait_for_timeout(2000)
    try:
        with page.expect_file_chooser() as fc_info:
            page.get_by_role("button", name="Upload Photo").click()
        fc_info.value.set_files(TEST_IMAGE_1)
    except Exception:
        with page.expect_file_chooser() as fc_info:
            page.get_by_role("button", name=re.compile(r"upload", re.IGNORECASE)).first.click()
        fc_info.value.set_files(TEST_IMAGE_1)
    page.wait_for_timeout(5000)
    print("Activity: Upload Profile Picture")
    print("Navigation: home/profile/change profile picture/upload photo")


# ===============================================================
#  11. POST MULTIPLE IMAGES
# ===============================================================
def post_multiple_images(page: Page):
    _check_test_files()
    _go_home(page)
    _click_new_post(page)
    page.wait_for_timeout(2000)
    _upload_file(page, [TEST_IMAGE_1, TEST_IMAGE_2])
    page.wait_for_timeout(3000)
    try:
        page.get_by_role("button", name="Next").click()
    except Exception:
        page.locator("div").filter(has_text=re.compile(r"^Next$")).nth(1).click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    try:
        page.get_by_role("button", name="Share").click()
        page.wait_for_timeout(8000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Close").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_timeout(1000)
    except Exception:
        pass
    print("Activity: Upload Multiple Images")
    print("Navigation: home/+(create)/post/upload multiple images/next/next/share")


# ===============================================================
#  12. UPLOAD IMAGE IN MESSAGES
# ===============================================================
def upload_image_messages(page: Page, result=None):
    _check_test_files()
    _go_dm_chat(page)
    if result is not None:
        try:
            result["_tc26_dm_url"] = page.url
        except Exception:
            result["_tc26_dm_url"] = ""
        try:
            result["_tc26_dm_rows_before"] = dm_thread_message_count(page)
        except Exception:
            result["_tc26_dm_rows_before"] = -1
    try:
        with page.expect_file_chooser() as fc_info:
            page.get_by_role("button", name="Add Photo or Video").click()
        fc_info.value.set_files(TEST_IMAGE_1)
    except Exception:
        with page.expect_file_chooser() as fc_info:
            page.locator("svg[aria-label='Add Photo or Video']").locator("..").click()
        fc_info.value.set_files(TEST_IMAGE_1)
    page.wait_for_timeout(3000)
    try:
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(3000)
    except Exception:
        pass
    print("Activity: Upload Image Messages")
    print("Navigation: home/messages/chat/upload image/send")


# ===============================================================
#  15. POST COMMENT ON HOME PAGE
# ===============================================================
def post_comment_home(page: Page):
    _go_home(page)
    page.get_by_role("button", name="Comment").first.click()
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="Add a comment…").fill("test casb comment")
    page.get_by_role("button", name="Post", exact=True).click()
    page.wait_for_timeout(3000)
    print("Activity: Post Comment")
    print("Navigation: home/any post/comment/type comment/post")


# ===============================================================
#  16. LIKE POST ON HOME PAGE
# ===============================================================
def like_post_home(page: Page, result=None):
    _go_home(page)
    if result is not None:
        try:
            link = page.locator("article").first.locator("a[href*='/p/'], a[href*='/reel/']").first
            href = (link.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.instagram.com" + href.split("?")[0]
            result["_like_post_url"] = href
        except Exception:
            result["_like_post_url"] = ""
    page.get_by_role("button", name="Like").first.click()
    page.wait_for_timeout(2000)
    print("Activity: Like Post")
    print("Navigation: home/any post/click like")


# ===============================================================
#  17. LIKE POST VIA SEARCH
# ===============================================================
def like_post_search(page: Page, result=None):
    _go_home(page)
    _click_sidebar(page, "Search")
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="Search input").fill("carlossainz55")
    page.wait_for_timeout(2000)
    page.get_by_role("link", name=re.compile(r"carlossainz55", re.IGNORECASE)).first.click()
    page.wait_for_timeout(3000)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_like_post_url"] = page.url
        except Exception:
            result["_like_post_url"] = ""
    page.get_by_role("button", name="Like", exact=True).first.click()
    page.wait_for_timeout(2000)
    try:
        page.get_by_role("button", name="Close").click()
    except Exception:
        pass
    print("Activity: Like Post via Search")
    print("Navigation: home/search/search account/open any post/like")


# ===============================================================
#  18. LIKE STORY ON HOME PAGE
# ===============================================================
def like_story_home(page: Page, result=None):
    _go_home(page)
    _open_first_story_from_home(page, timeout_ms=45000)
    page.wait_for_timeout(1500)
    try:
        page.get_by_role("button", name=re.compile(r"^Like$", re.I)).first.click(timeout=15000)
    except Exception:
        page.get_by_role("button", name="Like").click(timeout=15000)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_like_story_url"] = page.url
        except Exception:
            result["_like_story_url"] = ""
    print("Activity: Like Story")
    print("Navigation: home/first story in tray/like/capture story URL for UI reload check")


# ===============================================================
#  19. LIKE OWN POST
# ===============================================================
def like_own_post(page: Page, result=None):
    _go_profile(page)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_like_post_url"] = page.url
        except Exception:
            result["_like_post_url"] = ""
    page.get_by_role("button", name="Like", exact=True).first.click()
    page.wait_for_timeout(2000)
    print("Activity: Like Own Post")
    print("Navigation: profile/open own post or reel/like")


# ===============================================================
#  20. LIKE MESSAGE IN DMS
# ===============================================================
def like_message(page: Page, result=None):
    # Go directly to the known DM chat thread
    _go_dm_chat(page)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_like_dm_url"] = page.url
        except Exception:
            result["_like_dm_url"] = ""

    # Hover over a message row to reveal the reaction button
    msg_rows = page.locator("div[role='row']")
    if msg_rows.count() > 0:
        msg_rows.last.hover()
        page.wait_for_timeout(1500)

    # Click the react button and then select the heart
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"React to message", re.IGNORECASE),
        ).first.click()
    except Exception:
        # Fallback: any button with 'React'
        page.get_by_role(
            "button",
            name=re.compile(r"React", re.IGNORECASE),
        ).first.click()
    page.wait_for_timeout(1000)
    # Emoji grid often has multiple ❤️ buttons — strict mode requires .first or a scoped locator
    try:
        page.locator("[role='dialog'], [role='tooltip'], [aria-modal='true']").get_by_role(
            "button", name="❤️"
        ).first.click(timeout=8000)
    except Exception:
        page.get_by_role("button", name="❤️").first.click(timeout=8000)
    page.wait_for_timeout(2000)
    print("Activity: Like Message")
    print("Navigation: messages/known DM chat/hover message/react/heart")


# ===============================================================
#  21. LIKE REEL ON EXPLORE/REELS
# ===============================================================
def like_reel_explore(page: Page, result=None):
    _nav(page, "https://www.instagram.com/reels/")
    if result is not None:
        try:
            result["_like_reel_url_before"] = page.url
        except Exception:
            result["_like_reel_url_before"] = ""
    page.get_by_role("button", name="Like").first.click()
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_like_reel_url"] = page.url
        except Exception:
            result["_like_reel_url"] = ""
    print("Activity: Like Reel")
    print("Navigation: reels page/open reel/like")


# ===============================================================
#  22. LIKE SAVED POST
# ===============================================================
def like_saved_post(page: Page, result=None):
    _go_saved_collection(page)
    _open_first_saved_grid_post(page, timeout_ms=45000)
    page.wait_for_timeout(2500)
    if result is not None:
        try:
            result["_like_post_url"] = page.url
        except Exception:
            result["_like_post_url"] = ""
    page.get_by_role("button", name="Like", exact=True).first.click(timeout=20000)
    page.wait_for_timeout(2000)
    print("Activity: Like Saved Post")
    print("Navigation: home/More→Saved or /saved/All posts/Reload/first grid/like")


# ===============================================================
#  23. LIKE COMMENT
# ===============================================================
def like_comment(page: Page, result=None):
    _go_home(page)
    if result is not None:
        try:
            link = page.locator("article").first.locator("a[href*='/p/'], a[href*='/reel/']").first
            href = (link.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.instagram.com" + href.split("?")[0]
            result["_like_post_url"] = href
        except Exception:
            result["_like_post_url"] = ""
    # Open comments for the first post
    page.locator("svg[aria-label='Comment']").first.click()
    page.wait_for_timeout(3000)
    # Inside the dialog/overlay, find comment-level like buttons (small hearts next to comments)
    # The post-level Like is the big one; comment-level likes use a smaller heart icon
    try:
        like_btns = page.get_by_role("button", name="Like", exact=True)
        if like_btns.count() > 1:
            like_btns.nth(1).click()
        else:
            like_btns.first.click()
    except Exception:
        page.locator("svg[aria-label='Like']").nth(1).click()
    page.wait_for_timeout(2000)
    print("Activity: Like Comment")
    print("Navigation: home/any post/comments/like a comment")


# ===============================================================
#  24. SHARE POST FROM HOME
# ===============================================================
def share_post_home(page: Page):
    _go_home(page)
    page.wait_for_timeout(2500)
    article = page.locator("article").first
    article.wait_for(state="visible", timeout=25000)
    try:
        article.locator("svg[aria-label='Share']").first.click(timeout=20000)
    except Exception:
        try:
            sh = article.get_by_role("button", name=re.compile(r"Share", re.I))
            sh.first.click(timeout=20000)
        except Exception:
            page.locator("article").first.locator("[aria-label*='Share']").first.click(
                timeout=20000
            )
    page.wait_for_timeout(2500)
    dlg = page.get_by_role("dialog")
    dlg.wait_for(state="visible", timeout=20000)
    rx = getattr(_cfg, "SHARE_POST_RECIPIENT_REGEX", r"Liss|casb") or r"."
    try:
        dlg.get_by_role("button", name=re.compile(rx, re.I)).first.click(timeout=12000)
    except Exception:
        try:
            dlg.locator(
                "div[role='button'], button"
            ).filter(has_text=re.compile(rx, re.I)).first.click(timeout=8000)
        except Exception:
            dlg.locator("div[role='button']").nth(1).click(timeout=8000)
    page.wait_for_timeout(1000)
    try:
        page.get_by_role("button", name=re.compile(r"^Send$", re.I)).click(timeout=15000)
    except Exception:
        dlg.get_by_role("button", name=re.compile(r"Send", re.I)).click(timeout=15000)
    page.wait_for_timeout(3000)
    print("Activity: Share Post")
    print("Navigation: home/any post/share/select account/send")


# ===============================================================
#  25. SHARE IMAGE IN MESSAGES
# ===============================================================
def share_image_messages(page: Page, result=None):
    _check_test_files()
    _go_dm_chat(page)
    if result is not None:
        try:
            result["_tc23_dm_url"] = page.url
        except Exception:
            result["_tc23_dm_url"] = ""
        try:
            result["_tc23_dm_rows_before"] = dm_thread_message_count(page)
        except Exception:
            result["_tc23_dm_rows_before"] = -1
    try:
        with page.expect_file_chooser() as fc_info:
            page.get_by_role("button", name="Add Photo or Video").click()
        fc_info.value.set_files(TEST_IMAGE_1)
    except Exception:
        with page.expect_file_chooser() as fc_info:
            page.locator("svg[aria-label='Add Photo or Video']").locator("..").click()
        fc_info.value.set_files(TEST_IMAGE_1)
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Send").click()
    page.wait_for_timeout(3000)
    print("Activity: Share Image in Messages")
    print("Navigation: messages/chat/attach image/send")


def _note_overlay_root(page: Page):
    """
    Instagram note UI is often NOT role=dialog — it may use aria-modal, presentation layer,
    or a full-width panel. Return the best container for scoping fills (never the inbox search).
    Do not use main() alone — it includes the Search column.
    """
    ordered = (
        page.locator('[aria-modal="true"]').first,
        page.get_by_role("dialog").first,
        page.locator('div[role="presentation"]').filter(
            has_text=re.compile(r"new\s*note|your\s*note|shared\s+with", re.I)
        ).first,
    )
    for loc in ordered:
        try:
            if loc.count() == 0:
                continue
            loc.wait_for(state="visible", timeout=5000)
            return loc
        except Exception:
            continue
    return page.locator("body")


def _fill_note_composer_text(page: Page, text: str) -> None:
    """
    Type into the Instagram *note* composer only. The inbox Search field is a separate
    textbox/contenteditable on the left — we avoid page.get_by_role('textbox').first.
    """
    page.wait_for_timeout(1000)
    errs = []

    # Prove the composer opened (avoid matching bare "note" — too many hits on the page)
    try:
        page.get_by_text(
            re.compile(r"new\s*note|your\s*note|first\s+note", re.I)
        ).first.wait_for(
            state="visible",
            timeout=20000,
        )
    except Exception as ex:
        errs.append(f"wait note title: {ex!r}")

    root = _note_overlay_root(page)

    for attempt in (
        lambda r: r.locator("[contenteditable='true']").first,
        lambda r: r.get_by_role("textbox").first,
        lambda r: r.locator("div[role='textbox']").first,
        lambda r: r.get_by_role("paragraph").first,
    ):
        try:
            loc = attempt(root)
            if loc.count() == 0:
                continue
            box = loc.bounding_box()
            if box is not None and float(box.get("x", 0)) < 72:
                continue
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(timeout=10000)
            page.wait_for_timeout(400)
            loc.fill(text)
            return
        except Exception as ex:
            errs.append(repr(ex))
            continue

    # Contenteditable in the right pane (search is usually far left)
    try:
        n = page.locator("[contenteditable='true']").count()
        for i in range(n - 1, -1, -1):
            el = page.locator("[contenteditable='true']").nth(i)
            try:
                box = el.bounding_box()
                if box is not None and float(box.get("x", 0)) < 72:
                    continue
                el.click(timeout=8000)
                el.fill(text)
                return
            except Exception as ex:
                errs.append(repr(ex))
                continue
    except Exception as ex:
        errs.append(repr(ex))

    try:
        root.click(timeout=5000)
        page.wait_for_timeout(250)
        page.keyboard.press("Control+A")
        page.keyboard.type(text, delay=40)
        return
    except Exception as ex:
        errs.append(repr(ex))

    raise TimeoutError(
        "Could not type into note composer. " + " | ".join(errs[-8:])
    )


def _click_note_share(page: Page) -> None:
    """Share on the note sheet — prefer button inside modal; else rightmost Share (not sidebar)."""
    last_exc = None
    for scope in (
        page.locator('[aria-modal="true"]').first,
        page.get_by_role("dialog").first,
        _note_overlay_root(page),
    ):
        try:
            if scope.count() == 0:
                continue
            btn = scope.get_by_role("button", name=re.compile(r"^share$", re.I)).first
            if btn.count() > 0:
                btn.click(timeout=15000)
                return
        except Exception as e:
            last_exc = e
            continue
    # Rightmost visible Share matches the composer footer (inbox search has no Share)
    try:
        shares = page.get_by_role("button", name=re.compile(r"^share$", re.I))
        best, best_x = None, -1.0
        for i in range(shares.count()):
            b = shares.nth(i)
            try:
                box = b.bounding_box()
                if not box:
                    continue
                x = float(box.get("x", 0))
                if x > best_x:
                    best_x, best = x, b
            except Exception:
                continue
        if best is not None:
            best.click(timeout=15000)
            return
    except Exception as e:
        last_exc = e
    try:
        exact = page.get_by_role("button", name="Share", exact=True)
        best, best_x = None, -1.0
        for i in range(exact.count()):
            b = exact.nth(i)
            try:
                box = b.bounding_box()
                if not box:
                    continue
                x = float(box.get("x", 0))
                if x > best_x:
                    best_x, best = x, b
            except Exception:
                continue
        if best is not None:
            best.click(timeout=15000)
            return
    except Exception as e:
        last_exc = e
    raise TimeoutError(f"Could not click Share on note: {last_exc!r}") from last_exc


# ===============================================================
#  26. SHARE NOTE IN MESSAGES
# ===============================================================
def share_note_messages(page: Page, result=None):
    _go_messages(page)
    note_text = "hiii"
    if result is not None:
        try:
            result["_tc24_messages_url"] = page.url
        except Exception:
            result["_tc24_messages_url"] = ""
        result["_tc24_note_share_text"] = note_text

    page.wait_for_timeout(2000)

    # Open note composer — avoid matching generic "note" that isn't the composer entry
    opened = False
    for opener in (
        lambda: page.get_by_role(
            "button", name=re.compile(r"first note of the week", re.I)
        ).click(timeout=12000),
        lambda: page.get_by_role(
            "button", name=re.compile(r"your note", re.I)
        ).first.click(timeout=12000),
        lambda: page.get_by_role(
            "button", name=re.compile(r"new note", re.I)
        ).first.click(timeout=12000),
        lambda: page.get_by_role(
            "link", name=re.compile(r"note", re.I)
        ).first.click(timeout=12000),
    ):
        try:
            opener()
            page.wait_for_timeout(2000)
            opened = True
            break
        except Exception:
            continue

    if not opened:
        note_btns = page.get_by_role("button", name=re.compile(r"note", re.I))
        for i in range(min(note_btns.count(), 8)):
            try:
                note_btns.nth(i).click(timeout=8000)
                page.wait_for_timeout(2000)
                page.get_by_text(re.compile(r"new\s*note|your\s*note", re.I)).first.wait_for(
                    state="visible",
                    timeout=8000,
                )
                opened = True
                break
            except Exception:
                continue

    _fill_note_composer_text(page, note_text)
    _click_note_share(page)
    page.wait_for_timeout(3000)
    print("Activity: Share Note")
    print("Navigation: messages/note overlay / edit / share")


# ===============================================================
#  27. SHARE REEL FROM EXPLORE
# ===============================================================
def share_reel_explore(page: Page):
    _nav(page, "https://www.instagram.com/reels/")
    page.get_by_role("button", name="Share").first.click()
    page.wait_for_timeout(2000)
    page.get_by_role("dialog").get_by_role("button", name=re.compile(r"Liss", re.IGNORECASE)).click()
    page.wait_for_timeout(1000)
    try:
        page.get_by_role("button", name="Send").click()
    except Exception:
        page.get_by_role("dialog").get_by_role("button", name=re.compile(r"Liss", re.IGNORECASE)).click()
    page.wait_for_timeout(3000)
    print("Activity: Share Reel")
    print("Navigation: reels/open reel/share/select account/send")


# ===============================================================
#  28. SHARE OWN POST
# ===============================================================
def share_own_post(page: Page):
    _go_profile(page)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Share Post").click()
    page.wait_for_timeout(2000)
    # Select first suggested account from the share dialog
    try:
        page.get_by_role("dialog").get_by_role("button").nth(1).click()
    except Exception:
        page.get_by_role("button", name=re.compile(r"Carlos Sainz|Liss|casb", re.IGNORECASE)).first.click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Send").click()
    page.wait_for_timeout(3000)
    print("Activity: Share Own Post")
    print("Navigation: profile/own post or reel/share/select account/send")


# ===============================================================
#  29. SHARE STORY
# ===============================================================
def share_story(page: Page, result=None):
    _go_home(page)
    page.wait_for_timeout(2000)
    _dismiss_popups(page)
    try:
        page.locator("main a[href*='/stories/']").first.wait_for(
            state="visible", timeout=35000
        )
    except Exception:
        pass

    # Open any story from the home tray first (codegen pattern: any ring, not a fixed account).
    try:
        _open_first_story_from_home(page, timeout_ms=45000)
    except Exception:
        if not _try_open_instagram_official_story_from_home(page):
            try:
                page.locator("main").get_by_role(
                    "link",
                    name=re.compile(
                        r"instagram'?s?\s+profile\s+picture|instagram.*story|story\s+by\s+instagram",
                        re.I,
                    ),
                ).first.click(timeout=15000)
                page.wait_for_timeout(2500)
            except Exception:
                pass
        if not _story_viewer_opened(page):
            _open_first_story_from_home(page, timeout_ms=45000)

    _wait_story_viewer_ready(page, timeout_ms=35000)
    _click_story_direct_for_dm(page)

    # Choose recipient and send (any visible contact — not a single hardcoded account)
    picked = _select_story_dm_recipient(page)
    if result is not None:
        result["_tc25_recipient"] = picked
    page.wait_for_timeout(1000)
    try:
        page.get_by_role("button", name=re.compile(r"^send$", re.I)).first.click(timeout=15000)
    except Exception:
        page.get_by_role("button", name="Send").click(timeout=15000)
    page.wait_for_timeout(2000)
    try:
        page.get_by_role("button", name=re.compile(r"^close$", re.I)).first.click(timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if result is not None:
        try:
            u = page.url or ""
            if "/direct/" in u:
                result["_tc25_dm_url"] = u
                result["_tc25_dm_rows_after_send"] = page.locator("div[role='row']").count()
            else:
                result["_tc25_dm_url"] = ""
                result["_tc25_dm_rows_after_send"] = -1
        except Exception:
            result["_tc25_dm_rows_after_send"] = -1

    # Do not navigate away to a fixed story URL — that leaves the DM/share flow and breaks validation
    print("Activity: Share Story")
    print("Navigation: home/story tray/open story/Direct/select recipient/Send/Close")


# ===============================================================
#  30. DELETE OWN POST
# ===============================================================
def delete_own_post(page: Page, result=None):
    _go_profile(page)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_tc11_post_url"] = page.url
            result["_tc11_post_path"] = _ig_media_path_from_url(page.url)
        except Exception:
            result["_tc11_post_path"] = ""
    page.get_by_role("button", name="More options").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(3000)
    print("Activity: Delete Post")
    print("Navigation: profile/own post or reel/three dots/delete/confirm")


# ===============================================================
#  31. DELETE COMMENT ON OWN POST
# ===============================================================
def delete_comment_own_post(page: Page, result=None):
    _go_profile(page)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    if result is not None:
        result["_tc8_target_comment_text"] = _tc7_snapshot_existing_comment(page)
    # Try to open comment options if needed
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"Comment Options|More options", re.IGNORECASE),
        ).first.click()
        page.wait_for_timeout(1000)
    except Exception:
        try:
            page.locator("svg[aria-label='Comment Options']").first.click()
            page.wait_for_timeout(1000)
        except Exception:
            # If there is a direct Delete button (like in your recording), just continue
            pass

    # Click Delete on the menu / dialog
    try:
        page.get_by_role("button", name=re.compile(r"Delete", re.IGNORECASE)).first.click()
        page.wait_for_timeout(1500)
    except Exception:
        pass

    # If a confirmation dialog appears, click Delete again
    try:
        page.get_by_role("button", name=re.compile(r"Delete", re.IGNORECASE)).first.click()
    except Exception:
        pass
    page.wait_for_timeout(3000)
    print("Activity: Delete Comment on Own Post")
    print("Navigation: profile/own post/delete(or comment options+delete)/confirm delete(if shown)")


# ===============================================================
#  32. DELETE COMMENT ON HOME PAGE
# ===============================================================
def _tc7_snapshot_existing_comment(page: Page) -> str:
    """Best-effort text of a comment to track after reload (e.g. casb.test3 / Hii)."""
    try:
        link = page.get_by_role("link", name=re.compile(r"casb\.test3", re.I)).first
        if link.count():
            row = link.locator("xpath=ancestor::li[1]")
            if row.count():
                for line in (row.inner_text() or "").split("\n"):
                    s = line.strip()
                    if not s or s.lower() in ("reply", "like") or "casb.test" in s.lower():
                        continue
                    if 1 < len(s) < 150:
                        return s[:120]
    except Exception:
        pass
    try:
        li = page.locator("article ul li").first
        if li.count():
            for line in (li.inner_text() or "").split("\n"):
                s = line.strip()
                if 1 < len(s) < 120 and s.lower() not in ("reply", "like", "see translation"):
                    return s[:120]
    except Exception:
        pass
    return ""


def delete_comment_home(page: Page, result=None):
    """Delete a comment on first post of carlossainz55 via search."""
    _go_home(page)

    # Open search
    try:
        page.get_by_role("button", name=re.compile(r"Search", re.I)).click()
    except Exception:
        page.get_by_role("link", name=re.compile(r"Search", re.I)).click()
    page.wait_for_timeout(1500)

    # Type search query (more specific to reduce noise)
    page.get_by_role("textbox", name=re.compile(r"Search input", re.I)).fill("carlo")
    page.wait_for_timeout(2000)

    # Click first matching 'carlossainz55' profile
    profile_links = page.get_by_role("link", name=re.compile(r"carlossainz55", re.I))
    profile_links.nth(0).click()
    page.wait_for_timeout(4000)

    # Open first post on profile (grid links are /p/ or /reel/ — not always article>a)
    _open_first_post_from_profile_grid(page, timeout_ms=25000)
    page.wait_for_timeout(3000)

    posted_probe = False
    # Ensure there is at least one comment to delete: add one if needed
    try:
        box = page.get_by_role("textbox", name=re.compile(r"Add a comment", re.I))
        box.fill("delete me")
        page.get_by_role("button", name="Post", exact=True).click()
        page.wait_for_timeout(4000)
        posted_probe = True
    except Exception:
        pass  # if comment box not found, assume there is already a comment

    if result is not None:
        if posted_probe:
            result["_tc7_target_comment_text"] = "delete me"
        else:
            result["_tc7_target_comment_text"] = _tc7_snapshot_existing_comment(page)

    # Open comment options and delete
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"Comment Options|More options", re.IGNORECASE),
        ).first.click()
    except Exception:
        page.locator("svg[aria-label='Comment Options']").first.click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(3000)

    print("Activity: Delete Comment on Home")
    print(
        "Navigation: search/profile/first post/add comment(if needed)/comment options/delete"
    )


# ===============================================================
#  33. DELETE OWN STORY
# ===============================================================
def delete_own_story(page: Page, result=None):
    _go_home(page)
    page.get_by_role("main").get_by_role("link", name=re.compile(r"casb.test3.*profile picture", re.IGNORECASE)).click()
    page.wait_for_timeout(3000)
    if result is not None:
        try:
            result["_tc12_story_url"] = page.url
        except Exception:
            result["_tc12_story_url"] = ""
    page.get_by_role("button", name="Menu").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(3000)
    print("Activity: Delete Story")
    print("Navigation: home/own story/menu/delete/confirm")


# ===============================================================
#  34. DELETE NOTE IN MESSAGES
# ===============================================================
def delete_note_messages(page: Page, result=None):
    _go_messages(page)
    note_btn = page.get_by_role("button", name=re.compile(r"casb.test3.*profile", re.IGNORECASE)).first
    if result is not None:
        try:
            raw = (note_btn.inner_text() or "").strip()
            aria = (note_btn.get_attribute("aria-label") or "").strip()
            result["_delete_note_snapshot"] = (raw or aria or "")[:220]
        except Exception:
            result["_delete_note_snapshot"] = ""
    note_btn.click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Delete note").click()
    page.wait_for_timeout(3000)
    print("Activity: Delete Note")
    print("Navigation: messages/click on note/delete note")


# ===============================================================
#  35. DELETE GROUP CHAT
# ===============================================================
def delete_group_chat(page: Page, result=None):
    _go_messages(page)
    # Open the casb chat thread like your recording
    try:
        page.get_by_role("link", name=re.compile(r"Messages", re.IGNORECASE)).click()
    except Exception:
        pass
    page.wait_for_timeout(1500)

    # Click on the specific casb chat in the left sidebar
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"user-profile-picture\s*casb", re.IGNORECASE),
        ).click()
    except Exception:
        # Fallback: any chat button containing 'casb'
        page.get_by_role("button", name=re.compile(r"casb", re.IGNORECASE)).first.click()
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            fill_delete_chat_target_label_if_missing(page, result, "_delete_group_chat_target_label")
        except Exception:
            pass
        if not (result.get("_delete_group_chat_target_label") or "").strip():
            try:
                raw = (
                    page.get_by_role("button", name=re.compile(r"casb", re.IGNORECASE))
                    .first.inner_text()
                    or ""
                ).strip()
                result["_delete_group_chat_target_label"] = raw.split("\n")[0].strip()[:120]
            except Exception:
                result["_delete_group_chat_target_label"] = ""

    # Open more options for the thread and delete
    page.get_by_role("button", name="More options", exact=True).click()
    page.wait_for_timeout(1000)
    page.get_by_role(
        "button",
        name=re.compile(r"Delete\s+thread|Delete chat", re.IGNORECASE),
    ).click()
    page.wait_for_timeout(1000)
    # Confirm delete if a dialog appears
    try:
        page.get_by_role("button", name=re.compile(r"Delete", re.IGNORECASE)).first.click()
    except Exception:
        pass
    page.wait_for_timeout(3000)
    print("Activity: Delete Group Chat")
    print("Navigation: messages/casb chat/more options/delete thread/confirm delete(if shown)")


# ===============================================================
#  36. DELETE CHAT
# ===============================================================
def _delete_chat_inbox_thread_links(page: Page):
    """Instagram DM inbox rows — role=listbox is often absent; href is stable."""
    for sel in (
        "div[role='listbox'] a[href*='/direct/t/']",
        "div[role='list'] a[href*='/direct/t/']",
        "a[href*='/direct/t/']",
    ):
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n > 0:
                return loc, n
        except Exception:
            continue
    try:
        loc = page.locator("a[href*='/direct/t/']")
        return loc, loc.count()
    except Exception:
        return page.locator("a[href*='/direct/t/']"), 0


def fill_delete_chat_target_label_if_missing(page: Page, result: dict, key: str = "_delete_chat_target_label") -> None:
    """If list capture missed, read the open thread title from the main pane header."""
    if not result or (result.get(key) or "").strip():
        return
    for sel in (
        "div[role='main'] h2",
        "[role='main'] h2",
        "header h2",
        "div[role='main'] span[dir='auto']",
        "section h2",
    ):
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            t = (el.inner_text() or "").strip()
            if t and len(t) < 120:
                result[key] = t.split("\n")[0].strip()[:120]
                return
        except Exception:
            continue


def delete_chat(page: Page, result=None):
    _go_messages(page)
    # Prefer any existing chat from the inbox list; if none are visible
    # (fresh account / DOM change), fall back to a known DM thread URL.
    chat_links, count = _delete_chat_inbox_thread_links(page)

    if count > 0:
        idx = 1 if count > 1 else 0
        if result is not None:
            try:
                raw = (chat_links.nth(idx).inner_text() or "").strip()
                # First line is usually the display name (e.g. "Liss")
                result["_delete_chat_target_label"] = raw.split("\n")[0].strip()[:120]
            except Exception:
                if result is not None:
                    result["_delete_chat_target_label"] = ""
        chat_links.nth(idx).click()
    else:
        if result is not None:
            result["_delete_chat_target_label"] = ""
        _nav(page, "https://www.instagram.com/direct/t/17842019184172650/")

    page.wait_for_timeout(2000)
    if result is not None:
        fill_delete_chat_target_label_if_missing(page, result)
    try:
        page.get_by_role("button", name="Conversation information").click()
    except Exception:
        page.locator("svg[aria-label='Conversation information']").click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Delete chat").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Delete").click()
    page.wait_for_timeout(3000)
    print("Activity: Delete Chat")
    print("Navigation: messages/any chat/info/delete chat/confirm")


# ===============================================================
#  37. EDIT OWN POST
# ===============================================================
def edit_own_post(page: Page, result=None):
    _go_profile(page)
    _click_first_post(page)
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            result["_tc14_post_url"] = page.url
            result["_tc14_post_path"] = _ig_media_path_from_url(page.url)
        except Exception:
            result["_tc14_post_path"] = ""
        # Strings the navigation attempts to apply (must match steps below)
        result["_tc14_expected_caption"] = "edited by casb test"
        result["_tc14_expected_location_query"] = "ban"
    page.get_by_role("button", name="More options").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Edit").click()
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="Add location").click()
    page.get_by_role("textbox", name="Add location").fill("ban")
    page.wait_for_timeout(1500)
    # Select first location suggestion
    try:
        page.get_by_role("button", name=re.compile(r"Ban", re.IGNORECASE)).first.click()
    except Exception:
        pass
    page.wait_for_timeout(1000)
    page.get_by_role("textbox", name=re.compile(r"caption", re.IGNORECASE)).click()
    page.get_by_role("textbox", name=re.compile(r"caption", re.IGNORECASE)).fill("edited by casb test")
    page.get_by_role("button", name="Done").click()
    page.wait_for_timeout(3000)
    try:
        page.get_by_role("button", name="Close").click()
    except Exception:
        pass
    print("Activity: Edit Post")
    print("Navigation: profile/own post/three dots/edit/change caption+location/done")


# ===============================================================
#  38. EDIT MESSAGE IN DMS
# ===============================================================
def edit_message(page: Page):
    _go_dm_chat(page)
    # Send a message first
    page.get_by_role("textbox", name="Message").click()
    page.get_by_role("textbox", name="Message").fill("casb test msg")
    page.get_by_role("textbox", name="Message").press("Enter")
    page.wait_for_timeout(3000)
    # Hover over the last message row to reveal three-dot menu
    msg_rows = page.locator("div[role='row']")
    if msg_rows.count() > 0:
        msg_rows.last.hover()
        page.wait_for_timeout(1500)
    try:
        page.get_by_role("button", name=re.compile(r"See more options for message|More", re.IGNORECASE)).last.click()
    except Exception:
        page.locator("svg[aria-label='More']").last.click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name=re.compile(r"Edit", re.IGNORECASE)).click()
    page.wait_for_timeout(1500)
    # The edit textbox might have different labels
    try:
        tb = page.get_by_role("textbox", name=re.compile(r"Editing message|Message", re.IGNORECASE))
        tb.fill("casb test edited")
        tb.press("Enter")
    except Exception:
        page.get_by_role("textbox").last.fill("casb test edited")
        page.get_by_role("textbox").last.press("Enter")
    page.wait_for_timeout(3000)
    print("Activity: Edit Message")
    print("Navigation: messages/chat/send message/hover/three dots/edit/save")


# ===============================================================
#  39. EDIT HIGHLIGHT
# ===============================================================
def edit_highlight(page: Page, result=None):
    _go_profile(page)
    if result is not None:
        result["_tc13_new_highlight_name"] = "casb highlight"
        try:
            tgt = page.get_by_role(
                "button",
                name=re.compile(r"casb\.test3.*highlight story picture", re.IGNORECASE),
            ).first
            raw = (tgt.inner_text() or tgt.get_attribute("aria-label") or "").strip()
            result["_tc13_highlight_label_before"] = raw[:220]
        except Exception:
            result["_tc13_highlight_label_before"] = ""
        try:
            link = page.locator("a[href*='/highlights/']").first
            if link.count():
                result["_tc13_highlight_grid_text"] = (link.inner_text() or "").strip()[:120]
        except Exception:
            result["_tc13_highlight_grid_text"] = ""
    # Click the specific highlight story picture on own profile
    try:
        page.get_by_role(
            "button",
            name=re.compile(r"casb\.test3.*highlight story picture", re.IGNORECASE),
        ).click()
    except Exception:
        page.get_by_role(
            "button",
            name=re.compile(r"highlight story picture", re.IGNORECASE),
        ).first.click()
    page.wait_for_timeout(3000)
    page.get_by_role("button", name="Menu").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Edit").click()
    page.wait_for_timeout(2000)
    if result is not None:
        try:
            tb = page.get_by_role("textbox", name="Highlight Name")
            before_val = (tb.input_value() or tb.inner_text() or "").strip()
            result["_tc13_highlight_name_before_edit"] = before_val[:220]
        except Exception:
            result["_tc13_highlight_name_before_edit"] = ""
    page.get_by_role("textbox", name="Highlight Name").click()
    page.get_by_role("textbox", name="Highlight Name").fill("casb highlight ")
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Next").click()
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Done").click()
    page.wait_for_timeout(3000)
    print("Activity: Edit Highlight")
    print("Navigation: profile/highlight/menu/edit/change name/next/next/done")

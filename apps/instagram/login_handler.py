"""
Instagram — BrowserMixin: single-tab navigation per TC (Playwright).

Personal/session login uses persistent Chrome profile (config); log in once if prompted.
"""


def login(browser, account_type, cfg):
    """Optional hook from run.py — persistent profile handles session."""
    print(
        "   [Instagram] Persistent Chrome profile — log in manually once if you see a login screen."
    )


class BrowserMixin:
    """Required by framework: _open_fresh_tab + _wait_for_app."""

    def _open_fresh_tab(self):
        """Reuse first page, goto app URL, close extra tabs (stable on Windows/RDP)."""
        url = self.app_config.get("app_url", "https://www.instagram.com/")
        alive = [p for p in self.browser.pages if not p.is_closed()]
        if not alive:
            page = self.browser.new_page()
        else:
            page = alive[0]
            for extra in alive[1:]:
                try:
                    extra.close()
                except Exception:
                    pass
        page.set_default_timeout(45000)
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        print(f"\nInstagram tab → {url} (TC navigation)")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        from apps.instagram import navigations as nav

        nav._dismiss_popups(page)
        page.wait_for_timeout(800)
        return page

    def _wait_for_app(self, page) -> bool:
        print("Waiting for Instagram…")
        for _attempt in range(24):
            try:
                if page.locator("svg[aria-label='Home']").first.is_visible(timeout=3000):
                    return True
            except Exception:
                pass
            try:
                if page.locator("input[name='username']").first.is_visible(timeout=2000):
                    print(
                        "   [!] Login screen — sign in once; profile will remember the session."
                    )
                    return True
            except Exception:
                pass
            page.wait_for_timeout(5000)
        return False

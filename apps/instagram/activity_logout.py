"""Instagram — category: logout."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramLogoutMixin:
    def _do_logout(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "logout", nav.logout)

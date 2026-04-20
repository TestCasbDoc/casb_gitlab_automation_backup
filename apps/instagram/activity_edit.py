"""Instagram — category: edit."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramEditMixin:
    def _do_edit_highlight(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "edit_highlight", nav.edit_highlight)

    def _do_edit_message(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "edit_message", nav.edit_message)

    def _do_edit_own_post(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "edit_own_post", nav.edit_own_post)

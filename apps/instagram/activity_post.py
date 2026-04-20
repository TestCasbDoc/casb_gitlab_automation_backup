"""Instagram — category: post (TC1 comment flow)."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramPostMixin:
    def _do_post_comment_home(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "post_comment_home", nav.post_comment_home)

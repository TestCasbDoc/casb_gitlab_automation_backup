"""Instagram — category: like."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramLikeMixin:
    def _do_like_comment(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_comment", nav.like_comment)

    def _do_like_message(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_message", nav.like_message)

    def _do_like_own_post(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_own_post", nav.like_own_post)

    def _do_like_post_home(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_post_home", nav.like_post_home)

    def _do_like_post_search(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_post_search", nav.like_post_search)

    def _do_like_reel_explore(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_reel_explore", nav.like_reel_explore)

    def _do_like_saved_post(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_saved_post", nav.like_saved_post)

    def _do_like_story_home(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "like_story_home", nav.like_story_home)

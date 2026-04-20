"""Instagram — category: share (feed posts, reels, story, etc.)."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramShareMixin:
    def _do_post_image(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "post_image", nav.post_image)

    def _do_post_multiple_images(self, page, result, **kwargs):
        return insta_run(
            self, page, result, kwargs, "post_multiple_images", nav.post_multiple_images
        )

    def _do_post_video(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "post_video", nav.post_video)

    def _do_share_note_messages(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_note_messages", nav.share_note_messages)

    def _do_share_own_post(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_own_post", nav.share_own_post)

    def _do_share_post_home(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_post_home", nav.share_post_home)

    def _do_share_reel_explore(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_reel_explore", nav.share_reel_explore)

    def _do_share_story(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_story", nav.share_story)

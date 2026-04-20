"""Instagram — category: delete."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramDeleteMixin:
    def _do_delete_chat(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_chat", nav.delete_chat)

    def _do_delete_comment_home(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_comment_home", nav.delete_comment_home)

    def _do_delete_comment_own_post(self, page, result, **kwargs):
        return insta_run(
            self, page, result, kwargs, "delete_comment_own_post", nav.delete_comment_own_post
        )

    def _do_delete_group_chat(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_group_chat", nav.delete_group_chat)

    def _do_delete_note_messages(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_note_messages", nav.delete_note_messages)

    def _do_delete_own_post(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_own_post", nav.delete_own_post)

    def _do_delete_own_story(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "delete_own_story", nav.delete_own_story)

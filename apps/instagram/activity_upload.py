"""Instagram — category: upload (profile photo, message attachments)."""

from apps.instagram import navigations as nav
from apps.instagram.activity_common import insta_run


class InstagramUploadMixin:
    def _do_change_profile_picture(self, page, result, **kwargs):
        return insta_run(
            self, page, result, kwargs, "change_profile_picture", nav.change_profile_picture
        )

    def _do_share_image_messages(self, page, result, **kwargs):
        return insta_run(self, page, result, kwargs, "share_image_messages", nav.share_image_messages)

    def _do_upload_image_messages(self, page, result, **kwargs):
        return insta_run(
            self, page, result, kwargs, "upload_image_messages", nav.upload_image_messages
        )

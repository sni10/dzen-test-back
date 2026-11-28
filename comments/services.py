"""Comment use cases. Views only translate HTTP to these calls; rules live here."""
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import F

from accounts.models import User
from captcha.service import CaptchaService

from .attachments import AttachmentRejected, CheckedUpload, inspect_upload
from . import stats
from .live import Notifier
from .markup import CommentMarkup, MarkupError
from .models import Attachment, Comment
from .viewer import Viewer


class CommentError(Exception):
    """A rule violation reported to the client as a field error."""

    field = 'non_field_errors'

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptchaInvalid(CommentError):
    field = 'captcha'


class ParentNotFound(CommentError):
    field = 'parent'


class InvalidAttachment(CommentError):
    field = 'attachment'


class InvalidMarkup(CommentError):
    field = 'text'

    def __init__(self, error: MarkupError):
        super().__init__(error.message)
        self.code = error.code
        self.position = error.position


@dataclass(frozen=True)
class NewComment:
    """Validated form data (field formats are checked by the serializer)."""

    user_name: str
    email: str
    text: str
    home_page: str = ''
    parent_id: int | None = None
    captcha_key: str = ''
    captcha_answer: str = ''
    attachment: UploadedFile | None = None


@dataclass(frozen=True)
class Author:
    """Who posts and from where. A registered user is identified by `user`, a guest by `guest_key`."""

    user: User | None = None
    guest_key: UUID | None = None
    ip: str | None = None
    user_agent: str = ''

    @property
    def viewer(self) -> Viewer:
        return Viewer(
            user_id=self.user.pk if self.user else None,
            guest_key=None if self.user else self.guest_key,
            is_moderator=bool(self.user and self.user.is_moderator),
        )


class CommentService:
    def __init__(
        self,
        markup: CommentMarkup,
        captcha: CaptchaService,
        process_attachment: Callable[[int], None],
        notifier: Notifier,
        index_comments: Callable[[list[int]], None] = lambda ids: None,
    ):
        self.markup = markup
        self.captcha = captcha
        self.process_attachment = process_attachment  # queues background work (a Celery task)
        self.notifier = notifier  # live updates over WebSocket
        self.index_comments = index_comments  # queues search indexing (a Celery task)

    def preview(self, text: str) -> str:
        """The text exactly as `create` would store it; nothing is saved and no CAPTCHA is spent."""
        return self._clean(text)

    def create(self, data: NewComment, author: Author) -> Comment:
        """Validate markup, parent and attachment first, then spend the CAPTCHA, then save.

        The CAPTCHA is checked last so a typo in the text or a wrong file does not cost a new CAPTCHA.
        Only guests need a CAPTCHA: a signed-in author passed one when registering. An image is resized in the
        background after the commit.
        """
        text = self._clean(data.text)
        parent = self._parent(data.parent_id, author.viewer)
        checked = self._inspect(data.attachment)

        if author.user is None and not self.captcha.verify(data.captcha_key, data.captcha_answer):
            raise CaptchaInvalid('Wrong or expired CAPTCHA, enter the new one')

        comment = Comment(
            text=text,
            home_page=data.home_page,
            ip=author.ip,
            user_agent=author.user_agent,
            **self._identity(data, author),
        )
        comment.set_parent(parent)
        with transaction.atomic():
            # The parent's counter first: that takes its row lock before the INSERT. The other way round two
            # concurrent replies both hold the shared lock of the foreign-key check and deadlock on the UPDATE.
            # A shadowed reply is not counted: the counter must not reveal hidden comments to other people
            if parent is not None and not comment.is_shadowed:
                Comment.objects.filter(pk=parent.pk).update(replies_count=F('replies_count') + 1)
            comment.save()
            if checked is not None:
                attachment = self._attach(comment, data.attachment, checked)
                if checked.needs_processing:
                    transaction.on_commit(lambda: self.process_attachment(attachment.pk))
            transaction.on_commit(lambda: stats.comment_created(comment))
            transaction.on_commit(lambda: self.notifier.comment_created(comment))
            transaction.on_commit(lambda: self.index_comments([comment.pk]))
        return comment

    @staticmethod
    def _inspect(upload: UploadedFile | None) -> CheckedUpload | None:
        if upload is None:
            return None
        try:
            return inspect_upload(upload)
        except AttachmentRejected as error:
            raise InvalidAttachment(str(error)) from error

    @staticmethod
    def _attach(comment: Comment, upload: UploadedFile, checked: CheckedUpload) -> Attachment:
        attachment = Attachment(
            comment=comment,
            kind=checked.kind,
            original_name=(upload.name or '')[:255],
            size=upload.size,
            status=Attachment.Status.PROCESSING if checked.needs_processing else Attachment.Status.READY,
        )
        # ponytail: the file is written before the commit; a rolled-back transaction leaves it orphaned
        attachment.file.save(f'upload.{checked.extension}', upload, save=False)
        attachment.save()
        return attachment

    def _clean(self, text: str) -> str:
        try:
            return self.markup.clean(text)
        except MarkupError as error:
            raise InvalidMarkup(error) from error

    @staticmethod
    def _parent(parent_id: int | None, viewer: Viewer) -> Comment | None:
        if parent_id is None:
            return None
        parent = Comment.objects.visible_to(viewer).filter(pk=parent_id).first()
        if parent is None:
            raise ParentNotFound('The comment you reply to does not exist')
        return parent

    @staticmethod
    def _identity(data: NewComment, author: Author) -> dict:
        """A registered user always posts under the profile name and email; a guest under the form values."""
        if author.user is not None:
            return {
                'user': author.user,
                'user_name': author.user.username,
                'email': author.user.email,
                'is_shadowed': author.user.is_shadowbanned,
                'by_moderator': author.user.is_moderator,
            }
        from moderation.models import ShadowBan  # moderation builds on comments, not the other way round

        banned = ShadowBan.objects.matching_guest(author.guest_key, data.email).exists()
        return {'guest_key': author.guest_key, 'user_name': data.user_name, 'email': data.email,
                'is_shadowed': banned}

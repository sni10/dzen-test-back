"""Comment use cases. Views only translate HTTP to these calls; rules live here."""
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import F

from accounts.models import User
from captcha.service import CaptchaService

from .markup import CommentMarkup, MarkupError
from .models import Comment
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
    def __init__(self, markup: CommentMarkup, captcha: CaptchaService):
        self.markup = markup
        self.captcha = captcha

    def create(self, data: NewComment, author: Author) -> Comment:
        """Validate markup and parent first, then spend the CAPTCHA, then save.

        The CAPTCHA is checked last so a typo in the text does not cost the user a new CAPTCHA.
        Moderators post without a CAPTCHA.
        """
        try:
            text = self.markup.clean(data.text)
        except MarkupError as error:
            raise InvalidMarkup(error) from error

        parent = self._parent(data.parent_id, author.viewer)

        if not author.viewer.is_moderator and not self.captcha.verify(data.captcha_key, data.captcha_answer):
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
            comment.save()
            if parent is not None:
                Comment.objects.filter(pk=parent.pk).update(replies_count=F('replies_count') + 1)
        return comment

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
            }
        return {'guest_key': author.guest_key, 'user_name': data.user_name, 'email': data.email}

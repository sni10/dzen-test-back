import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from accounts.models import username_validator

from .querysets import CommentQuerySet


class Comment(models.Model):
    """A comment or a reply. Replies keep `root` (the top-level comment) to load a whole thread in one query.

    Author fields are a snapshot taken at posting time: guests have no account, and a later profile change
    must not rewrite old comments. `text` holds HTML that already passed validation and sanitizing.
    """

    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    root = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    depth = models.PositiveSmallIntegerField(default=0)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='comments',
    )
    guest_key = models.UUIDField(null=True, blank=True)
    user_name = models.CharField(max_length=50, validators=[username_validator])
    email = models.EmailField()
    home_page = models.URLField(blank=True)

    text = models.TextField()

    is_ufo = models.BooleanField(default=False)  # text hidden by a moderator ("UFO"), the card stays
    is_shadowed = models.BooleanField(default=False)  # the author is shadow-banned: visible only to them
    # Posted by a moderator: shown as a message from the administration. A snapshot like the author's name,
    # so a later role change does not rewrite old comments
    by_moderator = models.BooleanField(default=False)
    replies_count = models.PositiveIntegerField(default=0)  # direct replies, denormalized
    score = models.IntegerField(default=0)  # sum of counted votes, denormalized

    # Client identification; never exposed through the API
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        indexes = [
            # top-level table: parent IS NULL + every sortable column, id as the tie-breaker
            # Sorts of the feed; is_shadowed rides along so the visibility filter is answered by the index
            models.Index(fields=['parent', 'created_at', 'id', 'is_shadowed'], name='comment_feed_created'),
            models.Index(fields=['parent', 'user_name', 'id', 'is_shadowed'], name='comment_feed_user_name'),
            models.Index(fields=['parent', 'email', 'id', 'is_shadowed'], name='comment_feed_email'),
            models.Index(fields=['root', 'created_at', 'id'], name='comment_thread'),
            # Covering indexes for the counters (comments/stats.py): index scans, not a million rows
            models.Index(fields=['is_shadowed', 'is_ufo'], name='comment_shadowed_ufo'),
            models.Index(fields=['guest_key', 'is_shadowed'], name='comment_guest_shadowed'),
            # A guest's shadow ban finds their comments by the cookie or the e-mail
            models.Index(fields=['email'], name='comment_email'),
        ]

    def __str__(self):
        return f'#{self.pk} by {self.user_name}'

    @property
    def is_top_level(self) -> bool:
        return self.parent_id is None

    def set_parent(self, parent: 'Comment | None') -> None:
        """Place the comment in the tree: a reply inherits the thread root and goes one level deeper."""
        self.parent = parent
        if parent is None:
            self.root = None
            self.depth = 0
        else:
            self.root_id = parent.root_id or parent.pk
            self.depth = parent.depth + 1


def attachment_path(instance: 'Attachment', filename: str) -> str:
    """Random stored name: the user's file name is kept only in `original_name`."""
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    name = uuid.uuid4().hex
    return f'attachments/{name[:2]}/{name}.{extension}' if extension else f'attachments/{name[:2]}/{name}'


class Attachment(models.Model):
    class Kind(models.TextChoices):
        IMAGE = 'image', 'Image'  # JPG / GIF / PNG, fitted into 320x240
        TEXT = 'text', 'Text'  # TXT up to 100 KB

    class Status(models.TextChoices):
        PROCESSING = 'processing', 'Processing'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='attachments')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file = models.FileField(upload_to=attachment_path, max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()  # bytes, of the stored file
    width = models.PositiveSmallIntegerField(null=True, blank=True)
    height = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROCESSING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.kind} {self.original_name} (comment #{self.comment_id})'


class CommentVote(models.Model):
    class Value(models.IntegerChoices):
        UP = 1, 'Up'
        DOWN = -1, 'Down'

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comment_votes')
    value = models.SmallIntegerField(choices=Value.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['comment', 'user'], name='vote_one_per_user'),
            models.CheckConstraint(condition=Q(value__in=[1, -1]), name='vote_value_plus_minus_one'),
        ]

    def __str__(self):
        return f'{self.value:+d} by user #{self.user_id} on comment #{self.comment_id}'


class Bookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmarks')
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'comment'], name='bookmark_once_per_user')]
        indexes = [models.Index(fields=['user', '-created_at'], name='bookmark_user_recent')]

    def __str__(self):
        return f'user #{self.user_id} -> comment #{self.comment_id}'

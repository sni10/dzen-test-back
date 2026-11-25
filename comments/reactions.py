"""Votes and bookmarks of signed-in users.

`Comment.score` is the sum of counted votes, kept in step with the vote rows inside one transaction (the vote
row is locked, the score moves by the difference with an F() expression, so parallel votes never lose an
update). A shadow-banned user's vote is stored — they see their own arrow — but never counted.
"""
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F

from accounts.models import User

from .live import Notifier
from .models import Bookmark, Comment, CommentVote
from .viewer import Viewer


class ReactionError(Exception):
    def __init__(self, message: str, field: str = 'commentId'):
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass(frozen=True)
class VoteResult:
    comment_id: int
    score: int
    my_vote: int | None


class ReactionService:
    def __init__(self, notifier: Notifier):
        self.notifier = notifier

    @staticmethod
    def _comment(user: User, comment_id: int) -> Comment:
        comment = Comment.objects.visible_to(Viewer.of(user)).filter(pk=comment_id).first()
        if comment is None:
            raise ReactionError('The comment does not exist')
        return comment

    def vote(self, user: User, comment_id: int, value: int | None) -> VoteResult:
        """value: 1 / -1 to vote, None to take the vote back. Voting the same way again changes nothing."""
        if value not in (1, -1, None):
            raise ReactionError('A vote is 1 or -1', field='value')
        comment = self._comment(user, comment_id)
        if comment.user_id == user.pk:
            raise ReactionError('You cannot vote for your own comment')

        with transaction.atomic():
            existing = CommentVote.objects.select_for_update().filter(comment=comment, user=user).first()
            old = existing.value if existing else 0
            if value is None:
                if existing:
                    existing.delete()
            elif existing:
                existing.value = value
                existing.save(update_fields=['value', 'updated_at'])
            else:
                CommentVote.objects.create(comment=comment, user=user, value=value)

            delta = 0 if user.is_shadowbanned else (value or 0) - old
            if delta:
                Comment.objects.filter(pk=comment.pk).update(score=F('score') + delta)
                transaction.on_commit(lambda: self.notifier.score_changed(comment))
        comment.refresh_from_db(fields=['score'])
        return VoteResult(comment.pk, comment.score, value)

    def set_bookmark(self, user: User, comment_id: int, on: bool) -> bool:
        comment = self._comment(user, comment_id)
        if on:
            Bookmark.objects.get_or_create(user=user, comment=comment)
        else:
            Bookmark.objects.filter(user=user, comment=comment).delete()
        return on

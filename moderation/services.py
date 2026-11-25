"""Moderation use cases: hide a comment's text ("UFO") and shadow-ban its author.

Counters stay honest after every change: replies_count of parents and scores of comments the author voted on
are recounted, so no number gives a hidden comment or a shadowed vote away.
"""
from collections.abc import Callable

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from accounts.models import User
from comments import stats
from comments.live import Notifier
from comments.models import Comment, CommentVote

from .models import ModerationAction, ShadowBan


class ModerationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _comment(comment_id: int) -> Comment:
    comment = Comment.objects.select_related('user').filter(pk=comment_id).first()
    if comment is None:
        raise ModerationError('The comment does not exist')
    return comment


def author_comments(ban: ShadowBan):
    if ban.user_id is not None:
        return Comment.objects.filter(user_id=ban.user_id)
    return Comment.objects.filter(user__isnull=True).filter(Q(guest_key=ban.guest_key) | Q(email__iexact=ban.email))


def recount_replies(parent_ids) -> None:
    """replies_count counts visible replies only. A loop: MySQL cannot update a table from a subquery on itself."""
    for parent_id in set(parent_ids) - {None}:
        visible = Comment.objects.filter(parent_id=parent_id, is_shadowed=False).count()
        Comment.objects.filter(pk=parent_id).update(replies_count=visible)


def recount_scores(comment_ids) -> None:
    """score counts votes of users who are not shadow-banned."""
    for comment_id in set(comment_ids):
        total = (CommentVote.objects.filter(comment_id=comment_id, user__is_shadowbanned=False)
                 .aggregate(total=Sum('value'))['total'] or 0)
        Comment.objects.filter(pk=comment_id).update(score=total)


class ModerationService:
    def __init__(self, notifier: Notifier, index_comments: Callable[[list[int]], None] = lambda ids: None):
        self.notifier = notifier
        self.index_comments = index_comments  # queues search re-indexing (visibility changed)

    def _log(self, moderator: User, kind: str, **fields) -> None:
        ModerationAction.objects.create(moderator=moderator, kind=kind, **fields)

    def ufo(self, moderator: User, comment_id: int, reason: str = '') -> Comment:
        """Hide the text and attachments for everyone; the card, the author and the replies stay."""
        with transaction.atomic():
            comment = _comment(comment_id)
            if comment.is_ufo:
                raise ModerationError('The comment is already hidden')
            comment.is_ufo = True
            comment.save(update_fields=['is_ufo'])
            self._log(moderator, ModerationAction.Kind.UFO, comment=comment, original_text=comment.text,
                      reason=reason)
            self._after_commit(comment)
        return comment

    def restore(self, moderator: User, comment_id: int) -> Comment:
        with transaction.atomic():
            comment = _comment(comment_id)
            if not comment.is_ufo:
                raise ModerationError('The comment is not hidden')
            comment.is_ufo = False
            comment.save(update_fields=['is_ufo'])
            self._log(moderator, ModerationAction.Kind.RESTORE, comment=comment)
            self._after_commit(comment)
        return comment

    def shadowban(self, moderator: User, comment_id: int, hide_past: bool = True, reason: str = '') -> ShadowBan:
        """Ban the author of a comment. New comments of theirs are shadowed; with hide_past the old ones too."""
        with transaction.atomic():
            comment = _comment(comment_id)
            author = comment.user
            if author is not None and author.is_moderator:
                raise ModerationError('A moderator cannot be banned')
            if author is not None:
                active = ShadowBan.objects.active().filter(user=author)
            else:
                active = ShadowBan.objects.matching_guest(comment.guest_key, comment.email)
            if active.exists():
                raise ModerationError('The author is already banned')

            ban = ShadowBan.objects.create(
                user=author,
                guest_key=None if author else comment.guest_key,
                email=author.email if author else comment.email,
                user_name=author.username if author else comment.user_name,
                reason=reason,
                created_by=moderator,
            )
            if author is not None:
                User.objects.filter(pk=author.pk).update(is_shadowbanned=True)
                recount_scores(CommentVote.objects.filter(user=author).values_list('comment_id', flat=True))
            if hide_past:
                changed = self._set_shadowed(author_comments(ban), True)
                transaction.on_commit(lambda: self.index_comments(changed))
            self._log(moderator, ModerationAction.Kind.SHADOWBAN, comment=comment, shadow_ban=ban, reason=reason)
            transaction.on_commit(stats.invalidate)
        return ban

    def unban(self, moderator: User, ban_id: int) -> ShadowBan:
        """Lift the ban: the author's comments become visible again and their votes count."""
        with transaction.atomic():
            ban = ShadowBan.objects.active().filter(pk=ban_id).first()
            if ban is None:
                raise ModerationError('No such active ban')
            ban.lifted_at = timezone.now()
            ban.save(update_fields=['lifted_at'])
            if ban.user_id is not None:
                User.objects.filter(pk=ban.user_id).update(is_shadowbanned=False)
                recount_scores(CommentVote.objects.filter(user_id=ban.user_id).values_list('comment_id', flat=True))
            changed = self._set_shadowed(author_comments(ban), False)
            transaction.on_commit(lambda: self.index_comments(changed))
            self._log(moderator, ModerationAction.Kind.UNBAN, shadow_ban=ban)
            transaction.on_commit(stats.invalidate)
        return ban

    @staticmethod
    def _set_shadowed(comments, shadowed: bool) -> list[int]:
        changing = comments.filter(is_shadowed=not shadowed)
        rows = list(changing.values_list('pk', 'parent_id'))
        changing.update(is_shadowed=shadowed)
        recount_replies(parent_id for _, parent_id in rows)
        return [pk for pk, _ in rows]

    def _after_commit(self, comment: Comment) -> None:
        transaction.on_commit(stats.invalidate)
        transaction.on_commit(lambda: self.notifier.comment_updated(comment))
        transaction.on_commit(lambda: self.index_comments([comment.pk]))

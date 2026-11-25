"""Moderation in GraphQL: moderators only."""
from __future__ import annotations

from datetime import datetime
from functools import cache
from typing import TYPE_CHECKING

import strawberry
from asgiref.sync import sync_to_async
from graphql import GraphQLError

from accounts.graphql import signed_in
from comments.container import notifier
from comments.tasks import index_comments
from comments.graphql.types import CommentType, parse_id
from comments.models import Comment

from .models import ShadowBan
from .services import ModerationError, ModerationService, author_comments

if TYPE_CHECKING:
    from config.graphql import Context


@cache
def moderation_service() -> ModerationService:
    return ModerationService(notifier=notifier(), index_comments=index_comments.delay)


def moderator(info: strawberry.Info[Context]):
    user = signed_in(info)
    if not user.is_moderator:
        raise GraphQLError('Moderators only', extensions={'code': 'FORBIDDEN'})
    return user


async def _call(fn, *args):
    try:
        return await sync_to_async(fn)(*args)
    except ModerationError as error:
        raise GraphQLError(error.message, extensions={'code': 'BAD_USER_INPUT'}) from None


@strawberry.type(name='ShadowBan')
class ShadowBanType:
    id: strawberry.ID
    user_name: str
    email: str
    is_guest: bool
    reason: str
    created_at: datetime
    lifted_at: datetime | None
    comments_count: int = strawberry.field(description="The author's comments hidden by the ban")

    @classmethod
    def from_model(cls, ban: ShadowBan) -> ShadowBanType:
        return cls(
            id=strawberry.ID(str(ban.pk)),
            user_name=ban.user_name,
            email=ban.email,
            is_guest=ban.user_id is None,
            reason=ban.reason,
            created_at=ban.created_at,
            lifted_at=ban.lifted_at,
            comments_count=author_comments(ban).filter(is_shadowed=True).count(),
        )


def _active_bans() -> list[ShadowBanType]:
    return [ShadowBanType.from_model(ban) for ban in ShadowBan.objects.active().order_by('-created_at')]


def _comment_type(comment: Comment) -> CommentType:
    return CommentType.from_model(Comment.objects.get(pk=comment.pk))


@strawberry.type
class ModerationQuery:
    @strawberry.field(description='Active shadow bans, the latest first')
    async def shadow_bans(self, info: strawberry.Info[Context]) -> list[ShadowBanType]:
        moderator(info)
        return await sync_to_async(_active_bans)()


@strawberry.type
class ModerationMutation:
    @strawberry.mutation(description='"A UFO flew in": hide the text and attachments; the card and replies stay')
    async def ufo_comment(self, info: strawberry.Info[Context], comment_id: strawberry.ID,
                          reason: str = '') -> CommentType:
        comment = await _call(moderation_service().ufo, moderator(info), parse_id(comment_id, 'commentId'), reason)
        return await sync_to_async(_comment_type)(comment)

    @strawberry.mutation(description='Show the hidden text again')
    async def restore_comment(self, info: strawberry.Info[Context], comment_id: strawberry.ID) -> CommentType:
        comment = await _call(moderation_service().restore, moderator(info), parse_id(comment_id, 'commentId'))
        return await sync_to_async(_comment_type)(comment)

    @strawberry.mutation(description="Shadow-ban the comment's author (account, or the guest's cookie and e-mail)")
    async def shadowban(self, info: strawberry.Info[Context], comment_id: strawberry.ID, hide_past: bool = True,
                        reason: str = '') -> ShadowBanType:
        ban = await _call(moderation_service().shadowban, moderator(info), parse_id(comment_id, 'commentId'),
                          hide_past, reason)
        return await sync_to_async(ShadowBanType.from_model)(ban)

    @strawberry.mutation(description="Lift a ban: the author's comments are visible again")
    async def unban(self, info: strawberry.Info[Context], ban_id: strawberry.ID) -> ShadowBanType:
        ban = await _call(moderation_service().unban, moderator(info), parse_id(ban_id, 'banId'))
        return await sync_to_async(ShadowBanType.from_model)(ban)

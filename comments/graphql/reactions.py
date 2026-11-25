"""Votes and bookmarks in GraphQL (signed-in users)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import strawberry
from asgiref.sync import sync_to_async

from accounts.graphql import field_error, signed_in
from comments.container import reaction_service
from comments.models import Comment
from comments.reactions import ReactionError
from comments.viewer import Viewer

from .queries import comment_page
from .types import CommentPage, parse_id

if TYPE_CHECKING:
    from config.graphql import Context


@strawberry.type
class VoteResult:
    comment_id: strawberry.ID
    score: int
    my_vote: int | None = strawberry.field(description='1, -1 or null after taking the vote back')


async def _call(fn, *args):
    try:
        return await sync_to_async(fn)(*args)
    except ReactionError as error:
        raise field_error(error.field, error.message) from None


def _bookmarks(user, page: int) -> CommentPage:
    comments = (Comment.objects.visible_to(Viewer.of(user))
                .filter(bookmarks__user=user).order_by('-bookmarks__created_at', '-id'))
    return comment_page(comments, page)


@strawberry.type
class ReactionQuery:
    @strawberry.field(description='Comments I bookmarked, the latest bookmark first, 25 per page')
    async def my_bookmarks(self, info: strawberry.Info[Context], page: int = 1) -> CommentPage:
        return await sync_to_async(_bookmarks)(signed_in(info), page)


@strawberry.type
class ReactionMutation:
    @strawberry.mutation(description='Vote 1 or -1; voting again the other way changes the vote')
    async def vote(self, info: strawberry.Info[Context], comment_id: strawberry.ID, value: int) -> VoteResult:
        result = await _call(reaction_service().vote, signed_in(info), parse_id(comment_id, 'commentId'), value)
        return VoteResult(comment_id=comment_id, score=result.score, my_vote=result.my_vote)

    @strawberry.mutation(description='Take my vote back')
    async def unvote(self, info: strawberry.Info[Context], comment_id: strawberry.ID) -> VoteResult:
        result = await _call(reaction_service().vote, signed_in(info), parse_id(comment_id, 'commentId'), None)
        return VoteResult(comment_id=comment_id, score=result.score, my_vote=None)

    @strawberry.mutation(description='Add to my bookmarks; returns true')
    async def bookmark(self, info: strawberry.Info[Context], comment_id: strawberry.ID) -> bool:
        return await _call(reaction_service().set_bookmark, signed_in(info), parse_id(comment_id, 'commentId'), True)

    @strawberry.mutation(description='Remove from my bookmarks; returns false')
    async def unbookmark(self, info: strawberry.Info[Context], comment_id: strawberry.ID) -> bool:
        return await _call(reaction_service().set_bookmark, signed_in(info), parse_id(comment_id, 'commentId'),
                           False)


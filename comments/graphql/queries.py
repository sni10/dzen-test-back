from __future__ import annotations

import math
from typing import TYPE_CHECKING

import strawberry
from asgiref.sync import sync_to_async
from graphql import GraphQLError

from comments.models import Comment
from comments.viewer import Viewer

from .types import CommentPage, CommentSort, CommentType, parse_id

if TYPE_CHECKING:
    from config.graphql import Context

PAGE_SIZE = 25  # the assignment: 25 top-level comments per page
MAX_SINCE = 100


def _feed_page(viewer: Viewer, page: int, sort: CommentSort) -> CommentPage:
    feed = Comment.objects.top_level().visible_to(viewer)
    total = feed.count()
    offset = (page - 1) * PAGE_SIZE
    rows = list(feed.sorted_by(sort.value)[offset:offset + PAGE_SIZE])
    return CommentPage(
        items=[CommentType.from_model(comment) for comment in rows],
        total_count=total,
        page=page,
        page_size=PAGE_SIZE,
        page_count=max(1, math.ceil(total / PAGE_SIZE)),
    )


def _since(viewer: Viewer, last_id: int, limit: int) -> list[CommentType]:
    rows = Comment.objects.visible_to(viewer).since(last_id)[:limit]
    return [CommentType.from_model(comment) for comment in rows]


@strawberry.type
class CommentQuery:
    @strawberry.field(description=f'Top-level comments, {PAGE_SIZE} per page')
    async def comments(
        self, info: strawberry.Info[Context], page: int = 1, sort: CommentSort = CommentSort.CREATED_AT_DESC,
    ) -> CommentPage:
        if page < 1:
            raise GraphQLError('page must be 1 or greater')
        return await sync_to_async(_feed_page)(info.context.viewer, page, sort)

    @strawberry.field(description='One comment (a thread link); null if it does not exist or is hidden')
    async def comment(self, info: strawberry.Info[Context], id: strawberry.ID) -> CommentType | None:
        comment = await info.context.loaders.by_id.load(parse_id(id, 'id'))
        return CommentType.from_model(comment) if comment else None

    @strawberry.field(description=f'Comments posted after lastId, oldest first (after a WebSocket reconnect); '
                                  f'limit <= {MAX_SINCE}')
    async def comments_since(
        self, info: strawberry.Info[Context], last_id: strawberry.ID, limit: int = MAX_SINCE,
    ) -> list[CommentType]:
        if not 1 <= limit <= MAX_SINCE:
            raise GraphQLError(f'limit must be between 1 and {MAX_SINCE}')
        return await sync_to_async(_since)(info.context.viewer, parse_id(last_id, 'lastId'), limit)

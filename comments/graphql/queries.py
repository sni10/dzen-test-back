from __future__ import annotations

import math
from typing import TYPE_CHECKING

import strawberry
from asgiref.sync import sync_to_async
from graphql import GraphQLError

from comments.models import Comment
from comments.search import PAGE_SIZE as SEARCH_PAGE_SIZE
from comments.stats import stats_for
from comments.viewer import Viewer

from .types import CommentPage, CommentSort, CommentType, parse_id

if TYPE_CHECKING:
    from config.graphql import Context

PAGE_SIZE = 25  # the assignment: 25 top-level comments per page
MAX_SINCE = 100


def comment_page(comments, page: int) -> CommentPage:
    """One page of an already filtered and ordered queryset (the feed, a user's own comments)."""
    if page < 1:
        raise GraphQLError('page must be 1 or greater')
    total = comments.count()
    offset = (page - 1) * PAGE_SIZE
    rows = list(comments[offset:offset + PAGE_SIZE])
    return CommentPage(
        items=[CommentType.from_model(comment) for comment in rows],
        total_count=total,
        page=page,
        page_size=PAGE_SIZE,
        page_count=max(1, math.ceil(total / PAGE_SIZE)),
    )


def _feed_page(viewer: Viewer, page: int, sort: CommentSort) -> CommentPage:
    return comment_page(Comment.objects.top_level().visible_to(viewer).sorted_by(sort.value), page)


def _since(viewer: Viewer, last_id: int, limit: int) -> list[CommentType]:
    rows = Comment.objects.visible_to(viewer).since(last_id)[:limit]
    return [CommentType.from_model(comment) for comment in rows]


@strawberry.type
class StatsType:
    comments: int = strawberry.field(description='Comments this viewer can see')
    ufo: int = strawberry.field(description='Hidden by a moderator')
    shadowed: int = strawberry.field(description="Shadow-banned authors' comments (public on purpose)")
    my_comments: int | None = strawberry.field(description='Signed-in users only')
    my_bookmarks: int | None = strawberry.field(description='Signed-in users only')


@strawberry.type
class SearchHit:
    comment: CommentType
    highlight: str | None = strawberry.field(
        description='HTML snippet of the matching text: escaped, with <mark> around the matches')


@strawberry.type
class SearchPage:
    items: list[SearchHit]
    total_count: int
    page: int
    page_count: int


MAX_QUERY_LENGTH = 200


def _search(viewer: Viewer, query: str, page: int) -> SearchPage:
    from comments.container import search_index

    try:
        found = search_index().search(query, viewer, page)
    except Exception as error:  # the database keeps working when the search cluster does not
        raise GraphQLError('Search is unavailable, try again later',
                           extensions={'code': 'SEARCH_UNAVAILABLE'}) from error
    # Load from the database in the index's order, through the same visibility rule as everything else
    comments = Comment.objects.visible_to(viewer).in_bulk(found.ids)
    items = [SearchHit(comment=CommentType.from_model(comments[pk]), highlight=found.highlights.get(pk))
             for pk in found.ids if pk in comments]
    return SearchPage(items=items, total_count=found.total, page=page,
                      page_count=max(1, math.ceil(found.total / SEARCH_PAGE_SIZE)))


@strawberry.type
class CommentQuery:
    @strawberry.field(description=f'Full-text search (Russian and English word forms), {SEARCH_PAGE_SIZE} per page')
    async def search(self, info: strawberry.Info[Context], query: str, page: int = 1) -> SearchPage:
        query = query.strip()
        if not query:
            raise GraphQLError('Type something to search for')
        if len(query) > MAX_QUERY_LENGTH:
            raise GraphQLError(f'At most {MAX_QUERY_LENGTH} characters')
        if page < 1:
            raise GraphQLError('page must be 1 or greater')
        return await sync_to_async(_search)(info.context.viewer, query, page)

    @strawberry.field(description='Counters for the stats cards; what a viewer may not know is null')
    async def stats(self, info: strawberry.Info[Context]) -> StatsType:
        found = await sync_to_async(stats_for)(info.context.viewer)
        return StatsType(comments=found.comments, ufo=found.ufo, shadowed=found.shadowed,
                         my_comments=found.my_comments, my_bookmarks=found.my_bookmarks)

    @strawberry.field(description=f'Top-level comments, {PAGE_SIZE} per page')
    async def comments(
        self, info: strawberry.Info[Context], page: int = 1, sort: CommentSort = CommentSort.CREATED_AT_DESC,
    ) -> CommentPage:
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

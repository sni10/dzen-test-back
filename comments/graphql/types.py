from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import strawberry
from graphql import GraphQLError

from comments.models import Attachment, Comment

from .loaders import RepliesKey

if TYPE_CHECKING:
    from config.graphql import Context

MAX_FIRST = 50


@strawberry.enum(description='Columns of the top-level table; the default is CREATED_AT_DESC (LIFO)')
class CommentSort(Enum):
    USER_NAME_ASC = 'user_name'
    USER_NAME_DESC = '-user_name'
    EMAIL_ASC = 'email'
    EMAIL_DESC = '-email'
    CREATED_AT_ASC = 'created_at'
    CREATED_AT_DESC = '-created_at'


def parse_id(value: strawberry.ID | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GraphQLError(f'{name} must be a comment id') from None
    if number < 1:
        raise GraphQLError(f'{name} must be a comment id')
    return number


def check_first(first: int) -> int:
    if not 1 <= first <= MAX_FIRST:
        raise GraphQLError(f'first must be between 1 and {MAX_FIRST}')
    return first


@strawberry.type(name='Attachment')
class AttachmentType:
    id: strawberry.ID
    kind: str = strawberry.field(description='image (fitted into 320x240) or text (TXT up to 100 KB)')
    url: str = strawberry.field(description='Relative URL on the same origin (/media/...)')
    original_name: str
    size: int = strawberry.field(description='Bytes of the stored file')
    width: int | None
    height: int | None
    status: str = strawberry.field(description='processing (image being resized), ready or failed')

    @classmethod
    def from_model(cls, attachment: Attachment) -> AttachmentType:
        return cls(
            id=strawberry.ID(str(attachment.pk)),
            kind=attachment.kind,
            url=attachment.file.url,
            original_name=attachment.original_name,
            size=attachment.size,
            width=attachment.width,
            height=attachment.height,
            status=attachment.status,
        )


@strawberry.type(name='Comment')
class CommentType:
    id: strawberry.ID
    user_name: str
    email: str
    home_page: str
    text: str = strawberry.field(description='Sanitized HTML: only <a>, <code>, <i>, <strong>')
    is_ufo: bool = strawberry.field(description='Text hidden by a moderator; the card stays')
    by_moderator: bool = strawberry.field(description='A message from the administration')
    score: int
    replies_count: int = strawberry.field(description='Direct replies visible to everyone')
    depth: int = strawberry.field(description='0 for a top-level comment')
    created_at: datetime
    parent_id: strawberry.ID | None
    root_id: strawberry.ID | None = strawberry.field(description='The top-level comment of the thread')
    author_id: strawberry.Private[int | None]  # never in the schema
    raw_text: strawberry.Private[str]  # the text even when hidden by a moderator: for moderators only
    shadowed: strawberry.Private[bool]

    @classmethod
    def from_model(cls, comment: Comment) -> CommentType:
        return cls(
            id=strawberry.ID(str(comment.pk)),
            user_name=comment.user_name,
            email=comment.email,
            home_page=comment.home_page,
            text='' if comment.is_ufo else comment.text,  # the hidden text never leaves the server
            is_ufo=comment.is_ufo,
            by_moderator=comment.by_moderator,
            score=comment.score,
            replies_count=comment.replies_count,
            depth=comment.depth,
            created_at=comment.created_at,
            parent_id=strawberry.ID(str(comment.parent_id)) if comment.parent_id else None,
            root_id=strawberry.ID(str(comment.root_id)) if comment.root_id else None,
            author_id=comment.user_id,
            raw_text=comment.text,
            shadowed=comment.is_shadowed,
        )

    @strawberry.field(description='The text hidden by a moderator; moderators only, otherwise null')
    def original_text(self, info: strawberry.Info[Context]) -> str | None:
        return self.raw_text if self.is_ufo and info.context.viewer.is_moderator else None

    @strawberry.field(description='The author is shadow-banned; moderators only, otherwise null')
    def is_shadowed(self, info: strawberry.Info[Context]) -> bool | None:
        return self.shadowed if info.context.viewer.is_moderator else None

    @strawberry.field(description='Posted by me (signed-in viewers): no voting on own comments')
    def is_mine(self, info: strawberry.Info[Context]) -> bool:
        return self.author_id is not None and self.author_id == info.context.viewer.user_id

    @strawberry.field(description='My vote: 1, -1 or null (always null for guests)')
    async def my_vote(self, info: strawberry.Info[Context]) -> int | None:
        if info.context.viewer.user_id is None:
            return None
        return await info.context.loaders.my_votes.load(int(self.id))

    @strawberry.field(description='In my bookmarks (always false for guests)')
    async def bookmarked(self, info: strawberry.Info[Context]) -> bool:
        if info.context.viewer.user_id is None:
            return False
        return await info.context.loaders.bookmarked.load(int(self.id))

    @strawberry.field(description='Files attached to the comment (at most one at the moment)')
    async def attachments(self, info: strawberry.Info[Context]) -> list[AttachmentType]:
        if self.is_ufo:
            return []  # hidden by a moderator together with the text
        found = await info.context.loaders.attachments.load(int(self.id))
        return [AttachmentType.from_model(attachment) for attachment in found]

    @strawberry.field(description='The comment this one replies to (for the quote); null for top-level')
    async def parent(self, info: strawberry.Info[Context]) -> CommentType | None:
        if self.parent_id is None:
            return None
        parent = await info.context.loaders.by_id.load(int(self.parent_id))
        return CommentType.from_model(parent) if parent else None

    @strawberry.field(description=f'Direct replies, oldest first; first <= {MAX_FIRST}, `after` = endCursor')
    async def replies(
        self, info: strawberry.Info[Context], first: int = 10, after: strawberry.ID | None = None,
    ) -> ReplyPage:
        key = RepliesKey(int(self.id), check_first(first), parse_id(after, 'after'))
        replies = await info.context.loaders.replies.load(key)
        items = [CommentType.from_model(reply) for reply in replies.items]
        return ReplyPage(items=items, has_more=replies.has_more, end_cursor=items[-1].id if items else after)


@strawberry.type
class ReplyPage:
    items: list[CommentType]
    has_more: bool
    end_cursor: strawberry.ID | None = strawberry.field(description='Pass as `after` to load the next replies')


@strawberry.type
class CommentPage:
    items: list[CommentType]
    total_count: int
    page: int
    page_size: int
    page_count: int

"""DataLoaders: nested fields of many comments are loaded in one query per level, not one per comment (N+1)."""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple

from asgiref.sync import sync_to_async
from strawberry.dataloader import DataLoader

from comments.models import Attachment, Bookmark, Comment, CommentVote
from comments.viewer import Viewer


class RepliesKey(NamedTuple):
    parent_id: int
    first: int
    after: int | None


class RepliesSlice(NamedTuple):
    items: list[Comment]
    has_more: bool


@dataclass
class CommentLoaders:
    """One set per request: results are cached for the request and respect what this viewer may see."""

    viewer: Viewer
    by_id: DataLoader[int, Comment | None] = field(init=False)
    replies: DataLoader[RepliesKey, RepliesSlice] = field(init=False)
    attachments: DataLoader[int, list[Attachment]] = field(init=False)
    my_votes: DataLoader[int, int | None] = field(init=False)
    bookmarked: DataLoader[int, bool] = field(init=False)

    def __post_init__(self):
        self.by_id = DataLoader(load_fn=self._load_by_id)
        self.replies = DataLoader(load_fn=self._load_replies)
        self.attachments = DataLoader(load_fn=self._load_attachments)
        self.my_votes = DataLoader(load_fn=self._load_my_votes)
        self.bookmarked = DataLoader(load_fn=self._load_bookmarked)

    async def _load_my_votes(self, comment_ids: list[int]) -> list[int | None]:
        """The viewer's own vote on each comment (only asked for signed-in viewers)."""
        votes = await sync_to_async(lambda: dict(CommentVote.objects.filter(
            user_id=self.viewer.user_id, comment_id__in=comment_ids).values_list('comment_id', 'value')))()
        return [votes.get(pk) for pk in comment_ids]

    async def _load_bookmarked(self, comment_ids: list[int]) -> list[bool]:
        marked = await sync_to_async(lambda: set(Bookmark.objects.filter(
            user_id=self.viewer.user_id, comment_id__in=comment_ids).values_list('comment_id', flat=True)))()
        return [pk in marked for pk in comment_ids]

    async def _load_attachments(self, comment_ids: list[int]) -> list[list[Attachment]]:
        return await sync_to_async(self._attachments)(comment_ids)

    @staticmethod
    def _attachments(comment_ids: list[int]) -> list[list[Attachment]]:
        found: dict[int, list[Attachment]] = defaultdict(list)
        for attachment in Attachment.objects.filter(comment_id__in=comment_ids).order_by('id'):
            found[attachment.comment_id].append(attachment)
        return [found[pk] for pk in comment_ids]

    async def _load_by_id(self, ids: list[int]) -> list[Comment | None]:
        comments = await sync_to_async(self._comments_by_id)(ids)
        return [comments.get(pk) for pk in ids]

    def _comments_by_id(self, ids: list[int]) -> dict[int, Comment]:
        return {comment.pk: comment for comment in Comment.objects.visible_to(self.viewer).filter(pk__in=ids)}

    async def _load_replies(self, keys: list[RepliesKey]) -> list[RepliesSlice]:
        return await sync_to_async(self._replies)(keys)

    def _replies(self, keys: list[RepliesKey]) -> list[RepliesSlice]:
        # Keys asking for the same page size/cursor share one query; usually that is all of them
        groups: dict[tuple[int, int | None], set[int]] = defaultdict(set)
        for key in keys:
            groups[(key.first, key.after)].add(key.parent_id)

        found: dict[RepliesKey, list[Comment]] = defaultdict(list)
        for (first, after), parent_ids in groups.items():
            # one extra row per parent tells whether there is a next page
            rows = Comment.objects.visible_to(self.viewer).replies_of(parent_ids, first + 1, after)
            for reply in rows:
                found[RepliesKey(reply.parent_id, first, after)].append(reply)

        return [RepliesSlice(found[key][:key.first], len(found[key]) > key.first) for key in keys]

"""Counters for the stats cards. The shared part is cached in Redis and dropped whenever it changes
(a new comment now, moderation later); the per-viewer part is counted every time."""
from dataclasses import dataclass

from django.core.cache import cache
from django.db.models import Count, Q

from .models import Bookmark, Comment
from .viewer import Viewer

CACHE_KEY = 'comments:stats'
CACHE_SECONDS = 60  # a safety net: every change drops the key anyway


@dataclass(frozen=True)
class Stats:
    comments: int  # what this viewer can see
    ufo: int  # hidden by a moderator: the placeholders are public anyway
    shadowed: int | None  # moderators only: telling anyone else would give the shadow ban away
    my_comments: int | None  # signed-in users
    my_bookmarks: int | None


def _shared() -> dict[str, int]:
    counts = cache.get(CACHE_KEY)
    if counts is None:
        counts = Comment.objects.aggregate(
            public=Count('id', filter=Q(is_shadowed=False)),
            ufo=Count('id', filter=Q(is_ufo=True, is_shadowed=False)),
            shadowed=Count('id', filter=Q(is_shadowed=True)),
        )
        cache.set(CACHE_KEY, counts, CACHE_SECONDS)
    return counts


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def stats_for(viewer: Viewer) -> Stats:
    shared = _shared()
    if viewer.is_moderator:
        visible = shared['public'] + shared['shadowed']
    elif viewer.user_id is not None or viewer.guest_key is not None:
        # an author in the shadow ban sees their own hidden comments, so they count for them
        own = Q(user_id=viewer.user_id) if viewer.user_id is not None else Q(guest_key=viewer.guest_key)
        visible = shared['public'] + Comment.objects.filter(own, is_shadowed=True).count()
    else:
        visible = shared['public']

    signed_in = viewer.user_id is not None
    return Stats(
        comments=visible,
        ufo=shared['ufo'],
        shadowed=shared['shadowed'] if viewer.is_moderator else None,
        my_comments=Comment.objects.filter(user_id=viewer.user_id).count() if signed_in else None,
        my_bookmarks=Bookmark.objects.filter(user_id=viewer.user_id).count() if signed_in else None,
    )

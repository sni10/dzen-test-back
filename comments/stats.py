"""Counters: the stats cards and the number of pages of the feed.

Counting a million rows on every request is what does not scale, so the shared counters live in Redis.
A new comment increments them in place (atomic INCR); moderation, which may change many rows, drops them
and the next read recounts (covering indexes keep that to an index scan). The per-viewer part (own shadowed
comments, own comments, bookmarks) is a small indexed count every time.
"""
from dataclasses import dataclass

from django.core.cache import cache
from django.db.models import Count, Q

from .models import Bookmark, Comment
from .viewer import Viewer

PREFIX = 'comments:count:'
NAMES = ('public', 'ufo', 'shadowed', 'top_public', 'top_shadowed')
KEYS = [PREFIX + name for name in NAMES]
# No expiry: an expiring key under load means every request at that moment recounting a million rows at once
# (seen in the load test). Increments keep the counters current, moderation drops them for a recount.
# ponytail: an increment racing a recount can leave a counter off by one until the next moderation;
# exact enough for a page count and the cards
CACHE_SECONDS = None


@dataclass(frozen=True)
class Stats:
    comments: int  # what this viewer can see
    ufo: int  # hidden by a moderator: the placeholders are public anyway
    shadowed: int  # public on purpose: everyone sees how many comments are under a shadow ban
    my_comments: int | None  # signed-in users
    my_bookmarks: int | None


def _shared() -> dict[str, int]:
    found = cache.get_many(KEYS)
    if len(found) == len(KEYS):
        return {name: found[PREFIX + name] for name in NAMES}
    # Two grouped counts, each answered by an index alone (comment_shadowed_ufo, comment_feed_created)
    counts = dict.fromkeys(NAMES, 0)
    for row in Comment.objects.values('is_shadowed', 'is_ufo').annotate(n=Count('id')).order_by():
        if row['is_shadowed']:
            counts['shadowed'] += row['n']
        else:
            counts['public'] += row['n']
            counts['ufo'] += row['n'] if row['is_ufo'] else 0
    for row in Comment.objects.filter(parent__isnull=True).values('is_shadowed').annotate(n=Count('id')).order_by():
        counts['top_shadowed' if row['is_shadowed'] else 'top_public'] += row['n']
    cache.set_many({PREFIX + name: value for name, value in counts.items()}, CACHE_SECONDS)
    return counts


def invalidate() -> None:
    cache.delete_many(KEYS)


def comment_created(comment: Comment) -> None:
    """+1 in place; a counter that is not cached is simply recounted on the next read."""
    kind = 'shadowed' if comment.is_shadowed else 'public'
    names = [kind] + ([f'top_{kind}'] if comment.parent_id is None else [])
    for name in names:
        try:
            cache.incr(PREFIX + name)
        except ValueError:  # not cached (expired or dropped): the next read recounts everything
            invalidate()
            return


def _own_shadowed(viewer: Viewer, top_level_only: bool = False) -> int:
    """An author under a shadow ban sees their own hidden comments, so they count for them."""
    if viewer.user_id is None and viewer.guest_key is None:
        return 0
    own = Q(user_id=viewer.user_id) if viewer.user_id is not None else Q(guest_key=viewer.guest_key)
    rows = Comment.objects.filter(own, is_shadowed=True)
    return (rows.filter(parent__isnull=True) if top_level_only else rows).count()


def top_level_count(viewer: Viewer) -> int:
    """How many rows the feed has for this viewer: the same rule as CommentQuerySet.visible_to."""
    shared = _shared()
    if viewer.is_moderator:
        return shared['top_public'] + shared['top_shadowed']
    return shared['top_public'] + _own_shadowed(viewer, top_level_only=True)


def stats_for(viewer: Viewer) -> Stats:
    shared = _shared()
    if viewer.is_moderator:
        visible = shared['public'] + shared['shadowed']
    else:
        visible = shared['public'] + _own_shadowed(viewer)

    signed_in = viewer.user_id is not None
    return Stats(
        comments=visible,
        ufo=shared['ufo'],
        shadowed=shared['shadowed'],
        my_comments=Comment.objects.filter(user_id=viewer.user_id).count() if signed_in else None,
        my_bookmarks=Bookmark.objects.filter(user_id=viewer.user_id).count() if signed_in else None,
    )

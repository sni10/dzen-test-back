"""All comment reads go through these named QuerySet methods (the ORM plays the repository role)."""
from django.db import models
from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber

from .viewer import Viewer

# Columns the top-level table can be sorted by; '-' = descending. The default is LIFO (newest first).
SORT_FIELDS = ('user_name', 'email', 'created_at')
SORT_OPTIONS = frozenset(SORT_FIELDS) | {f'-{field}' for field in SORT_FIELDS}
DEFAULT_SORT = '-created_at'


class CommentQuerySet(models.QuerySet):
    def top_level(self):
        """Comments that are not replies: rows of the main table."""
        return self.filter(parent__isnull=True)

    def visible_to(self, viewer: Viewer):
        """Hide shadow-banned comments from everyone except their author and moderators."""
        if viewer.is_moderator:
            return self
        visible = Q(is_shadowed=False)
        if viewer.user_id is not None:
            visible |= Q(user_id=viewer.user_id)
        if viewer.guest_key is not None:
            visible |= Q(guest_key=viewer.guest_key)
        return self.filter(visible)

    def sorted_by(self, sort: str = DEFAULT_SORT):
        """Sort by an allowlisted column; `id` breaks ties in the same direction so pages are stable."""
        if sort not in SORT_OPTIONS:
            raise ValueError(f'Unknown sort "{sort}", expected one of {sorted(SORT_OPTIONS)}')
        tie_breaker = '-id' if sort.startswith('-') else 'id'
        return self.order_by(sort, tie_breaker)

    def replies_of(self, parent_ids, first: int, after: int | None = None):
        """Up to `first` direct replies of each parent, oldest first, in ONE query (window function).

        `after` is a reply id (ids grow with time): continue after it. Rows carry `position` (1-based).
        """
        rows = self.filter(parent_id__in=parent_ids)
        if after is not None:
            rows = rows.filter(pk__gt=after)
        return rows.annotate(
            position=Window(RowNumber(), partition_by=[F('parent_id')], order_by=F('id').asc()),
        ).filter(position__lte=first).order_by('parent_id', 'id')

    def since(self, last_id: int):
        """Comments posted after `last_id`, oldest first: catching up after a WebSocket reconnect."""
        return self.filter(pk__gt=last_id).order_by('id')

    def thread(self, root_id: int):
        """The whole branch under a top-level comment (root included), oldest first; the tree is built in code."""
        return self.filter(Q(pk=root_id) | Q(root_id=root_id)).order_by('created_at', 'id')

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Viewer:
    """Who is looking at the comments: decides what shadow-banned content is visible.

    A registered user is identified by `user_id`, a guest by `guest_key` (UUID from an httpOnly cookie).
    Moderators see everything.
    """

    user_id: int | None = None
    guest_key: UUID | None = None
    is_moderator: bool = False

    @classmethod
    def anonymous(cls) -> 'Viewer':
        return cls()

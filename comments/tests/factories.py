import itertools

from comments.models import Comment

_seq = itertools.count(1)


def make_comment(parent: Comment | None = None, **fields) -> Comment:
    """A saved comment with valid defaults; pass `parent` to make a reply."""
    n = next(_seq)
    comment = Comment(
        user_name=fields.pop('user_name', f'user{n}'),
        email=fields.pop('email', f'user{n}@example.com'),
        text=fields.pop('text', f'Comment {n}'),
        **fields,
    )
    comment.set_parent(parent)
    comment.save()
    return comment

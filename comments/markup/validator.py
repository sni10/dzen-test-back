"""Strict XHTML check of comment text with regular expressions.

Only the allowlisted tags may appear, every tag must be closed and properly nested, attributes must be
lowercase and double-quoted. Invalid markup is rejected with a reason and a position, never silently fixed:
the author sees exactly what is wrong.

A `<` that cannot start a tag (followed by a space, a digit, `=` ...) is plain text, so "a < b" is fine;
the sanitizer escapes it afterwards.
"""
import re
from dataclasses import dataclass, field
from enum import StrEnum


class MarkupErrorCode(StrEnum):
    MALFORMED_TAG = 'malformed_tag'
    UNKNOWN_TAG = 'unknown_tag'
    UNKNOWN_ATTRIBUTE = 'unknown_attribute'
    DUPLICATE_ATTRIBUTE = 'duplicate_attribute'
    MISSING_ATTRIBUTE = 'missing_attribute'
    UNSAFE_URL = 'unsafe_url'
    NESTED_TAG = 'nested_tag'
    UNEXPECTED_CLOSING_TAG = 'unexpected_closing_tag'
    MISMATCHED_CLOSING_TAG = 'mismatched_closing_tag'
    UNCLOSED_TAG = 'unclosed_tag'


class MarkupError(ValueError):
    """Invalid markup. `code` is stable (the front translates it), `position` is a 0-based character offset."""

    def __init__(self, code: MarkupErrorCode, message: str, position: int):
        super().__init__(f'{message} (at {position})')
        self.code = code
        self.message = message
        self.position = position


@dataclass(frozen=True)
class TagRule:
    name: str
    attributes: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()
    url_attributes: frozenset[str] = frozenset()
    can_nest_in_itself: bool = True


@dataclass(frozen=True)
class MarkupPolicy:
    """Which tags and attributes are allowed. The validator and the sanitizer read the same policy."""

    tags: tuple[TagRule, ...]
    url_schemes: frozenset[str] = frozenset({'http', 'https', 'mailto'})
    _by_name: dict[str, TagRule] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, '_by_name', {rule.name: rule for rule in self.tags})

    def rule(self, name: str) -> TagRule | None:
        return self._by_name.get(name)


# The assignment: <a href="" title=""> </a> <code> </code> <i> </i> <strong> </strong>
COMMENT_POLICY = MarkupPolicy(tags=(
    TagRule('a', attributes=frozenset({'href', 'title'}), required=frozenset({'href'}),
            url_attributes=frozenset({'href'}), can_nest_in_itself=False),  # a link inside a link is invalid
    TagRule('code'),
    TagRule('i'),
    TagRule('strong'),
))

_TAG_START = re.compile(r'<(?=[A-Za-z/!?])')  # anything else after "<" is text
_OPEN_TAG = re.compile(r'<([a-z][a-z0-9]*)((?:\s+[a-z][a-z-]*="[^"<>]*")*)\s*>')
_CLOSE_TAG = re.compile(r'</([a-z][a-z0-9]*)\s*>')
_ATTRIBUTE = re.compile(r'\s+([a-z][a-z-]*)="([^"<>]*)"')
_URL = re.compile(r'^([a-z][a-z0-9+.-]*):\S+$', re.IGNORECASE)


@dataclass
class _Open:
    name: str
    position: int


class XhtmlValidator:
    def __init__(self, policy: MarkupPolicy = COMMENT_POLICY):
        self.policy = policy

    def validate(self, text: str) -> None:
        """Raise MarkupError on the first problem; return None when the markup is valid."""
        stack: list[_Open] = []
        for start in _TAG_START.finditer(text):
            position = start.start()
            if closing := _CLOSE_TAG.match(text, position):
                self._close(closing.group(1), position, stack)
            elif opening := _OPEN_TAG.match(text, position):
                self._open(opening.group(1), opening.group(2), position, stack)
            else:
                raise MarkupError(
                    MarkupErrorCode.MALFORMED_TAG,
                    'Malformed tag: use lowercase tags, double-quoted attributes and a separate closing tag; '
                    'write &lt; for a literal "<"',
                    position,
                )
        if stack:
            unclosed = stack[-1]
            raise MarkupError(MarkupErrorCode.UNCLOSED_TAG, f'<{unclosed.name}> is not closed', unclosed.position)

    def _open(self, name: str, raw_attributes: str, position: int, stack: list[_Open]) -> None:
        rule = self._rule(name, position)
        if not rule.can_nest_in_itself and any(item.name == name for item in stack):
            raise MarkupError(MarkupErrorCode.NESTED_TAG, f'<{name}> cannot be placed inside another <{name}>', position)

        seen: set[str] = set()
        for attribute, value in _ATTRIBUTE.findall(raw_attributes):
            if attribute not in rule.attributes:
                raise MarkupError(
                    MarkupErrorCode.UNKNOWN_ATTRIBUTE, f'Attribute "{attribute}" is not allowed in <{name}>', position,
                )
            if attribute in seen:
                raise MarkupError(
                    MarkupErrorCode.DUPLICATE_ATTRIBUTE, f'Attribute "{attribute}" is repeated in <{name}>', position,
                )
            seen.add(attribute)
            if attribute in rule.url_attributes:
                self._check_url(value, position)

        if missing := sorted(rule.required - seen):
            raise MarkupError(
                MarkupErrorCode.MISSING_ATTRIBUTE, f'<{name}> needs the attribute "{missing[0]}"', position,
            )
        stack.append(_Open(name, position))

    def _close(self, name: str, position: int, stack: list[_Open]) -> None:
        self._rule(name, position)
        if not stack:
            raise MarkupError(MarkupErrorCode.UNEXPECTED_CLOSING_TAG, f'</{name}> has no opening tag', position)
        if stack[-1].name != name:
            raise MarkupError(
                MarkupErrorCode.MISMATCHED_CLOSING_TAG,
                f'</{name}> closes <{stack[-1].name}>: tags must be closed in reverse order',
                position,
            )
        stack.pop()

    def _rule(self, name: str, position: int) -> TagRule:
        rule = self.policy.rule(name)
        if rule is None:
            allowed = ', '.join(f'<{tag.name}>' for tag in self.policy.tags)
            raise MarkupError(MarkupErrorCode.UNKNOWN_TAG, f'<{name}> is not allowed; allowed: {allowed}', position)
        return rule

    def _check_url(self, url: str, position: int) -> None:
        match = _URL.match(url.strip())
        if not match or match.group(1).lower() not in self.policy.url_schemes:
            schemes = ', '.join(sorted(self.policy.url_schemes))
            raise MarkupError(MarkupErrorCode.UNSAFE_URL, f'Link must start with one of: {schemes}', position)

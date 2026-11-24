"""Comment text markup: strict validation, then sanitizing. Used by comment creation and preview."""
from .sanitizer import HtmlSanitizer
from .validator import COMMENT_POLICY, MarkupError, MarkupErrorCode, MarkupPolicy, TagRule, XhtmlValidator


class CommentMarkup:
    """Validate (reject invalid markup with a reason) and return HTML that is safe to store and render."""

    def __init__(self, validator: XhtmlValidator | None = None, sanitizer: HtmlSanitizer | None = None):
        self.validator = validator or XhtmlValidator()
        self.sanitizer = sanitizer or HtmlSanitizer()

    def clean(self, text: str) -> str:
        self.validator.validate(text)
        return self.sanitizer.clean(text)


__all__ = [
    'COMMENT_POLICY', 'CommentMarkup', 'HtmlSanitizer', 'MarkupError', 'MarkupErrorCode', 'MarkupPolicy',
    'TagRule', 'XhtmlValidator',
]

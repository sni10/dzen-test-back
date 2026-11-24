"""Second line of defence after the validator: an allowlist HTML cleaner (nh3, a binding to Rust's ammonia).

Even if a validator bug let something through, only the policy's tags/attributes/URL schemes survive.
Text-level `<`, `>` and `&` are escaped, so the stored HTML is safe to render with v-html.
"""
import nh3

from .validator import COMMENT_POLICY, MarkupPolicy

LINK_REL = 'nofollow ugc noopener noreferrer'


class HtmlSanitizer:
    def __init__(self, policy: MarkupPolicy = COMMENT_POLICY):
        self._tags = {rule.name for rule in policy.tags}
        self._attributes = {rule.name: set(rule.attributes) for rule in policy.tags if rule.attributes}
        self._url_schemes = set(policy.url_schemes)

    def clean(self, html: str) -> str:
        return nh3.clean(
            html,
            tags=self._tags,
            attributes=self._attributes,
            url_schemes=self._url_schemes,
            link_rel=LINK_REL,
            set_tag_attribute_values={'a': {'target': '_blank'}} if 'a' in self._tags else None,
            strip_comments=True,
        )

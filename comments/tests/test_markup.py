import json
from pathlib import Path

from django.test import SimpleTestCase

from comments.markup import CommentMarkup, HtmlSanitizer, MarkupError, MarkupPolicy, TagRule, XhtmlValidator

CASES = json.loads((Path(__file__).resolve().parents[1] / 'markup' / 'cases.json').read_text(encoding='utf-8'))['cases']


class XhtmlValidatorSharedCasesTests(SimpleTestCase):
    """The same cases.json is run by the frontend validator: both sides must agree."""

    def test_shared_cases(self):
        validator = XhtmlValidator()
        for case in CASES:
            with self.subTest(text=case['text']):
                expected = case['error']
                if expected is None:
                    validator.validate(case['text'])
                    continue
                with self.assertRaises(MarkupError) as ctx:
                    validator.validate(case['text'])
                self.assertEqual(
                    (ctx.exception.code, ctx.exception.position), (expected['code'], expected['position']),
                    ctx.exception.message,
                )


class XhtmlValidatorTests(SimpleTestCase):
    def test_error_message_is_human_readable(self):
        with self.assertRaises(MarkupError) as ctx:
            XhtmlValidator().validate('<b>x</b>')

        self.assertIn('<b> is not allowed', ctx.exception.message)
        self.assertIn('<strong>', ctx.exception.message)

    def test_policy_is_configurable(self):
        """Open/closed: another tag set needs a new policy, not a new validator."""
        policy = MarkupPolicy(tags=(TagRule('b'),))
        validator = XhtmlValidator(policy)

        validator.validate('<b>ok</b>')
        with self.assertRaises(MarkupError):
            validator.validate('<i>no</i>')

    def test_deep_nesting_is_linear(self):
        text = '<i><strong>' * 2000 + 'x' + '</strong></i>' * 2000

        XhtmlValidator().validate(text)  # no recursion limit, no catastrophic regex backtracking


class HtmlSanitizerTests(SimpleTestCase):
    sanitizer = HtmlSanitizer()

    def test_escapes_text_level_special_characters(self):
        self.assertEqual(self.sanitizer.clean('a < b & c > d'), 'a &lt; b &amp; c &gt; d')

    def test_keeps_allowed_markup_and_hardens_links(self):
        html = self.sanitizer.clean('<a href="https://e.com" title="T">x</a> <i>i</i>')

        self.assertIn('href="https://e.com"', html)
        self.assertIn('title="T"', html)
        self.assertIn('rel="nofollow ugc noopener noreferrer"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('<i>i</i>', html)

    def test_strips_everything_else_even_if_the_validator_is_bypassed(self):
        cases = {
            '<script>alert(1)</script>ok': 'ok',
            '<i onclick="x()">t</i>': '<i>t</i>',
            '<img src=x onerror=alert(1)>': '',
            '<!-- c -->ok': 'ok',
            '<b>bold</b>': 'bold',
        }
        for dirty, clean in cases.items():
            with self.subTest(dirty=dirty):
                self.assertEqual(self.sanitizer.clean(dirty), clean)

    def test_drops_unsafe_link_schemes(self):
        html = self.sanitizer.clean('<a href="javascript:alert(1)">x</a>')

        self.assertNotIn('javascript', html)


class CommentMarkupTests(SimpleTestCase):
    def test_valid_text_is_validated_then_sanitized(self):
        self.assertEqual(CommentMarkup().clean('<code>1 < 2</code>'), '<code>1 &lt; 2</code>')

    def test_invalid_text_is_rejected_not_fixed(self):
        with self.assertRaises(MarkupError):
            CommentMarkup().clean('<i>unclosed')

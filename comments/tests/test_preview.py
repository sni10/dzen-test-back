from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from comments.models import Comment
from comments.serializers import TEXT_MAX_LENGTH


class CommentPreviewApiTests(TestCase):
    url = reverse('comment-preview')

    def setUp(self):
        cache.clear()  # throttle counters

    def preview(self, text):
        return self.client.post(self.url, {'text': text}, content_type='application/json')

    def test_returns_text_exactly_as_it_would_be_stored(self):
        response = self.preview('1 < 2 & <a href="https://e.com" title="E">link</a> <code>x</code>')

        self.assertEqual(response.status_code, 200)
        text = response.json()['text']
        self.assertTrue(text.startswith('1 &lt; 2 &amp; <a href="https://e.com" title="E"'))
        self.assertIn('rel="nofollow ugc noopener noreferrer"', text)
        self.assertTrue(text.endswith('<code>x</code>'))

    def test_saves_nothing_and_needs_no_captcha(self):
        self.preview('<i>hello</i>')

        self.assertFalse(Comment.objects.exists())

    def test_invalid_markup_reports_code_and_position(self):
        response = self.preview('ok </strong>')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['markup'], {'code': 'unexpected_closing_tag', 'position': 3})
        self.assertIn('text', response.json())

    def test_same_text_rules_as_posting(self):
        for text in ('', '   ', 'x' * (TEXT_MAX_LENGTH + 1)):
            with self.subTest(length=len(text)):
                response = self.preview(text)
                self.assertEqual(response.status_code, 400)
                self.assertIn('text', response.json())

    def test_rate_limited(self):
        with mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES', {'comment_preview': '2/min'}):
            codes = [self.preview('x').status_code for _ in range(3)]

        self.assertEqual(codes, [200, 200, 429])

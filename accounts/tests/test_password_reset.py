import re
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from accounts.password_reset import PasswordResetService, reset_link
from accounts.tasks import send_password_reset
from accounts.views import REFRESH_COOKIE

PASSWORD = 'correct-horse-battery-9'
NEW_PASSWORD = 'another-long-secret-42'
RESET_URL = 'https://comments.example/reset-password'


class ResetTestCase(TestCase):
    def setUp(self):
        cache.clear()  # cooldowns and throttle counters
        rates = mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES',
                                {'auth_password_reset': '1000/min', 'auth_password_reset_confirm': '1000/min'})
        rates.start()
        self.addCleanup(rates.stop)
        self.user = User.objects.create_user('Rum8', 'rum@example.com', PASSWORD)

    def link_parts(self, link=None):
        query = parse_qs(urlsplit(link or reset_link(self.user, RESET_URL)).query)
        return query['uid'][0], query['token'][0]

    def confirm(self, uid, token, password=NEW_PASSWORD):
        return self.client.post(reverse('auth-password-reset-confirm'),
                                {'uid': uid, 'token': token, 'password': password}, content_type='application/json')


class RequestTests(ResetTestCase):
    def setUp(self):
        super().setUp()
        self.queued = []
        self.service = PasswordResetService(lambda user_id, url: self.queued.append((user_id, url)))

    def test_queues_an_email_for_an_existing_account_any_case(self):
        self.service.request(' RUM@example.com ', RESET_URL)

        self.assertEqual(self.queued, [(self.user.pk, RESET_URL)])

    def test_unknown_or_inactive_address_sends_nothing(self):
        User.objects.create_user('Gone', 'gone@example.com', PASSWORD, is_active=False)

        self.service.request('nobody@example.com', RESET_URL)
        self.service.request('gone@example.com', RESET_URL)

        self.assertEqual(self.queued, [])

    def test_one_email_per_minute_per_account(self):
        self.service.request('rum@example.com', RESET_URL)
        self.service.request('rum@example.com', RESET_URL)

        self.assertEqual(len(self.queued), 1)

    def test_api_answers_the_same_whether_or_not_the_account_exists(self):
        with mock.patch('accounts.container.send_password_reset') as task:
            from accounts.container import password_reset_service
            password_reset_service.cache_clear()
            self.addCleanup(password_reset_service.cache_clear)
            known = self.client.post(reverse('auth-password-reset'), {'email': 'rum@example.com'},
                                     content_type='application/json')
            unknown = self.client.post(reverse('auth-password-reset'), {'email': 'nobody@example.com'},
                                       content_type='application/json')

        self.assertEqual((known.status_code, known.json()), (unknown.status_code, unknown.json()))
        self.assertEqual(known.status_code, 202)
        task.delay.assert_called_once_with(self.user.pk, 'http://testserver/reset-password')


class EmailTests(ResetTestCase):
    def test_the_email_carries_a_working_link(self):
        send_password_reset(self.user.pk, RESET_URL)

        [message] = mail.outbox
        self.assertEqual(message.to, ['rum@example.com'])
        self.assertEqual(message.subject, 'Reset your password')
        self.assertIn('comments.example', message.body)
        link = re.search(r'https://\S+', message.body).group(0)
        self.assertTrue(link.startswith(RESET_URL + '?'))
        self.assertEqual(self.confirm(*self.link_parts(link)).status_code, 200)

    def test_no_email_for_a_deactivated_account(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        send_password_reset(self.user.pk, RESET_URL)

        self.assertEqual(mail.outbox, [])


class ConfirmTests(ResetTestCase):
    def test_sets_the_password_signs_out_everywhere_and_signs_this_browser_in(self):
        old_session = RefreshToken.for_user(self.user)

        response = self.confirm(*self.link_parts())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccessToken(response.json()['access'])['user_id'], str(self.user.pk))
        self.assertIn(REFRESH_COOKIE, response.cookies)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.client.cookies[REFRESH_COOKIE] = str(old_session)
        self.assertEqual(self.client.post(reverse('auth-refresh')).status_code, 401)

    def test_a_link_works_only_once(self):
        uid, token = self.link_parts()
        self.confirm(uid, token)

        response = self.confirm(uid, token, 'yet-another-secret-55')

        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.json())

    def test_a_bad_link(self):
        uid, token = self.link_parts()
        for bad_uid, bad_token in ((uid, 'nope'), ('!!', token), ('MTIzNDU2', token), ('', '')):
            with self.subTest(uid=bad_uid, token=bad_token):
                response = self.confirm(bad_uid or 'x', bad_token or 'y')
                self.assertEqual(response.status_code, 400)
                self.assertIn('token', response.json())

    def test_an_expired_link(self):
        uid, token = self.link_parts()

        an_hour_later = datetime.now() + timedelta(hours=1, seconds=1)
        with mock.patch('django.contrib.auth.tokens.PasswordResetTokenGenerator._now', return_value=an_hour_later):
            response = self.confirm(uid, token)

        self.assertEqual(response.status_code, 400)

    def test_a_weak_new_password_keeps_the_link_valid(self):
        uid, token = self.link_parts()

        weak = self.confirm(uid, token, '12345678')

        self.assertEqual(weak.status_code, 400)
        self.assertIn('password', weak.json())
        self.assertEqual(self.confirm(uid, token).status_code, 200)

import uuid
from unittest import mock

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from accounts.tokens import user_from_token
from accounts.views import REFRESH_COOKIE
from comments.live import ChannelsNotifier
from comments.tests.factories import make_comment
from comments.tests.test_create import FakeCaptcha
from common.guest import COOKIE_NAME as GUEST_COOKIE
from config.asgi import application

PASSWORD = 'correct-horse-battery-9'


class AuthApiTestCase(TestCase):
    def setUp(self):
        cache.clear()  # throttle counters
        rates = mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES',
                                {'auth_register': '1000/min', 'auth_login': '1000/min', 'auth_refresh': '1000/min'})
        rates.start()
        self.addCleanup(rates.stop)
        self.captcha = FakeCaptcha()
        patcher = mock.patch('accounts.container.captcha_service', return_value=self.captcha.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        from accounts.container import auth_service
        auth_service.cache_clear()
        self.addCleanup(auth_service.cache_clear)

    def post(self, name, data=None, **headers):
        return self.client.post(reverse(name), data or {}, content_type='application/json', headers=headers)

    def register(self, **overrides):
        return self.post('auth-register', {
            'username': 'Rum8', 'email': 'rum@example.com', 'password': PASSWORD,
            'captcha_key': self.captcha.new_key(), 'captcha_answer': 'Ab3Cd', **overrides,
        })


class RegisterTests(AuthApiTestCase):
    def test_creates_the_account_and_signs_in(self):
        response = self.register(email='Rum@Example.com')

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['user'], {'id': body['user']['id'], 'username': 'Rum8', 'email': 'rum@example.com',
                                        'home_page': '', 'is_moderator': False})
        self.assertEqual(AccessToken(body['access'])['user_id'], str(body['user']['id']))
        user = User.objects.get()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)

    def test_refresh_token_is_an_httponly_cookie_for_the_auth_endpoints_only(self):
        cookie = self.register().cookies[REFRESH_COOKIE]

        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['path'], '/api/auth/')
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(int(cookie['max-age']), 7 * 24 * 3600)
        self.assertNotIn(cookie.value, self.register(username='Other', email='o@example.com').content.decode())

    def test_field_rules(self):
        cases = {
            'username': ['', 'a', 'bad name', 'юзер', 'x' * 51],
            'email': ['', 'not-an-email'],
            'password': ['short', '12345678901', 'password123', 'rum@example.com'],  # too similar to the e-mail
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.register(**{field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json())
        self.assertFalse(User.objects.exists())

    def test_name_and_email_are_unique_ignoring_case(self):
        self.register()

        self.assertIn('username', self.register(username='RUM8', email='x@example.com').json())
        self.assertIn('email', self.register(username='Other', email='RUM@example.com').json())
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_captcha(self):
        response = self.register(captcha_answer='wrong')

        self.assertEqual(response.status_code, 400)
        self.assertIn('captcha', response.json())
        self.assertFalse(User.objects.exists())

    def test_taken_name_keeps_the_captcha(self):
        self.register()
        key = self.captcha.new_key()

        self.register(captcha_key=key)  # rejected: the name is taken

        self.assertTrue(self.captcha.service.verify(key, 'Ab3Cd'))

    def test_rate_limited(self):
        with mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES', {'auth_register': '1/min'}):
            codes = [self.register(username=f'user{n}', email=f'u{n}@example.com').status_code for n in range(2)]

        self.assertEqual(codes, [201, 429])


class LoginLogoutRefreshTests(AuthApiTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('Rum8', 'rum@example.com', PASSWORD)

    def login(self, login='Rum8', password=PASSWORD):
        return self.post('auth-login', {'login': login, 'password': password})

    def test_by_name_or_email_in_any_case(self):
        for login in ('Rum8', 'rum8', 'rum@example.com', 'RUM@EXAMPLE.COM'):
            with self.subTest(login=login):
                response = self.login(login)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['user']['username'], 'Rum8')

    def test_one_message_for_every_failure(self):
        inactive = User.objects.create_user('Gone', 'gone@example.com', PASSWORD, is_active=False)
        for login, password in (('Rum8', 'wrong'), ('nobody', PASSWORD), (inactive.username, PASSWORD)):
            with self.subTest(login=login):
                response = self.login(login, password)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'non_field_errors': ['Wrong name, e-mail or password']})

    def test_signing_in_and_out_ends_the_guest_identity(self):
        """After signing out the browser is a new guest, not the one who wrote here (and may be shadow-banned)"""
        self.client.get(reverse('captcha'))  # any request: the guest cookie is issued
        guest = self.client.cookies[GUEST_COOKIE].value

        self.login()
        self.assertEqual(self.client.cookies[GUEST_COOKIE].value, '')  # dropped
        self.post('auth-logout')

        self.assertNotIn(self.client.cookies[GUEST_COOKIE].value, ('', guest))  # a new guest from now on

    def test_a_refresh_keeps_the_guest_cookie(self):
        self.login()
        self.client.get(reverse('captcha'))
        guest = self.client.cookies[GUEST_COOKIE].value

        self.post('auth-refresh')

        self.assertEqual(self.client.cookies[GUEST_COOKIE].value, guest)

    def test_refresh_rotates_the_cookie_and_the_old_one_stops_working(self):
        self.login()
        old = self.client.cookies[REFRESH_COOKIE].value

        response = self.post('auth-refresh')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccessToken(response.json()['access'])['user_id'], str(self.user.pk))
        new = response.cookies[REFRESH_COOKIE].value
        self.assertNotEqual(new, old)
        self.client.cookies[REFRESH_COOKIE] = old
        self.assertEqual(self.post('auth-refresh').status_code, 401)  # a replayed (stolen) copy is refused

    def test_refresh_without_a_valid_cookie(self):
        self.assertEqual(self.post('auth-refresh').status_code, 401)
        self.client.cookies[REFRESH_COOKIE] = 'garbage'
        response = self.post('auth-refresh')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.cookies[REFRESH_COOKIE].value, '')  # cleared

    def test_refresh_from_another_site_is_refused(self):
        self.login()

        self.assertEqual(self.post('auth-refresh', Origin='https://evil.example').status_code, 403)
        self.assertEqual(self.post('auth-refresh', Origin='http://testserver').status_code, 200)

    def test_refresh_for_a_deactivated_user(self):
        self.login()
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        self.assertEqual(self.post('auth-refresh').status_code, 401)

    def test_logout_revokes_the_refresh_token(self):
        self.login()
        token = self.client.cookies[REFRESH_COOKIE].value

        response = self.post('auth-logout')

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies[REFRESH_COOKIE].value, '')
        self.client.cookies[REFRESH_COOKIE] = token
        self.assertEqual(self.post('auth-refresh').status_code, 401)


class TokenIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('Rum8', 'rum@example.com', PASSWORD, is_shadowbanned=True)
        self.access = str(AccessToken.for_user(self.user))

    def test_user_from_token(self):
        self.assertEqual(user_from_token(self.access), self.user)
        for bad in (None, '', 'garbage', str(RefreshToken.for_user(self.user))):  # a refresh token is not access
            with self.subTest(token=bad):
                self.assertIsNone(user_from_token(bad))

    def test_graphql_knows_the_user_by_the_bearer_token(self):
        own = make_comment(user=self.user, is_shadowed=True)
        query = {'query': '{ comments { totalCount } }'}

        anonymous = self.client.post(reverse('graphql'), query, content_type='application/json')
        signed_in = self.client.post(reverse('graphql'), query, content_type='application/json',
                                     headers={'Authorization': f'Bearer {self.access}'})

        self.assertEqual(anonymous.json()['data']['comments']['totalCount'], 0)
        self.assertEqual(signed_in.json()['data']['comments']['totalCount'], 1)  # own shadowed comment
        self.assertTrue(own.is_shadowed)

    def test_comment_is_posted_under_the_account(self):
        captcha = FakeCaptcha()
        cache.clear()
        with mock.patch('comments.container.captcha_service', return_value=captcha.service), \
                mock.patch('comments.container.process_attachment'):
            from comments.container import comment_service
            comment_service.cache_clear()
            self.addCleanup(comment_service.cache_clear)
            response = self.client.post(reverse('comment-create'), {
                'user_name': 'Someone', 'email': 'someone@example.com', 'text': 'Mine',
                'captcha_key': captcha.new_key(), 'captcha_answer': 'Ab3Cd',
            }, content_type='application/json', headers={'Authorization': f'Bearer {self.access}'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json()['user_name'], response.json()['email']), ('Rum8', 'rum@example.com'))

    def test_an_invalid_token_on_rest_is_401(self):
        response = self.client.post(reverse('comment-create'), {}, content_type='application/json',
                                    headers={'Authorization': 'Bearer garbage'})

        self.assertEqual(response.status_code, 401)


class WebSocketTokenTests(TransactionTestCase):
    """The socket learns the user from ?token= (browsers cannot set headers on a WebSocket)."""

    def setUp(self):
        default = settings.CHANNEL_LAYERS['default']
        isolated = self.settings(CHANNEL_LAYERS={
            'default': {**default, 'CONFIG': {**default['CONFIG'], 'prefix': f'test-{uuid.uuid4().hex}'}},
        })
        isolated.enable()
        self.addCleanup(isolated.disable)

    async def test_signed_in_user_receives_own_shadowed_comment(self):
        user = await sync_to_async(User.objects.create_user)('Rum8', 'rum@example.com', PASSWORD,
                                                             is_shadowbanned=True)
        token = str(AccessToken.for_user(user))
        own = WebsocketCommunicator(application, f'/ws/comments/?token={token}',
                                    headers=[(b'origin', b'http://testserver')])
        stranger = WebsocketCommunicator(application, '/ws/comments/', headers=[(b'origin', b'http://testserver')])
        self.assertTrue((await own.connect())[0] and (await stranger.connect())[0])

        comment = await sync_to_async(make_comment)(user=user, is_shadowed=True)
        await sync_to_async(ChannelsNotifier().comment_created)(comment)

        self.assertEqual((await own.receive_json_from(timeout=2))['comment']['id'], str(comment.pk))
        self.assertTrue(await stranger.receive_nothing(timeout=0.3))
        await own.disconnect()
        await stranger.disconnect()

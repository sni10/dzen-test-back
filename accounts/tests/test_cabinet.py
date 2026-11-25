from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from accounts.views import REFRESH_COOKIE
from comments.tests.factories import make_comment

PASSWORD = 'correct-horse-battery-9'
NEW_PASSWORD = 'another-long-secret-42'


class CabinetTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('Rum8', 'rum@example.com', PASSWORD)

    def gql(self, query, variables=None, user=None):
        headers = {'Authorization': f'Bearer {AccessToken.for_user(user)}'} if user else {}
        response = self.client.post(reverse('graphql'), {'query': query, 'variables': variables or {}},
                                    content_type='application/json', headers=headers)
        self.assertEqual(response.status_code, 200)
        return response

    def data(self, query, variables=None, user=None):
        body = self.gql(query, variables, user).json()
        self.assertNotIn('errors', body, body.get('errors'))
        return body['data']

    def error(self, query, variables=None, user=None):
        return self.gql(query, variables, user).json()['errors'][0]


class MeTests(CabinetTestCase):
    def test_me(self):
        make_comment(user=self.user)
        make_comment(parent=make_comment(), user=self.user)
        make_comment()  # someone else's

        me = self.data('{ me { username email homePage isModerator commentsCount } }', user=self.user)['me']

        self.assertEqual(me, {'username': 'Rum8', 'email': 'rum@example.com', 'homePage': '',
                              'isModerator': False, 'commentsCount': 2})

    def test_guest_is_nobody(self):
        self.assertIsNone(self.data('{ me { username } }')['me'])

    def test_my_comments_newest_first_with_replies_and_shadowed(self):
        older = make_comment(user=self.user)
        reply = make_comment(parent=make_comment(), user=self.user)
        shadowed = make_comment(user=self.user, is_shadowed=True)
        make_comment()

        page = self.data('{ myComments { totalCount items { id } } }', user=self.user)['myComments']

        self.assertEqual(page['totalCount'], 3)
        self.assertEqual([int(c['id']) for c in page['items']], [shadowed.pk, reply.pk, older.pk])

    def test_cabinet_needs_sign_in(self):
        error = self.error('{ myComments { totalCount } }')

        self.assertEqual((error['message'], error['extensions']['code']), ('Sign in first', 'UNAUTHENTICATED'))


class UpdateProfileTests(CabinetTestCase):
    mutation = 'mutation($url: String!) { updateProfile(homePage: $url) { homePage } }'

    def test_sets_and_clears_the_home_page(self):
        result = self.data(self.mutation, {'url': ' https://rum.dev '}, user=self.user)

        self.assertEqual(result['updateProfile']['homePage'], 'https://rum.dev')
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_page, 'https://rum.dev')
        self.data(self.mutation, {'url': ''}, user=self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_page, '')

    def test_rejects_other_addresses(self):
        for url in ('rum.dev', 'ftp://rum.dev', 'javascript:alert(1)', 'https://' + 'x' * 200 + '.com'):
            with self.subTest(url=url):
                error = self.error(self.mutation, {'url': url}, user=self.user)
                self.assertEqual(error['extensions']['field'], 'homePage')

    def test_needs_sign_in(self):
        self.assertEqual(self.error(self.mutation, {'url': ''})['extensions']['code'], 'UNAUTHENTICATED')


class ChangePasswordTests(CabinetTestCase):
    mutation = 'mutation($old: String!, $new: String!) { changePassword(oldPassword: $old, newPassword: $new) }'

    def test_changes_the_password_and_keeps_this_session(self):
        other_session = RefreshToken.for_user(self.user)

        response = self.gql(self.mutation, {'old': PASSWORD, 'new': NEW_PASSWORD}, user=self.user)

        access = response.json()['data']['changePassword']
        self.assertEqual(AccessToken(access)['user_id'], str(self.user.pk))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        # this browser gets a new refresh cookie, every other session is revoked
        self.assertIn(REFRESH_COOKIE, response.cookies)
        self.client.cookies[REFRESH_COOKIE] = response.cookies[REFRESH_COOKIE].value
        self.assertEqual(self.client.post(reverse('auth-refresh')).status_code, 200)
        self.client.cookies[REFRESH_COOKIE] = str(other_session)
        self.assertEqual(self.client.post(reverse('auth-refresh')).status_code, 401)

    def test_wrong_current_password(self):
        error = self.error(self.mutation, {'old': 'wrong', 'new': NEW_PASSWORD}, user=self.user)

        self.assertEqual(error['extensions']['field'], 'oldPassword')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_weak_new_password(self):
        error = self.error(self.mutation, {'old': PASSWORD, 'new': '12345678'}, user=self.user)

        self.assertEqual(error['extensions']['field'], 'newPassword')

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User


class UserModelTests(TestCase):
    def test_username_accepts_latin_letters_and_digits(self):
        user = User(username='Rum8', email='rum@example.com')
        user.set_password('a-long-password-1')

        user.full_clean()  # no error

    def test_username_rejects_other_characters(self):
        for username in ('rum_8', 'рум', 'rum 8', 'rum-8'):
            with self.subTest(username=username):
                user = User(username=username, email='rum@example.com', password='x')
                with self.assertRaises(ValidationError) as ctx:
                    user.full_clean()
                self.assertIn('username', ctx.exception.message_dict)

    def test_defaults(self):
        user = User.objects.create_user('anonym', 'anonym@example.com', 'a-long-password-1')

        self.assertEqual(user.role, User.Role.USER)
        self.assertFalse(user.is_shadowbanned)
        self.assertFalse(user.is_moderator)

    def test_admin_role_and_superuser_are_moderators(self):
        admin = User(username='mod', email='mod@example.com', role=User.Role.ADMIN)
        superuser = User(username='root', email='root@example.com', is_superuser=True)

        self.assertTrue(admin.is_moderator)
        self.assertTrue(superuser.is_moderator)

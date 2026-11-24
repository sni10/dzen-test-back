import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from comments.models import Comment
from comments.querysets import SORT_OPTIONS
from comments.viewer import Viewer

from .factories import make_comment


def ids(queryset):
    return list(queryset.values_list('pk', flat=True))


class TopLevelAndThreadTests(TestCase):
    def test_top_level_excludes_replies(self):
        root = make_comment()
        make_comment(parent=root)
        other = make_comment()

        self.assertCountEqual(ids(Comment.objects.top_level()), [root.pk, other.pk])

    def test_thread_returns_root_and_all_descendants_oldest_first(self):
        root = make_comment()
        reply = make_comment(parent=root)
        deep = make_comment(parent=reply)
        second = make_comment(parent=root)
        make_comment(parent=make_comment())  # another thread

        self.assertEqual(ids(Comment.objects.thread(root.pk)), [root.pk, reply.pk, deep.pk, second.pk])


class SortTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.b = make_comment(user_name='bob', email='a@example.com')
        self.a = make_comment(user_name='alice', email='c@example.com')
        self.c = make_comment(user_name='carol', email='b@example.com')
        for offset, comment in enumerate([self.b, self.a, self.c]):  # created in this order
            Comment.objects.filter(pk=comment.pk).update(created_at=now + timedelta(minutes=offset))

    def sorted_ids(self, sort):
        return ids(Comment.objects.top_level().sorted_by(sort))

    def test_default_is_lifo(self):
        self.assertEqual(ids(Comment.objects.sorted_by()), [self.c.pk, self.a.pk, self.b.pk])

    def test_each_column_both_directions(self):
        cases = {
            'user_name': [self.a, self.b, self.c],
            'email': [self.b, self.c, self.a],
            'created_at': [self.b, self.a, self.c],
        }
        for field, ascending in cases.items():
            with self.subTest(field=field):
                expected = [comment.pk for comment in ascending]
                self.assertEqual(self.sorted_ids(field), expected)
                self.assertEqual(self.sorted_ids(f'-{field}'), expected[::-1])

    def test_ties_are_broken_by_id_in_the_same_direction(self):
        twin = make_comment(user_name='alice', email='z@example.com')

        self.assertEqual(self.sorted_ids('user_name')[:2], [self.a.pk, twin.pk])
        self.assertEqual(self.sorted_ids('-user_name')[-2:], [twin.pk, self.a.pk])

    def test_unknown_sort_is_rejected(self):
        for sort in ('text', 'ip', '-id; DROP TABLE', ''):
            with self.subTest(sort=sort), self.assertRaises(ValueError):
                Comment.objects.sorted_by(sort)

    def test_allowlist(self):
        self.assertEqual(
            SORT_OPTIONS,
            {'user_name', '-user_name', 'email', '-email', 'created_at', '-created_at'},
        )


class VisibilityTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user('shadow', 'shadow@example.com', 'a-long-password-1')
        self.guest_key = uuid.uuid4()
        self.public = make_comment()
        self.shadowed_user = make_comment(user=self.author, is_shadowed=True)
        self.shadowed_guest = make_comment(guest_key=self.guest_key, is_shadowed=True)

    def visible(self, viewer):
        return set(ids(Comment.objects.visible_to(viewer)))

    def test_anonymous_sees_only_public(self):
        self.assertEqual(self.visible(Viewer.anonymous()), {self.public.pk})

    def test_shadowed_user_sees_own_comments(self):
        self.assertEqual(self.visible(Viewer(user_id=self.author.pk)), {self.public.pk, self.shadowed_user.pk})

    def test_shadowed_guest_sees_own_comments_by_guest_key(self):
        self.assertEqual(self.visible(Viewer(guest_key=self.guest_key)), {self.public.pk, self.shadowed_guest.pk})

    def test_other_guest_does_not_see_shadowed(self):
        self.assertEqual(self.visible(Viewer(guest_key=uuid.uuid4())), {self.public.pk})

    def test_moderator_sees_everything(self):
        self.assertEqual(
            self.visible(Viewer(is_moderator=True)),
            {self.public.pk, self.shadowed_user.pk, self.shadowed_guest.pk},
        )

    def test_chains_with_top_level_and_sort(self):
        reply = make_comment(parent=self.public)

        result = ids(Comment.objects.top_level().visible_to(Viewer.anonymous()).sorted_by('-created_at'))

        self.assertEqual(result, [self.public.pk])
        self.assertNotIn(reply.pk, result)

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from comments.models import Comment

from .factories import make_comment


class SeedTests(TestCase):
    def test_a_consistent_tree_and_clear_removes_only_seeded(self):
        own = make_comment(text='mine')

        call_command('seed', count=500, stdout=StringIO())

        seeded = Comment.objects.exclude(pk=own.pk)
        self.assertEqual(seeded.count(), 500)
        for comment in seeded.select_related('parent'):
            if comment.parent is None:
                self.assertEqual((comment.root_id, comment.depth), (None, 0))
            else:
                self.assertEqual(comment.root_id, comment.parent.root_id or comment.parent.pk)
                self.assertEqual(comment.depth, comment.parent.depth + 1)
                self.assertLess(comment.parent.created_at, comment.created_at)
            self.assertEqual(comment.replies_count, comment.replies.count())
        self.assertLessEqual(max(seeded.values_list('depth', flat=True)), 6)

        call_command('seed', clear=True, stdout=StringIO())

        self.assertEqual(list(Comment.objects.values_list('pk', flat=True)), [own.pk])

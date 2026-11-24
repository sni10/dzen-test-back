from django.db import IntegrityError
from django.test import TestCase

from accounts.models import User
from comments.models import Attachment, Bookmark, Comment, CommentVote, attachment_path

from .factories import make_comment


class CommentTreeTests(TestCase):
    def test_top_level_comment_has_no_root(self):
        comment = make_comment()

        self.assertTrue(comment.is_top_level)
        self.assertIsNone(comment.root_id)
        self.assertEqual(comment.depth, 0)

    def test_reply_points_to_thread_root_at_any_depth(self):
        root = make_comment()
        reply = make_comment(parent=root)
        reply_to_reply = make_comment(parent=reply)

        self.assertEqual((reply.root_id, reply.depth), (root.pk, 1))
        self.assertEqual((reply_to_reply.root_id, reply_to_reply.depth), (root.pk, 2))
        self.assertFalse(reply_to_reply.is_top_level)

    def test_moving_back_to_top_level_resets_tree_fields(self):
        reply = make_comment(parent=make_comment())

        reply.set_parent(None)

        self.assertIsNone(reply.root_id)
        self.assertEqual(reply.depth, 0)

    def test_deleting_root_deletes_thread(self):
        root = make_comment()
        make_comment(parent=make_comment(parent=root))

        root.delete()

        self.assertFalse(Comment.objects.exists())


class AttachmentPathTests(TestCase):
    def test_stored_name_is_random_and_keeps_lowercase_extension(self):
        first = attachment_path(Attachment(), 'Photo.JPG')
        second = attachment_path(Attachment(), 'Photo.JPG')

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith('attachments/'))
        self.assertTrue(first.endswith('.jpg'))
        self.assertNotIn('Photo', first)

    def test_name_without_extension(self):
        path = attachment_path(Attachment(), 'README')

        self.assertNotIn('.', path)


class VoteAndBookmarkConstraintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('voter', 'voter@example.com', 'a-long-password-1')
        self.comment = make_comment()

    def test_one_vote_per_user_and_comment(self):
        CommentVote.objects.create(comment=self.comment, user=self.user, value=1)

        with self.assertRaises(IntegrityError):
            CommentVote.objects.create(comment=self.comment, user=self.user, value=-1)

    def test_vote_value_is_plus_or_minus_one(self):
        with self.assertRaises(IntegrityError):
            CommentVote.objects.create(comment=self.comment, user=self.user, value=5)

    def test_one_bookmark_per_user_and_comment(self):
        Bookmark.objects.create(comment=self.comment, user=self.user)

        with self.assertRaises(IntegrityError):
            Bookmark.objects.create(comment=self.comment, user=self.user)

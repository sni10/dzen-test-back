from django.conf import settings
from django.db import models
from django.db.models import Q


def same_guest(guest_key, email: str) -> Q:
    """The cookie or the e-mail. An empty cookie matches nothing: `guest_key IS NULL` would be every
    comment posted without one (old or imported rows), not this guest."""
    match = Q(email__iexact=email)
    if guest_key is not None:
        match |= Q(guest_key=guest_key)
    return match


class ShadowBanQuerySet(models.QuerySet):
    def active(self):
        return self.filter(lifted_at__isnull=True)

    def matching_guest(self, guest_key, email: str):
        """A guest is recognised by the cookie or, if the cookie was cleared, by the e-mail in the form."""
        return self.active().filter(same_guest(guest_key, email))


class ShadowBan(models.Model):
    """The author's comments are visible only to the author (and moderators). Never shown to the banned one.

    A registered user is banned by account (User.is_shadowbanned mirrors an active ban for fast checks);
    a guest by the guest cookie and the e-mail they posted with.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                             related_name='shadow_bans')
    guest_key = models.UUIDField(null=True, blank=True)
    email = models.EmailField(blank=True)
    user_name = models.CharField(max_length=50)  # as shown in the list of banned authors
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)

    objects = ShadowBanQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['guest_key'], name='shadowban_guest'),
            models.Index(fields=['email'], name='shadowban_email'),
        ]

    def __str__(self):
        return f'{self.user_name} ({"lifted" if self.lifted_at else "active"})'


class ModerationAction(models.Model):
    """The journal: who did what and when; the hidden text of a UFO is kept here."""

    class Kind(models.TextChoices):
        UFO = 'ufo', 'Text hidden (UFO)'
        RESTORE = 'restore', 'Text restored'
        SHADOWBAN = 'shadowban', 'Shadow ban'
        UNBAN = 'unban', 'Shadow ban lifted'

    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    comment = models.ForeignKey('comments.Comment', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='moderation_actions')
    shadow_ban = models.ForeignKey(ShadowBan, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='actions')
    original_text = models.TextField(blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_kind_display()} by #{self.moderator_id}'

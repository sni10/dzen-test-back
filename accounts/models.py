from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

# The same rule as "User Name" in the comment form: Latin letters and digits only
username_validator = RegexValidator(r'^[A-Za-z0-9]+$', 'Only Latin letters and digits.')


class User(AbstractUser):
    class Role(models.TextChoices):
        USER = 'user', 'User'
        ADMIN = 'admin', 'Admin'

    username = models.CharField(
        max_length=50,
        unique=True,
        validators=[username_validator],
        error_messages={'unique': 'A user with that username already exists.'},
    )
    email = models.EmailField(unique=True)
    home_page = models.URLField(blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    # Shadow ban: the user's comments are visible to nobody but the user (see the moderation feature)
    is_shadowbanned = models.BooleanField(default=False)

    REQUIRED_FIELDS = ['email']

    @property
    def is_moderator(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

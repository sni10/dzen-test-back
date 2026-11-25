"""The cabinet in GraphQL: who I am, my comments, profile and password changes. Signed-in users only."""
from __future__ import annotations

from typing import TYPE_CHECKING

import strawberry
from asgiref.sync import sync_to_async
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from graphql import GraphQLError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from comments.graphql.queries import comment_page
from comments.graphql.types import CommentPage
from comments.models import Comment

from .models import User
from .views import set_refresh_cookie

if TYPE_CHECKING:
    from config.graphql import Context


def signed_in(info: strawberry.Info[Context]) -> User:
    user = info.context.user
    if user is None:
        raise GraphQLError('Sign in first', extensions={'code': 'UNAUTHENTICATED'})
    return user


def field_error(field: str, message: str) -> GraphQLError:
    """A message the form shows under `field`."""
    return GraphQLError(message, extensions={'code': 'BAD_USER_INPUT', 'field': field})


@strawberry.type(name='Me')
class MeType:
    id: strawberry.ID
    username: str
    email: str
    home_page: str
    is_moderator: bool
    comments_count: int = strawberry.field(description='Everything I posted, replies included')

    @classmethod
    def from_user(cls, user: User) -> MeType:
        return cls(
            id=strawberry.ID(str(user.pk)),
            username=user.username,
            email=user.email,
            home_page=user.home_page,
            is_moderator=user.is_moderator,
            comments_count=Comment.objects.filter(user=user).count(),
        )


@strawberry.type
class AccountQuery:
    @strawberry.field(description='The signed-in user; null for guests')
    async def me(self, info: strawberry.Info[Context]) -> MeType | None:
        user = info.context.user
        return await sync_to_async(MeType.from_user)(user) if user else None

    @strawberry.field(description='My comments and replies, newest first, 25 per page (shadowed ones included)')
    async def my_comments(self, info: strawberry.Info[Context], page: int = 1) -> CommentPage:
        user = signed_in(info)
        return await sync_to_async(comment_page)(Comment.objects.filter(user=user).order_by('-created_at', '-id'),
                                                 page)


def _update_profile(user: User, home_page: str) -> MeType:
    home_page = home_page.strip()
    if home_page:
        try:
            URLValidator(schemes=['http', 'https'])(home_page)
        except ValidationError:
            raise field_error('homePage', 'An http:// or https:// address') from None
        if len(home_page) > 200:
            raise field_error('homePage', 'At most 200 characters')
    user.home_page = home_page
    user.save(update_fields=['home_page'])
    return MeType.from_user(user)


def _change_password(user: User, old: str, new: str) -> RefreshToken:
    if not user.check_password(old):
        raise field_error('oldPassword', 'Wrong current password')
    try:
        validate_password(new, user=user)
    except ValidationError as error:
        raise field_error('newPassword', ' '.join(error.messages)) from None
    user.set_password(new)
    user.save(update_fields=['password'])
    # Every other session ends: their refresh tokens are revoked; this one gets a fresh token below
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    return RefreshToken.for_user(user)


@strawberry.type
class AccountMutation:
    @strawberry.mutation(description='Home page shown with my comments; an empty string clears it')
    async def update_profile(self, info: strawberry.Info[Context], home_page: str) -> MeType:
        return await sync_to_async(_update_profile)(signed_in(info), home_page)

    @strawberry.mutation(description='Signs out every other session; returns a new access token for this one')
    async def change_password(
        self, info: strawberry.Info[Context], old_password: str, new_password: str,
    ) -> str:
        refresh = await sync_to_async(_change_password)(signed_in(info), old_password, new_password)
        set_refresh_cookie(info.context.response, refresh)
        return str(refresh.access_token)

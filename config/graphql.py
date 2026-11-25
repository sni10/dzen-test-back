"""The GraphQL endpoint: schema, limits against expensive queries, per-request context."""
from dataclasses import dataclass

import strawberry
from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from graphql import GraphQLError
from strawberry.django.views import AsyncGraphQLView
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter

from accounts.graphql import AccountMutation, AccountQuery
from accounts.models import User
from accounts.tokens import user_from_request
from comments.graphql.loaders import CommentLoaders
from comments.graphql.queries import CommentQuery
from comments.graphql.reactions import ReactionMutation, ReactionQuery
from comments.viewer import Viewer

MAX_DEPTH = 10  # comments > items > replies > items > replies ... ~4 levels of replies in one query
MAX_ALIASES = 15
MAX_TOKENS = 2000


@dataclass
class Context:
    request: HttpRequest
    response: HttpResponse
    viewer: Viewer
    loaders: CommentLoaders
    user: User | None = None


@strawberry.type
class Query(CommentQuery, AccountQuery, ReactionQuery):
    pass


@strawberry.type
class Mutation(AccountMutation, ReactionMutation):
    pass


class Schema(strawberry.Schema):
    def process_errors(self, errors, execution_context=None):
        """Log only real failures. Client mistakes are already returned in the response, a traceback for them
        is noise: errors before execution (parse, validation, limits, variable coercion — no `path`) and
        GraphQLError raised on purpose by resolvers."""
        unexpected = [
            error for error in errors
            if error.path is not None and not isinstance(error.original_error, GraphQLError)
        ]
        if unexpected:
            super().process_errors(unexpected, execution_context)


schema = Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        QueryDepthLimiter(max_depth=MAX_DEPTH),
        MaxAliasesLimiter(max_alias_count=MAX_ALIASES),
        MaxTokensLimiter(max_token_count=MAX_TOKENS),
    ],
)


class GraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Context:
        user = await sync_to_async(user_from_request)(request)  # Authorization: Bearer <access token>
        viewer = Viewer.of(user, getattr(request, 'guest_key', None))
        return Context(request=request, response=response, viewer=viewer, loaders=CommentLoaders(viewer), user=user)

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import LoginView, LogoutView, RefreshView, RegisterView
from captcha.views import CaptchaView
from comments.views import CommentCreateView, CommentPreviewView
from common.views import HealthView
from config.graphql import GraphQLView, schema

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', HealthView.as_view(), name='health'),
    path('api/captcha/', CaptchaView.as_view(), name='captcha'),
    path('api/auth/register/', RegisterView.as_view(), name='auth-register'),
    path('api/auth/login/', LoginView.as_view(), name='auth-login'),
    path('api/auth/refresh/', RefreshView.as_view(), name='auth-refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('api/comments/', CommentCreateView.as_view(), name='comment-create'),
    path('api/comments/preview/', CommentPreviewView.as_view(), name='comment-preview'),
    # No CSRF cookie dance: the SPA lives on another subdomain, mutations will authenticate with a JWT in the
    # Authorization header (a cross-site form cannot set it), the guest cookie is SameSite=Lax.
    path('graphql', csrf_exempt(GraphQLView.as_view(schema=schema)), name='graphql'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

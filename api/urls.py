from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    auth_complete_redirect,
    auth_accounts_list,
    email_detail,
    has_refresh_token,
    list_google_accounts,
    disconnect_google_account,
    archive_email,
    delete_emails,
    EmailCategoryViewSet,
    unsubscribe_emails,
)

router = DefaultRouter()
router.register(r'categories', EmailCategoryViewSet, basename='emailcategory')

urlpatterns = [
    path("auth/", include("social_django.urls", namespace="social")),
    path("auth/complete/google-oauth2/", auth_complete_redirect, name="auth-complete-redirect"),
    path("auth/refresh-token/", has_refresh_token),
    path("auth/success/", auth_accounts_list, name="auth-accounts-list"),
    path("auth/google-accounts/", list_google_accounts),
    path("auth/disconnect-google/", disconnect_google_account),
    path("archive-emails/", archive_email),
    path("delete-emails/", delete_emails),
    path("unsubscribe-emails/", unsubscribe_emails),
    path("emails/<str:message_id>/", email_detail),
    path("", include(router.urls)),
]

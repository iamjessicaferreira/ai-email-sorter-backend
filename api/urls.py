from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    auth_success, list_google_accounts, disconnect_google_account, fetch_emails,
    EmailCategoryViewSet 
)

router = DefaultRouter()
router.register(r'categories', EmailCategoryViewSet, basename='emailcategory')

urlpatterns = [
    path('auth/success/', auth_success),
    path('auth/google-accounts/', list_google_accounts),
    path('auth/disconnect-google/', disconnect_google_account),
    path('fetch-emails/', fetch_emails),
    path('', include(router.urls)),
]

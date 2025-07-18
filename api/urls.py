from django.urls import path
from .views import auth_success, list_google_accounts

urlpatterns = [
    path('auth/success/', auth_success),
    path('auth/google-accounts/', list_google_accounts),
]

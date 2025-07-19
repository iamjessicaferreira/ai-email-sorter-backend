# gmail_services.py

from social_django.models import UserSocialAuth
from .models import GmailAccount
from datetime import datetime, timezone

def update_gmail_account_from_social(user):
    try:
        social = UserSocialAuth.objects.get(user=user, provider='google-oauth2')
    except UserSocialAuth.DoesNotExist:
        return None

    extra_data = social.extra_data
    email = extra_data.get('email') or user.email
    access_token = extra_data.get('access_token')
    refresh_token = extra_data.get('refresh_token') or social.tokens.get('refresh_token')  # ajuste se precisar
    expires = extra_data.get('expires')

    if expires:
        expires_at = datetime.fromtimestamp(int(expires), timezone.utc)
    else:
        expires_at = None

    if not refresh_token:
        refresh_token = social.extra_data.get('refresh_token')

    gmail_account, created = GmailAccount.objects.update_or_create(
        user=user,
        email=email,
        defaults={
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_at': expires_at,
        }
    )
    return gmail_account

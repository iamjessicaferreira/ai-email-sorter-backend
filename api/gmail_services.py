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
    refresh_token = extra_data.get('refresh_token')  # só daqui mesmo
    expires = extra_data.get('expires')

    if expires:
        expires_at = datetime.fromtimestamp(int(expires), timezone.utc)
    else:
        expires_at = None

    gmail_account, created = GmailAccount.objects.get_or_create(user=user, email=email)

    if refresh_token:
        gmail_account.refresh_token = refresh_token

    gmail_account.access_token = access_token
    gmail_account.expires_at = expires_at
    gmail_account.save()

    return gmail_account

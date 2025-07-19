from social_django.models import UserSocialAuth
from .models import GmailAccount
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.conf import settings

def update_gmail_account_from_social(user):
    social_accounts = UserSocialAuth.objects.filter(user=user, provider='google-oauth2')

    for social in social_accounts:
        access_token = social.extra_data.get('access_token')
        refresh_token = social.extra_data.get('refresh_token')
        expires_at_timestamp = social.extra_data.get('expires')

        if not access_token:
            continue  # não tem nem access_token? ignora

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )

        try:
            service = build('gmail', 'v1', credentials=credentials)
            profile = service.users().getProfile(userId='me').execute()
            email_address = profile.get('emailAddress')
        except Exception as e:
            print(f"[OAuth ERROR] Erro ao obter perfil do Gmail: {e}")
            continue

        # Tenta recuperar uma conta existente
        existing_account = GmailAccount.objects.filter(user=user, email=email_address).first()

        if existing_account:
            # Atualiza o access_token e expires_at SEM perder o refresh_token, se ele não vier
            existing_account.access_token = access_token
            existing_account.expires_at = datetime.fromtimestamp(expires_at_timestamp, tz=timezone.utc)

            if refresh_token:  # só sobrescreve se for válido
                existing_account.refresh_token = refresh_token

            existing_account.save()
        else:
            # Cria uma nova conta com todos os campos
            if not refresh_token:
                print(f"[AVISO] Nova conta {email_address} conectada sem refresh_token. Pulei.")
                continue

            GmailAccount.objects.create(
                user=user,
                email=email_address,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=datetime.fromtimestamp(expires_at_timestamp, tz=timezone.utc)
            )

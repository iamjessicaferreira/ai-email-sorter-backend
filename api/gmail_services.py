from social_django.models import UserSocialAuth
from .models import GmailAccount
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from .models import GmailAccount, Email, EmailCategory
from django.conf import settings
import base64
import email as pyemail
from .ai_services import classify_email, summarize_email

def update_gmail_account_from_social(user):
    social_accounts = UserSocialAuth.objects.filter(user=user, provider='google-oauth2')

    for social in social_accounts:
        access_token = social.extra_data.get('access_token')
        refresh_token = social.extra_data.get('refresh_token')
        expires_at_timestamp = social.extra_data.get('expires')
        uid = social.uid  # pega o uid do social auth

        if not access_token:
            continue  # ignora se não tiver token

        expires_at = None
        if expires_at_timestamp:
            try:
                expires_at = datetime.fromtimestamp(expires_at_timestamp, tz=timezone.utc)
            except Exception as e:
                print(f"[WARN] Erro convertendo expires_at: {e}")

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

        existing_account = GmailAccount.objects.filter(uid=uid).first()

        if existing_account:
            existing_account.access_token = access_token
            existing_account.expires_at = expires_at
            if refresh_token:
                existing_account.refresh_token = refresh_token
            existing_account.save()
        else:
            if not refresh_token:
                print(f"[AVISO] Nova conta {email_address} conectada sem refresh_token. Pulei.")
                continue

            GmailAccount.objects.create(
                user=user,
                email=email_address,
                uid=uid,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at
            )

def get_gmail_service(account):
    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
        client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    return build('gmail', 'v1', credentials=creds)

def archive_email_on_gmail(service, message_id):
    try:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={
                'removeLabelIds': ['INBOX']
            }
        ).execute()
        print(f"[GMAIL] Email {message_id} arquivado com sucesso.")
        return True
    except Exception as e:
        print(f"[GMAIL ERROR] Erro ao arquivar email {message_id}: {e}")
        return False


# api/gmail_services.py

from datetime import datetime
from email.utils import parsedate_to_datetime
import base64

# api/gmail_services.py

from datetime import datetime
from email.utils import parsedate_to_datetime
import base64


# api/gmail_services.py

from datetime import datetime
from email.utils import parsedate_to_datetime
import base64

def fetch_and_store_emails(user):
    """
    - Busca sempre os 10 e-mails não-lidos mais recentes
    - Roda IA apenas se wasReviewedByAI=False (cache)
    - Arquiva todos
    - Retorna lista de Email objects
    """
    accounts = GmailAccount.objects.filter(user=user)
    categories = list(
        EmailCategory.objects.filter(user=user)
        .values("name", "description")
    )
    all_emails = []

    for account in accounts:
        service = get_gmail_service(account)
        try:
            resp = service.users().messages().list(
                userId='me',
                labelIds=['INBOX'],
                q="is:unread",
                maxResults=10     # só os 10 mais recentes
            ).execute()
            messages = resp.get('messages', [])
            print(f"[{account.email}] Encontrados {len(messages)} e-mails não lidos (limit 10).")
        except Exception as e:
            print(f"[{account.email}] erro ao listar: {e}")
            continue

        for msg in messages:
            msg_id = msg['id']

            # pega ou instancia
            email_obj = Email.objects.filter(
                gmail_account=account,
                message_id=msg_id
            ).first() or Email(
                gmail_account=account,
                message_id=msg_id
            )

            # busca raw + parse
            raw = service.users().messages().get(
                userId='me', id=msg_id, format='full'
            ).execute()
            payload = raw.get('payload', {})
            headers = payload.get('headers', [])

            subject = next((h['value'] for h in headers if h['name']=="Subject"), "")
            sender  = next((h['value'] for h in headers if h['name']=="From"), "")
            date_str= next((h['value'] for h in headers if h['name']=="Date"), None)
            try:
                received_at = parsedate_to_datetime(date_str) if date_str else datetime.now()
            except:
                received_at = datetime.now()

            # extrai corpo text/plain
            body = ""
            for part in payload.get('parts') or []:
                if part.get('mimeType') == "text/plain":
                    data = part.get('body', {}).get('data')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8','ignore')
                        break
            else:
                data = payload.get('body', {}).get('data')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8','ignore')

            # preenche campos
            email_obj.subject     = subject
            email_obj.sender      = sender
            email_obj.body        = body
            email_obj.received_at = received_at

            # processa IA só se ainda não revisado
            if not email_obj.wasReviewedByAI:
                try:
                    pred = classify_email(subject, body, categories)
                    cat  = EmailCategory.objects.filter(user=user, name=pred).first()
                    email_obj.category        = cat
                    email_obj.summary         = summarize_email(subject, body)
                    email_obj.wasReviewedByAI = True
                except Exception as e:
                    print(f"[AI ERROR] {e}")

            # arquiva sempre
            email_obj.is_archived = archive_email_on_gmail(service, msg_id)

            # salva
            email_obj.save()
            all_emails.append(email_obj)

    return all_emails


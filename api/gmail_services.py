import asyncio
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
from googleapiclient.errors import HttpError

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.db import IntegrityError

from datetime import datetime
from email.utils import parsedate_to_datetime
import base64

from social_django.models import UserSocialAuth
from .models import GmailAccount
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.conf import settings
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

def update_gmail_account_from_social(user):
    """
    Atualiza (ou cria) a GmailAccount do usuário a partir do social auth,
    e inicia um watch no Pub/Sub para receber somente e‑mails novos.
    """
    social_accounts = UserSocialAuth.objects.filter(
        user=user,
        provider='google-oauth2'
    )

    for social in social_accounts:
        access_token  = social.extra_data.get('access_token')
        refresh_token = social.extra_data.get('refresh_token')
        expires_ts    = social.extra_data.get('expires')
        uid           = social.uid

        if not access_token:
            continue

        # converte expires_at
        expires_at = None
        if expires_ts:
            try:
                expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
            except Exception as e:
                print(f"[WARN] Erro convertendo expires_at: {e}")

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.metadata",
            ],
        )

        try:
            service = build('gmail', 'v1', credentials=creds)
            profile = service.users().getProfile(userId='me').execute()
            email_address = profile.get('emailAddress')
        except Exception as e:
            print(f"[OAuth ERROR] Erro ao obter perfil do Gmail: {e}")
            continue

        # cria ou atualiza a instância de GmailAccount
        account, created = GmailAccount.objects.update_or_create(
            uid=uid,
            defaults={
                'user':          user,
                'email':         email_address,
                'access_token':  access_token,
                'refresh_token': refresh_token or account.refresh_token,
                'expires_at':    expires_at,
            }
        )

        # inicia o watch no Pub/Sub para receber apenas novos e‑mails
        try:
            watch_body = {
                "topicName": settings.GMAIL_PUBSUB_TOPIC,
                # opcional: filtrar só INBOX
                "labelFilterAction": "INCLUDE",
                "labelIds": ["INBOX"],
            }
            watch_resp = service.users().watch(
                userId='me',
                body=watch_body
            ).execute()

            account.last_history_id = watch_resp["historyId"]
            # expiration vem em ms desde epoch
            account.watch_expires_at = datetime.fromtimestamp(
                int(watch_resp["expiration"]) // 1000,
                tz=timezone.utc
            )
            account.save()
        except Exception as e:
            print(f"[GMAIL WATCH ERROR] Não foi possível iniciar watch: {e}")



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

def parse_message(full_message):
    """
    Extrai:
      - subject (string)
      - body (HTML completo ou vazio)
      - received_at (datetime, timezone-aware)
    """

    # 1) Headers em dict
    headers = {h["name"]: h["value"] for h in full_message["payload"]["headers"]}

    # 2) Subject
    subject = headers.get("Subject", "")

    # 3) Data do e-mail → datetime
    date_str = headers.get("Date")
    if date_str:
        try:
            received_at = parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                # assume UTC se sem tz
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)
    else:
        received_at = datetime.now(timezone.utc)

    # 4) Função recursiva para achar parte text/html
    def find_html(parts):
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/html" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            # se for multipart, desce na árvore
            if part.get("parts"):
                html = find_html(part["parts"])
                if html:
                    return html
        return None

    payload = full_message["payload"]
    html_body = None

    # multipart?
    if payload.get("mimeType", "").startswith("multipart"):
        html_body = find_html(payload.get("parts", []))
    else:
        # não-multipart: pode ser text/html diretamente
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    body = html_body or ""

    return subject, body, received_at

def extract_sender(full):
    """
    Extract the 'From' header from the full message.
    """
    payload = full.get('payload', {})
    headers = payload.get('headers', [])
    return next((h['value'] for h in headers if h['name'] == 'From'), '')


def get_gmail_service(account: GmailAccount):
    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
        client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    return build('gmail', 'v1', credentials=creds)



def handle_gmail_history(email_address: str, new_history_id: str):
    try:
        account = GmailAccount.objects.get(email=email_address)
    except GmailAccount.DoesNotExist:
        print(f"[WARN] Nenhuma GmailAccount para {email_address}, pulando.")
        return

    service = get_gmail_service(account)
    start_id = account.last_history_id

    try:
        history_resp = service.users().history().list(
            userId="me",
            startHistoryId=start_id,
            historyTypes=["messageAdded"]
        ).execute()
    except HttpError:
        # se o historyId inicial estiver muito antigo, reseta para o atual
        profile = service.users().getProfile(userId="me").execute()
        account.last_history_id = profile["historyId"]
        account.save()
        return

    for history in history_resp.get("history", []):
        for added in history.get("messagesAdded", []):
            msg_id = added["message"]["id"]

            # pula duplicados
            if Email.objects.filter(gmail_account=account, message_id=msg_id).exists():
                continue

            # tenta buscar o e‑mail completo, mas ignora 404s
            try:
                full = service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute()
            except HttpError as e:
                if e.resp.status == 404:
                    print(f"[WARN] Mensagem {msg_id} não encontrada no Gmail, pulando.")
                    continue
                raise

            subject, body, received_at = parse_message(full)
            sender = extract_sender(full)

            # classificar e resumir
            categories    = list(EmailCategory.objects.filter(
                               user=account.user
                             ).values("name", "description"))
            category_name = classify_email(subject, body, categories)
            summary       = summarize_email(subject, body)

            # arquivar no Gmail
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]}
            ).execute()

            # salvar no banco
            category_obj = EmailCategory.objects.filter(
                user=account.user, name=category_name
            ).first()
            try:
                email_obj = Email.objects.create(
                    gmail_account=account,
                    message_id=msg_id,
                    subject=subject,
                    body=body,
                    summary=summary,
                    received_at=received_at,
                    wasReviewedByAI=True,
                    category=category_obj,
                    is_archived=True,
                    sender=sender,
                )
            except IntegrityError:
                print(f"[DB] Race/duplicate on {msg_id}, skipping")
                continue

            # enviar via WebSocket
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{account.user.id}",
                {
                    "type":        "new_email",
                    "id":          email_obj.message_id,
                    "subject":     email_obj.subject,
                    "body":        email_obj.body,
                    "summary":     email_obj.summary,
                    "received_at": email_obj.received_at.isoformat(),
                    "category":    category_name,
                    "account":     account.email,
                },
            )

    # atualizar last_history_id para a próxima rodada
    account.last_history_id = new_history_id
    account.save()
def fetch_and_store_emails(user, limit: int = 10):
    new_emails = []
    for account in GmailAccount.objects.filter(user=user):
        service = get_gmail_service(account)
        categories = list(
                EmailCategory.objects.filter(user=user)
                                    .values("name", "description")
            )
        try:
            
            resp = service.users().messages().list(
                userId="me", labelIds=["INBOX"], q="is:unread", maxResults=limit
            ).execute()
        except HttpError as e:
            print(f"[GMAIL ERROR] Listing emails failed: {e}")
            continue

        for msg in resp.get("messages", []):
            msg_id = msg["id"]

            # ← global check
            if Email.objects.filter(message_id=msg_id).exists():
                continue

            full = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            subject, body, received_at = parse_message(full)
            sender = extract_sender(full)

            # classify/summarize…
            category_name = classify_email(subject, body, categories)
            summary       = summarize_email(subject, body)

            # archive in Gmail…
            try:
                service.users().messages().modify(
                    userId='me', id=msg_id,
                    body={'removeLabelIds': ['INBOX']}
                ).execute()
            except Exception as e:
                print(f"[GMAIL ERROR] Archiving {msg_id} failed: {e}")

            # ← wrap creation in try/except as a belt‑and‑suspenders
            try:
                category_obj = EmailCategory.objects.filter(
                    user=user, name=category_name
                ).first()

                email_obj = Email.objects.create(
                    gmail_account=account,
                    message_id=msg_id,
                    subject=subject,
                    body=body,
                    summary=summary,
                    received_at=received_at,
                    wasReviewedByAI=True,
                    category=category_obj,
                    is_archived=True,
                    sender=sender,
                )
            except IntegrityError:
                # race or duplicate, just skip it
                print(f"[DB] Duplicate email {msg_id}, skipping")
                continue

            new_emails.append(email_obj)

            # broadcast…
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{user.id}",
                {
                    "type": "new_email",
                    "id": email_obj.message_id,
                    "subject": email_obj.subject,
                    "body": email_obj.body,
                    "summary": email_obj.summary,
                    "received_at": email_obj.received_at.isoformat(),
                    "category": category_name,
                    "account": account.email,
                },
            )

    return new_emails

async def _automate_unsubscribe(url: str) -> bool:
    """
    Abre um browser headless, navega até o link de unsubscribe e
    tenta clicar num botão ou submeter formulário.
    Retorna True se encontrar e clicar, False caso contrário.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url, timeout=20000)

        # tenta clicar em algo como "Unsubscribe", "Cancelar inscrição", etc.
        for sel in ['text=Unsubscribe',
                    'text=Cancelar inscrição',
                    'text=Cancelar subscrição',
                    'text=Opt out']:
            try:
                await page.click(sel, timeout=5000)
                await asyncio.sleep(1)
                await browser.close()
                return True
            except PWTimeout:
                continue

        # se não achou nenhum seletor, fecha e retorna False
        await browser.close()
        return False
import asyncio
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError
from requests import Response, request
from social_django.models import UserSocialAuth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .models import GmailAccount, Email, EmailCategory
from .ai_services import classify_email, summarize_email

def _get_categories_for_user(user) -> list[dict]:
    """Helper function to get categories with synonyms for a user."""
    category_objs = EmailCategory.objects.filter(user=user)
    return [
        {
            "name": cat.name,
            "description": cat.description,
            "synonyms": cat.get_synonyms()
        }
        for cat in category_objs
    ]

def update_gmail_account_from_social(user):
    """
    Updates (or creates) the user's GmailAccount from social auth
    and starts a Gmail Pub/Sub watch for new emails.
    """
    print(f"[UPDATE GMAIL ACCOUNT] Starting for user: {user.username} (id: {user.id})")
    social_accounts = UserSocialAuth.objects.filter(
        user=user,
        provider='google-oauth2'
    )
    print(f"[UPDATE GMAIL ACCOUNT] Found {social_accounts.count()} social accounts")
    for social in social_accounts:
        print(f"[UPDATE GMAIL ACCOUNT] Processing social account uid: {social.uid}")
        access_token = social.extra_data.get('access_token')
        refresh_token = social.extra_data.get('refresh_token')
        expires_ts = social.extra_data.get('expires')
        uid = social.uid

        print(f"[UPDATE GMAIL ACCOUNT] uid: {uid}, has_access_token: {bool(access_token)}, has_refresh_token: {bool(refresh_token)}")

        if not access_token:
            print(f"[UPDATE GMAIL ACCOUNT] Skipping {uid} - no access_token")
            continue

        expires_at = None
        if expires_ts:
            try:
                expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
            except Exception as e:
                print(f"[WARN] Error converting expires_at: {e}")

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
        )

        try:
            service = build('gmail', 'v1', credentials=creds)
            profile = service.users().getProfile(userId='me').execute()
            email_address = profile.get('emailAddress')
            print(f"[UPDATE GMAIL ACCOUNT] Got email address: {email_address} for uid: {uid}")
        except Exception as e:
            print(f"[OAuth ERROR] Error getting Gmail profile for uid {uid}: {e}")
            import traceback
            traceback.print_exc()
            continue

        # Check if account exists for this user and uid
        try:
            existing_account = GmailAccount.objects.get(user=user, uid=uid)
            refresh_token_to_use = refresh_token or existing_account.refresh_token
        except GmailAccount.DoesNotExist:
            # Check if account exists with this uid but different user (shouldn't happen, but handle it)
            try:
                existing_account_other_user = GmailAccount.objects.get(uid=uid)
                # If account exists for different user, update it to current user
                existing_account_other_user.user = user
                existing_account_other_user.save()
                refresh_token_to_use = refresh_token or existing_account_other_user.refresh_token
                existing_account = existing_account_other_user
            except GmailAccount.DoesNotExist:
                existing_account = None
                refresh_token_to_use = refresh_token or ''
        
        account, created = GmailAccount.objects.update_or_create(
            uid=uid,
            defaults={
                'user': user,
                'email': email_address,
                'access_token': access_token,
                'refresh_token': refresh_token_to_use,
                'expires_at': expires_at,
            }
        )
        
        # Ensure the account belongs to the current user
        if account.user != user:
            account.user = user
            account.save()
        
        if refresh_token and not account.refresh_token:
            account.refresh_token = refresh_token
            account.save()
        
        print(f"[GMAIL ACCOUNT] {'Created' if created else 'Updated'} GmailAccount: {email_address} (uid: {uid}) for user: {user.username}")

        try:
            watch_body = {
                "topicName": settings.GMAIL_PUBSUB_TOPIC,
                "labelFilterAction": "INCLUDE",
                "labelIds": ["INBOX"],
            }
            watch_resp = service.users().watch(
                userId='me',
                body=watch_body
            ).execute()

            account.last_history_id = watch_resp["historyId"]
            account.watch_expires_at = datetime.fromtimestamp(
                int(watch_resp["expiration"]) // 1000,
                tz=timezone.utc
            )
            account.save()
        except Exception as e:
            print(f"[GMAIL WATCH ERROR] Could not start watch: {e}")

def get_gmail_service(account):
    """
    Returns a Gmail API service instance for the given GmailAccount.
    """
    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
        client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )

    try:
        return build('gmail', 'v1', credentials=creds)
    except HttpError as e:
        if e.resp.status in [401, 403]:
            UserSocialAuth.objects.filter(user=account.user, provider='google-oauth2', uid=account.uid).delete()
            GmailAccount.objects.filter(user=account.user, uid=account.uid).delete()
        raise

def archive_email_on_gmail(service, message_id):
    """
    Archives a given email on Gmail using the API.

    Args:
        service: Gmail API service instance.
        message_id: The Gmail message ID to archive.

    Returns:
        True if successful, False otherwise.
    """
    user = request.user
    message_id = request.data.get("message_id")

    if not message_id:
        return Response({"error": "message_id is required"}, status=400)

    email_obj = Email.objects.filter(message_id=message_id, gmail_account__user=user).first()
    if not email_obj:
        return Response({"error": "Email not found"}, status=404)

    try:
        service = get_gmail_service(email_obj.gmail_account)
        success = archive_email_on_gmail(service, message_id)
    except HttpError as e:
        if e.resp.status in [401, 403]:
            return Response({"error": "Gmail account expired and was disconnected."}, status=401)
        return Response({"error": "Unexpected error"}, status=500)

    if success:
        email_obj.is_archived = True
        email_obj.save()
        return Response({"message": "Email successfully archived"})
    else:
        return Response({"error": "Failed to archive email"}, status=500)



def parse_message(full_message):
    """
    Parses a full Gmail API message and extracts subject, HTML body, and received datetime.

    Args:
        full_message: The full Gmail message (API dict).

    Returns:
        subject (str), body (str), received_at (datetime)
    """
    headers = {h["name"]: h["value"] for h in full_message["payload"]["headers"]}
    subject = headers.get("Subject", "")
    date_str = headers.get("Date")
    if date_str:
        try:
            received_at = parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)
    else:
        received_at = datetime.now(timezone.utc)

    def find_html(parts):
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/html" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            if part.get("parts"):
                html = find_html(part["parts"])
                if html:
                    return html
        return None

    payload = full_message["payload"]
    html_body = None

    if payload.get("mimeType", "").startswith("multipart"):
        html_body = find_html(payload.get("parts", []))
    else:
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    body = html_body or ""
    return subject, body, received_at

def extract_sender(full):
    """
    Extracts the sender ('From' header) from a full Gmail message.

    Args:
        full: The full Gmail message (API dict).

    Returns:
        str: Sender email string or empty if not found.
    """
    payload = full.get('payload', {})
    headers = payload.get('headers', [])
    return next((h['value'] for h in headers if h['name'] == 'From'), '')

def handle_gmail_history(email_address: str, new_history_id: str):
    """
    Fetches new emails added to Gmail since last historyId,
    classifies, summarizes, archives, and stores them, broadcasting via websocket.

    Args:
        email_address (str): The Gmail address for which to sync history.
        new_history_id (str): The latest Gmail history ID to store.
    """
    try:
        account = GmailAccount.objects.get(email=email_address)
    except GmailAccount.DoesNotExist:
        print(f"[WARN] No GmailAccount for {email_address}, skipping.")
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
        profile = service.users().getProfile(userId="me").execute()
        account.last_history_id = profile["historyId"]
        account.save()
        return

    for history in history_resp.get("history", []):
        for added in history.get("messagesAdded", []):
            msg_id = added["message"]["id"]
            if Email.objects.filter(gmail_account=account, message_id=msg_id).exists():
                continue

            try:
                full = service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute()
            except HttpError as e:
                if e.resp.status == 404:
                    print(f"[WARN] Message {msg_id} not found on Gmail, skipping.")
                    continue
                raise

            subject, body, received_at = parse_message(full)
            sender = extract_sender(full)
            categories = _get_categories_for_user(account.user)
            print(f"[EMAIL] Processing email '{subject[:50]}...' for user {account.user.id}")
            print(f"[EMAIL] Found {len(categories)} categories: {[c['name'] for c in categories]}")
            
            category_name = None
            try:
                category_name = classify_email(subject, body, categories)
                print(f"[EMAIL] Classification result: {category_name}")
            except Exception as e:
                print(f"[EMAIL] ERROR during classification: {e}")
                import traceback
                traceback.print_exc()
                category_name = None
            
            summary = None
            try:
                summary = summarize_email(subject, body)
            except Exception as e:
                print(f"[EMAIL] ERROR during summarization: {e}")
                summary = ""

            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]}
            ).execute()

            category_obj = None
            if category_name:
                # Try exact match first
                category_obj = EmailCategory.objects.filter(
                    user=account.user, name=category_name
                ).first()
                
                # If not found, try case-insensitive match
                if not category_obj:
                    category_obj = EmailCategory.objects.filter(
                        user=account.user
                    ).extra(where=["LOWER(name) = LOWER(%s)"], params=[category_name]).first()
                
                if not category_obj:
                    print(f"[EMAIL] WARNING: Category '{category_name}' not found in database for user {account.user.id}")
                    print(f"[EMAIL] Available categories: {[c.name for c in EmailCategory.objects.filter(user=account.user)]}")
                else:
                    print(f"[EMAIL] Category object found: {category_obj.name} (id: {category_obj.id})")
                    # Use the actual category name from database (normalized)
                    category_name = category_obj.name
            else:
                print(f"[EMAIL] No category assigned (category_name is None or empty)")
            
            try:
                email_obj = Email.objects.create(
                    gmail_account=account,
                    message_id=msg_id,
                    subject=subject,
                    body=body,
                    summary=summary or "",
                    received_at=received_at,
                    wasReviewedByAI=True,
                    category=category_obj,
                    is_archived=True,
                    sender=sender,
                )
                print(f"[EMAIL] Created email: {msg_id} - {subject[:50]}")
            except IntegrityError:
                print(f"[DB] Race/duplicate on {msg_id}, skipping")
                continue

            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f"user_{account.user.id}",
                    {
                        "type": "new_email",
                        "id": email_obj.message_id,
                        "subject": email_obj.subject,
                        "body": email_obj.body,
                        "summary": email_obj.summary or "",
                        "received_at": email_obj.received_at.isoformat(),
                        "category": category_name or "none",
                        "account": account.email,
                    },
                )
                print(f"[WEBSOCKET] Sent email {msg_id} to user_{account.user.id}")
            except Exception as e:
                print(f"[WEBSOCKET ERROR] Failed to send email via WebSocket: {e}")

    account.last_history_id = new_history_id
    account.save()

def fetch_and_store_emails(user, limit: int = 10):
    """
    Fetches up to `limit` unread emails for all GmailAccounts of the user,
    classifies, summarizes, archives, saves them, and broadcasts via websocket.

    Args:
        user: Django User instance.
        limit (int): Maximum unread emails to fetch per account.

    Returns:
        list: List of new Email objects created.
    """
    new_emails = []
    categories = _get_categories_for_user(user)
    for account in GmailAccount.objects.filter(user=user):
        service = get_gmail_service(account)
        try:
            resp = service.users().messages().list(
                userId="me", labelIds=["INBOX"], q="is:unread", maxResults=limit
            ).execute()
        except HttpError as e:
            print(f"[GMAIL ERROR] Listing emails failed: {e}")
            continue

        for msg in resp.get("messages", []):
            msg_id = msg["id"]
            if Email.objects.filter(message_id=msg_id).exists():
                continue

            full = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            subject, body, received_at = parse_message(full)
            sender = extract_sender(full)
            print(f"[EMAIL] Processing email '{subject[:50]}...' for user {user.id}")
            print(f"[EMAIL] Found {len(categories)} categories: {[c['name'] for c in categories]}")
            
            category_name = None
            try:
                category_name = classify_email(subject, body, categories)
                print(f"[EMAIL] Classification result: {category_name}")
            except Exception as e:
                print(f"[EMAIL] ERROR during classification: {e}")
                import traceback
                traceback.print_exc()
                category_name = None
            
            summary = None
            try:
                summary = summarize_email(subject, body)
            except Exception as e:
                print(f"[EMAIL] ERROR during summarization: {e}")
                summary = ""
            try:
                service.users().messages().modify(
                    userId='me', id=msg_id,
                    body={'removeLabelIds': ['INBOX']}
                ).execute()
            except Exception as e:
                print(f"[GMAIL ERROR] Archiving {msg_id} failed: {e}")

            try:
                category_obj = None
                if category_name:
                    # Try exact match first
                    category_obj = EmailCategory.objects.filter(
                        user=user, name=category_name
                    ).first()
                    
                    # If not found, try case-insensitive match
                    if not category_obj:
                        category_obj = EmailCategory.objects.filter(
                            user=user
                        ).extra(where=["LOWER(name) = LOWER(%s)"], params=[category_name]).first()
                    
                    if not category_obj:
                        print(f"[EMAIL] WARNING: Category '{category_name}' not found in database for user {user.id}")
                        print(f"[EMAIL] Available categories: {[c.name for c in EmailCategory.objects.filter(user=user)]}")
                    else:
                        print(f"[EMAIL] Category object found: {category_obj.name} (id: {category_obj.id})")
                        # Use the actual category name from database (normalized)
                        category_name = category_obj.name
                else:
                    print(f"[EMAIL] No category assigned (category_name is None or empty)")

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
                print(f"[DB] Duplicate email {msg_id}, skipping")
                continue

            new_emails.append(email_obj)

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

def recategorize_email(email_obj: Email):
    """
    Recategorizes an existing email using AI classification.
    
    Args:
        email_obj: Email instance to recategorize
    
    Returns:
        tuple: (success: bool, category_name: str or None, error: str or None)
    """
    try:
        user = email_obj.gmail_account.user
        categories = _get_categories_for_user(user)
        
        if not categories:
            return False, None, "No categories found for user"
        
        print(f"[RECATEGORIZE] Recategorizing email '{email_obj.subject[:50]}...' (id: {email_obj.message_id})")
        print(f"[RECATEGORIZE] Found {len(categories)} categories: {[c['name'] for c in categories]}")
        
        category_name = classify_email(email_obj.subject, email_obj.body, categories)
        print(f"[RECATEGORIZE] Classification result: {category_name}")
        
        category_obj = None
        if category_name:
            # Try exact match first
            category_obj = EmailCategory.objects.filter(
                user=user, name=category_name
            ).first()
            
            # If not found, try case-insensitive match
            if not category_obj:
                category_obj = EmailCategory.objects.filter(
                    user=user
                ).extra(where=["LOWER(name) = LOWER(%s)"], params=[category_name]).first()
            
            if not category_obj:
                print(f"[RECATEGORIZE] WARNING: Category '{category_name}' not found in database")
                print(f"[RECATEGORIZE] Available categories: {[c.name for c in EmailCategory.objects.filter(user=user)]}")
                return False, category_name, f"Category '{category_name}' not found in database"
            else:
                print(f"[RECATEGORIZE] Category object found: {category_obj.name} (id: {category_obj.id})")
                # Use the actual category name from database (normalized)
                category_name = category_obj.name
        else:
            print(f"[RECATEGORIZE] No category assigned (category_name is None or empty)")
        
        email_obj.category = category_obj
        email_obj.wasReviewedByAI = True
        email_obj.save()
        
        print(f"[RECATEGORIZE] Email successfully recategorized to: {category_name or 'None'}")
        return True, category_name, None
        
    except Exception as e:
        error_msg = f"Error recategorizing email: {str(e)}"
        error_type = type(e).__name__
        print(f"[RECATEGORIZE] {error_msg}")
        print(f"[RECATEGORIZE] Error type: {error_type}")
        import traceback
        traceback_str = traceback.format_exc()
        print(f"[RECATEGORIZE] Traceback: {traceback_str}")
        
        # Provide more specific error messages
        if "categories" in str(e).lower() or "category" in str(e).lower():
            return False, None, f"Category error: {str(e)}"
        elif "classification" in str(e).lower() or "huggingface" in str(e).lower() or "hf" in str(e).lower():
            return False, None, f"AI classification error: {str(e)}"
        elif "database" in str(e).lower() or "db" in str(e).lower():
            return False, None, f"Database error: {str(e)}"
        else:
            return False, None, f"{error_type}: {str(e)}"

async def _automate_unsubscribe(url: str) -> bool:
    """
    Opens a headless browser, navigates to an unsubscribe link, and
    attempts to click an unsubscribe button or submit a form.

    Args:
        url (str): The unsubscribe link to automate.

    Returns:
        bool: True if found and clicked, False otherwise.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url, timeout=20000)
        for sel in [
            'text=Unsubscribe',
            'text=Cancelar inscrição',
            'text=Cancelar subscrição',
            'text=Opt out'
        ]:
            try:
                await page.click(sel, timeout=5000)
                await asyncio.sleep(1)
                await browser.close()
                return True
            except PWTimeout:
                continue
        await browser.close()
        return False

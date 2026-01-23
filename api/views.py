import asyncio
import re
import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions

from api.utils import _automate_unsubscribe, extract_unsubscribe_links
from .models import EmailCategory, GmailAccount, Email
from .serializers import EmailCategorySerializer, EmailSerializer
from .gmail_services import archive_email_on_gmail, get_gmail_service, update_gmail_account_from_social, fetch_and_store_emails, handle_gmail_history
from rest_framework import status

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone
from googleapiclient.errors import HttpError

import base64
import html
import os
from django.conf import settings


@api_view(['GET'])
def auth_complete_redirect(request):
    """
    Callback for social-auth: updates/creates the GmailAccount,
    then redirects the browser to the frontend Dashboard.
    """
    print(f"[AUTH COMPLETE] Processing OAuth callback for user: {request.user.username}")
    # Update/create GmailAccount from social auth
    update_gmail_account_from_social(request.user)
    
    # Verify accounts were created
    accounts = GmailAccount.objects.filter(user=request.user)
    print(f"[AUTH COMPLETE] User {request.user.username} now has {accounts.count()} GmailAccount(s): {[a.email for a in accounts]}")
    
    redirect_url = getattr(settings, 'SOCIAL_AUTH_LOGIN_REDIRECT_URL', 'http://localhost:3000/')
    if '?' in redirect_url:
        redirect_url += '&account_added=true'
    else:
        redirect_url += '?account_added=true'
    return redirect(redirect_url)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_accounts_list(request):
    """
    Returns JSON with all GmailAccount objects for the user.
    Also cleans up orphaned GmailAccounts (accounts without corresponding UserSocialAuth).
    """
    print(f"[AUTH ACCOUNTS] Request from user: {request.user.username} (id: {request.user.id})")
    
    # Check social auth accounts first
    social_accounts = UserSocialAuth.objects.filter(user=request.user, provider='google-oauth2')
    social_uids = set(social_accounts.values_list('uid', flat=True))
    print(f"[AUTH ACCOUNTS] Found {social_accounts.count()} UserSocialAuth entries: {list(social_uids)}")
    
    # Clean up orphaned GmailAccounts (accounts without corresponding UserSocialAuth)
    gmail_accounts = GmailAccount.objects.filter(user=request.user)
    orphaned_accounts = []
    for account in gmail_accounts:
        if account.uid not in social_uids:
            print(f"[AUTH ACCOUNTS] Found orphaned GmailAccount: {account.email} (uid: {account.uid}) - no matching UserSocialAuth")
            orphaned_accounts.append(account)
    
    if orphaned_accounts:
        print(f"[AUTH ACCOUNTS] Cleaning up {len(orphaned_accounts)} orphaned GmailAccount(s)")
        for account in orphaned_accounts:
            # Delete associated emails
            from .models import Email
            email_count = Email.objects.filter(gmail_account=account).count()
            Email.objects.filter(gmail_account=account).delete()
            print(f"[AUTH ACCOUNTS] Deleted {email_count} emails for orphaned account {account.email}")
            # Delete the account
            account.delete()
            print(f"[AUTH ACCOUNTS] Deleted orphaned GmailAccount {account.email}")
    
    # CRITICAL: NEVER call update_gmail_account_from_social from auth_accounts_list
    # This prevents automatic reconnection when user has disconnected accounts.
    # The pipeline (create_gmail_account_after_auth) handles account creation during OAuth.
    # This endpoint should ONLY return existing accounts, not create new ones.
    
    if social_accounts.exists():
        print(f"[AUTH ACCOUNTS] Found {social_accounts.count()} social accounts, but NOT calling update_gmail_account_from_social to prevent auto-reconnection")
    else:
        print(f"[AUTH ACCOUNTS] No social accounts found")
    
    qs = GmailAccount.objects.filter(user=request.user)
    print(f"[AUTH ACCOUNTS] Found {qs.count()} GmailAccount objects for user {request.user.username}")
    for acc in qs:
        print(f"[AUTH ACCOUNTS]   - {acc.email} (uid: {acc.uid})")
    
    data = [{"uid": a.uid, "email": a.email} for a in qs]
    print(f"[AUTH ACCOUNTS] Returning {len(data)} accounts: {data}")
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_google_accounts(request):
    """
    Returns all linked Google OAuth accounts for the authenticated user.
    """
    accounts = UserSocialAuth.objects.filter(user=request.user, provider='google-oauth2')
    data = []
    for account in accounts:
        data.append({
            'uid': account.uid,
            'email': account.extra_data.get('email'),
            'expires_at': account.extra_data.get('expires'),
        })
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disconnect_google_account(request):
    """
    Disconnects a specific Google account and removes the associated GmailAccount.
    Also deletes all emails associated with this account.
    """
    uid = request.data.get('uid')
    if not uid:
        return Response({'error': 'UID is required'}, status=400)
    
    # Check if GmailAccount exists (this is the source of truth)
    gmail_account = GmailAccount.objects.filter(user=request.user, uid=uid).first()
    if not gmail_account:
        return Response({'error': 'Account not found'}, status=404)
    
    email_address = gmail_account.email
    print(f"[DISCONNECT] Disconnecting account {email_address} (uid: {uid}) for user {request.user.username}")
    
    # Delete UserSocialAuth if it exists
    try:
        social_account = UserSocialAuth.objects.get(user=request.user, provider='google-oauth2', uid=uid)
        social_account.delete()
        print(f"[DISCONNECT] Deleted UserSocialAuth for {uid}")
    except UserSocialAuth.DoesNotExist:
        # It's okay if UserSocialAuth doesn't exist, we can still disconnect the GmailAccount
        print(f"[DISCONNECT] No UserSocialAuth found for {uid}")
    
    # Delete all emails associated with this account
    from .models import Email
    email_count = Email.objects.filter(gmail_account=gmail_account).count()
    Email.objects.filter(gmail_account=gmail_account).delete()
    print(f"[DISCONNECT] Deleted {email_count} emails for account {email_address}")
    
    # Delete GmailAccount
    gmail_account.delete()
    print(f"[DISCONNECT] Deleted GmailAccount for {email_address}")
    
    # Verify deletion
    remaining_accounts = GmailAccount.objects.filter(user=request.user, uid=uid).count()
    if remaining_accounts > 0:
        print(f"[DISCONNECT] WARNING: Account {uid} still exists after deletion!")
    else:
        print(f"[DISCONNECT] Successfully disconnected account {email_address}")
    
    return Response({'message': 'Google account disconnected successfully'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disconnect_all_google_accounts(request):
    """
    Disconnects ALL Google accounts for the current user.
    This is more efficient than disconnecting one by one.
    """
    user = request.user
    print(f"[DISCONNECT ALL] Disconnecting all accounts for user {user.username}")
    
    # Get all GmailAccounts for this user
    gmail_accounts = GmailAccount.objects.filter(user=user)
    account_count = gmail_accounts.count()
    
    if account_count == 0:
        return Response({'message': 'No accounts to disconnect'}, status=200)
    
    # Delete all emails associated with these accounts
    from .models import Email
    email_count = Email.objects.filter(gmail_account__user=user).count()
    Email.objects.filter(gmail_account__user=user).delete()
    print(f"[DISCONNECT ALL] Deleted {email_count} emails")
    
    # Delete all UserSocialAuth entries for this user
    social_count = UserSocialAuth.objects.filter(user=user, provider='google-oauth2').delete()[0]
    print(f"[DISCONNECT ALL] Deleted {social_count} UserSocialAuth entries")
    
    # Delete all GmailAccounts
    gmail_count = gmail_accounts.delete()[0]
    print(f"[DISCONNECT ALL] Deleted {gmail_count} GmailAccounts")
    
    # Verify all accounts are deleted
    remaining_accounts = GmailAccount.objects.filter(user=user).count()
    remaining_social = UserSocialAuth.objects.filter(user=user, provider='google-oauth2').count()
    
    if remaining_accounts > 0 or remaining_social > 0:
        print(f"[DISCONNECT ALL] WARNING: Some accounts still exist! GmailAccounts: {remaining_accounts}, UserSocialAuth: {remaining_social}")
        return Response({
            'message': f'Disconnected {gmail_count} accounts, but some may still exist',
            'remaining_accounts': remaining_accounts,
            'remaining_social': remaining_social
        }, status=207)  # Multi-Status
    
    print(f"[DISCONNECT ALL] Successfully disconnected all {gmail_count} accounts for user {user.username}")
    return Response({
        'message': f'Successfully disconnected all {gmail_count} account(s)',
        'accounts_disconnected': gmail_count,
        'emails_deleted': email_count
    })

class EmailCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing email categories per user.
    """
    serializer_class = EmailCategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Returns the queryset for the current user's categories.
        """
        return EmailCategory.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """
        Sets the user as the owner of the category upon creation.
        """
        serializer.save(user=self.request.user)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def has_refresh_token(request):
    """
    Checks if the authenticated user has a GmailAccount with a refresh token.
    """
    user = request.user
    try:
        gmail_account = GmailAccount.objects.get(user=user)
        has_token = bool(gmail_account.refresh_token)
    except GmailAccount.DoesNotExist:
        has_token = False

    return Response({'has_refresh_token': has_token})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def archive_email(request):
    """
    Archives the given email (by message_id) for the current user in both Gmail and local DB.
    """
    user = request.user
    message_id = request.data.get("message_id")

    if not message_id:
        return Response({"error": "message_id is required"}, status=400)

    email_obj = Email.objects.filter(message_id=message_id, gmail_account__user=user).first()
    if not email_obj:
        return Response({"error": "Email not found"}, status=404)

    service = get_gmail_service(email_obj.gmail_account)
    success = archive_email_on_gmail(service, message_id)

    if success:
        email_obj.is_archived = True
        email_obj.save()
        return Response({"message": "Email successfully archived"})
    else:
        return Response({"error": "Failed to archive email"}, status=500)
    
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_emails(request):
    user = request.user
    email_ids = request.data.get('email_ids', [])
    failures = []
    successes = []

    for msg_id in email_ids:
        email_obj = Email.objects.filter(
            gmail_account__user=user,
            message_id=msg_id
        ).first()

        if not email_obj:
            failures.append({'id': msg_id, 'error': 'not found'})
            continue

        try:
            service = get_gmail_service(email_obj.gmail_account)
            service.users().messages().trash(userId='me', id=msg_id).execute()
            email_obj.delete()
            successes.append(msg_id)
        except HttpError as e:
            status = getattr(e.resp, 'status', None)
            if status in [401, 403]:
                from social_django.models import UserSocialAuth
                from api.models import GmailAccount

                uid = email_obj.gmail_account.uid
                UserSocialAuth.objects.filter(user=user, provider='google-oauth2', uid=uid).delete()
                GmailAccount.objects.filter(user=user, uid=uid).delete()
                failures.append({'id': msg_id, 'error': 'Gmail account expired and was disconnected.'})
                break
            failures.append({'id': msg_id, 'error': f'Gmail API: {status}'})
        except Exception as e:
            failures.append({'id': msg_id, 'error': str(e)})

    if failures:
        return Response({
            "message": "Some deletions failed",
            "successes": successes,
            "failures": failures
        }, status=207)

    return Response({"successes": successes, "failures": []}, status=200)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils.decorators import sync_and_async_middleware

from asgiref.sync import sync_to_async
import asyncio


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def unsubscribe_emails(request):
    """
    Attempts to unsubscribe from each email; success only if link found and action completed.
    Returns captcha-specific error if a captcha is detected.
    """
    user = request.user
    email_ids = request.data.get('email_ids', [])
    success_ids = []
    failures = []

    # Só processa cada um em sequência (sync)
    for msg_id in email_ids:
        email_obj = Email.objects.filter(
            gmail_account__user=user, message_id=msg_id
        ).first()
        if not email_obj:
            failures.append({'id': msg_id, 'error': 'not found in DB'})
            continue

        unsubscribe_links = extract_unsubscribe_links(email_obj.body)

        if not unsubscribe_links:
            print(f"[UNSUBSCRIBE] No link found for email {msg_id}")
            failures.append({'id': msg_id,  'subject': email_obj.subject, 'error': 'No unsubscribe link found'})
            continue

        unsubscribed = False
        for link in unsubscribe_links:
            try:
                # Chama a função async DE FORMA BLOQUEANTE (síncrona)
                import asyncio
                result = asyncio.run(_automate_unsubscribe(link))
                if result == "success":
                    print(f"[UNSUBSCRIBE] SUCCESS on link: {link} (email {msg_id})")
                    success_ids.append(msg_id)
                    email_obj.is_unsubscribed = True
                    email_obj.save()
                    unsubscribed = True
                    break
                elif result == "captcha":
                    print(f"[UNSUBSCRIBE] Captcha detected on link: {link} (email {msg_id})")
                    failures.append({'id': msg_id,  'subject': email_obj.subject, 'error': 'Unable to unsubscribe due to a captcha on the page.'})
                    unsubscribed = True
                    break
                else:
                    print(f"[UNSUBSCRIBE] Failed to unsubscribe on link: {link} (email {msg_id})")
            except Exception as e:
                print(f"[UNSUBSCRIBE] Error while trying to unsubscribe: {link} (email {msg_id}): {e}")
                continue

        if not unsubscribed:
            failures.append({'id': msg_id,  'subject': email_obj.subject, 'error': 'Unable to click/unsubscribe.'})

    status_code = 207 if failures else 200
    return Response({'success_ids': success_ids, 'failures': failures}, status=status_code)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_detail(request, message_id):
    """
    Returns the full email for the logged in user, or 404 if not found.
    """
    try:
        email = Email.objects.get(
            gmail_account__user=request.user,
            message_id=message_id
        )
    except Email.DoesNotExist:
        return Response({"detail": "Email not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = EmailSerializer(email)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recategorize_email(request, message_id):
    """
    Recategorizes an email using AI classification.
    """
    try:
        email = Email.objects.get(
            gmail_account__user=request.user,
            message_id=message_id
        )
    except Email.DoesNotExist:
        return Response({"detail": "Email not found"}, status=status.HTTP_404_NOT_FOUND)
    
    from .gmail_services import recategorize_email as recategorize_email_service
    success, category_name, error = recategorize_email_service(email)
    
    if success:
        serializer = EmailSerializer(email)
        return Response({
            "message": "Email recategorized successfully",
            "email": serializer.data,
            "category": category_name
        })
    else:
        return Response({
            "error": error or "Failed to recategorize email",
            "category": category_name
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
def gmail_webhook(request):
    """
    Webhook endpoint to receive Gmail Pub/Sub notifications.
    This endpoint is called by Google Cloud Pub/Sub when new emails arrive.
    """
    try:
        # Parse the Pub/Sub message
        body = json.loads(request.body)
        
        # Pub/Sub sends messages in this format:
        # {
        #   "message": {
        #     "data": "<base64-encoded-json>",
        #     "messageId": "...",
        #     "publishTime": "..."
        #   },
        #   "subscription": "..."
        # }
        
        if 'message' not in body:
            print("[WEBHOOK] Invalid message format - no 'message' field")
            return JsonResponse({'error': 'Invalid message format'}, status=400)
        
        message = body['message']
        if 'data' not in message:
            print("[WEBHOOK] Invalid message format - no 'data' field")
            return JsonResponse({'error': 'Invalid message format'}, status=400)
        
        # Decode the base64-encoded data
        try:
            decoded_data = base64.b64decode(message['data']).decode('utf-8')
            payload = json.loads(decoded_data)
        except Exception as e:
            print(f"[WEBHOOK] Error decoding message data: {e}")
            return JsonResponse({'error': 'Invalid message data'}, status=400)
        
        # Extract email address and history ID from the payload
        email_address = payload.get('emailAddress')
        history_id = payload.get('historyId')
        
        if not email_address or not history_id:
            print(f"[WEBHOOK] Missing required fields - emailAddress: {bool(email_address)}, historyId: {bool(history_id)}")
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        print(f"[WEBHOOK] Received notification for {email_address} with historyId {history_id}")
        
        # Process the Gmail history
        handle_gmail_history(email_address, history_id)
        
        return JsonResponse({'status': 'success'}, status=200)
        
    except json.JSONDecodeError as e:
        print(f"[WEBHOOK] JSON decode error: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"[WEBHOOK] Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Internal server error'}, status=500)

import asyncio
import re
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions

from api.utils import _automate_unsubscribe, extract_unsubscribe_links
from .models import EmailCategory, GmailAccount, Email
from .serializers import EmailCategorySerializer, EmailSerializer
from .gmail_services import archive_email_on_gmail, get_gmail_service, update_gmail_account_from_social, fetch_and_store_emails
from rest_framework import status

from django.views.decorators.csrf import csrf_exempt
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone
from googleapiclient.errors import HttpError

import base64
import html
import os


@api_view(['GET'])
def auth_complete_redirect(request):
    """
    Callback for social-auth: updates/creates the GmailAccount,
    then redirects the browser to the frontend Dashboard.
    """
    update_gmail_account_from_social(request.user)
    return redirect("http://localhost:3000/")

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_accounts_list(request):
    """
    Returns JSON with all GmailAccount objects for the user.
    """
    update_gmail_account_from_social(request.user)
    qs = GmailAccount.objects.filter(user=request.user)
    data = [{"uid": a.uid, "email": a.email} for a in qs]
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
    """
    uid = request.data.get('uid')
    if not uid:
        return Response({'error': 'UID is required'}, status=400)
    try:
        account = UserSocialAuth.objects.get(user=request.user, provider='google-oauth2', uid=uid)
        account.delete()
        GmailAccount.objects.filter(user=request.user, uid=uid).delete()
        return Response({'message': 'Google account disconnected successfully'})
    except UserSocialAuth.DoesNotExist:
        return Response({'error': 'Account not found'}, status=404)

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

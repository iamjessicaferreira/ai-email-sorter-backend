import asyncio
import re
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions
from .models import EmailCategory, GmailAccount, Email
from .serializers import EmailCategorySerializer, EmailSerializer
from .gmail_services import _automate_unsubscribe, archive_email_on_gmail, get_gmail_service, update_gmail_account_from_social, fetch_and_store_emails
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
@permission_classes([IsAuthenticated])
def auth_complete_redirect(request):
    """
    Callback do social-auth: atualiza/cria GmailAccount
    e depois redireciona o navegador para a Dashboard no front.
    """
    update_gmail_account_from_social(request.user)
    # URL da sua aplicação React
    return redirect("http://localhost:3000/")

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_accounts_list(request):
    """
    Retorna JSON com todas as GmailAccount do user.
    """
    update_gmail_account_from_social(request.user)
    qs = GmailAccount.objects.filter(user=request.user)
    data = [{"uid": a.uid, "email": a.email} for a in qs]
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_google_accounts(request):
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
    uid = request.data.get('uid')
    if not uid:
        return Response({'error': 'UID is required'}, status=400)

    try:
        account = UserSocialAuth.objects.get(user=request.user, provider='google-oauth2', uid=uid)
        account.delete()
        # Deletar ou desativar o GmailAccount correspondente
        GmailAccount.objects.filter(user=request.user, uid=uid).delete()
        return Response({'message': 'Conta Google desconectada com sucesso'})
    except UserSocialAuth.DoesNotExist:
        return Response({'error': 'Conta não encontrada'}, status=404)

class EmailCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = EmailCategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return EmailCategory.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def has_refresh_token(request):
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
    user = request.user
    message_id = request.data.get("message_id")

    if not message_id:
        return Response({"error": "message_id é obrigatório"}, status=400)

    email_obj = Email.objects.filter(message_id=message_id, gmail_account__user=user).first()
    if not email_obj:
        return Response({"error": "Email não encontrado"}, status=404)

    service = get_gmail_service(email_obj.gmail_account)
    success = archive_email_on_gmail(service, message_id)

    if success:
        email_obj.is_archived = True
        email_obj.save()
        return Response({"message": "Email arquivado com sucesso"})
    else:
        return Response({"error": "Erro ao arquivar email"}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_emails(request):
    """
    Recebe {"email_ids": ["<msgId>", ...]} e deleta cada um no Gmail e no nosso DB.
    """
    user = request.user
    email_ids = request.data.get('email_ids', [])
    failures = []
    successes = []

    for msg_id in email_ids:
        # garante que pertence ao usuário logado
        email_obj = Email.objects.filter(
            gmail_account__user=user,
            message_id=msg_id
        ).first()

        if not email_obj:
            failures.append({'id': msg_id, 'error': 'não encontrado'})
            continue

        service = get_gmail_service(email_obj.gmail_account)
        try:
            service.users().messages().trash(userId='me', id=msg_id).execute()
            email_obj.delete()
            successes.append(msg_id)  # <-- aqui!
        except HttpError as e:
            failures.append({'id': msg_id, 'error': f'Gmail API: {e.resp.status}'})
        except Exception as e:
            failures.append({'id': msg_id, 'error': str(e)})

    if failures:
        return Response({
            "message": "Algumas deleções falharam",
            "successes": successes,
            "failures": failures
        }, status=207)

    return Response({"successes": successes, "failures": []}, status=200)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def unsubscribe_emails(request):
    """
    Tenta dar unsubscribe em cada email; só conta como sucesso se
    encontrou o link e completou a ação.
    """
    user = request.user
    email_ids = request.data.get('email_ids', [])
    success_ids = []
    failures = []

    for msg_id in email_ids:
        email_obj = Email.objects.filter(
            gmail_account__user=user, message_id=msg_id
        ).first()
        if not email_obj:
            failures.append({'id': msg_id, 'error': 'não encontrado no DB'})
            continue

        # aqui você passa o body ou URL pra sua rotina de Playwright
        try:
            unsub_ok = _automate_unsubscribe(email_obj.body)
        except Exception as e:
            failures.append({'id': msg_id, 'error': str(e)})
            continue

        if unsub_ok:
            success_ids.append(msg_id)
            # flag opcional no DB
            email_obj.is_unsubscribed = True
            email_obj.save()
        else:
            failures.append({'id': msg_id,
                             'error': 'Nenhum link de unsubscribe encontrado'})
    status = 207 if failures else 200
    return Response({'success_ids': success_ids, 'failures': failures}, status=status)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_detail(request, message_id):
    """
    Retorna o email completo para o usuário logado, ou 404 se não existir.
    """
    try:
        email = Email.objects.get(
            gmail_account__user=request.user,
            message_id=message_id
        )
    except Email.DoesNotExist:
        return Response({"detail": "Email não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    serializer = EmailSerializer(email)
    return Response(serializer.data)
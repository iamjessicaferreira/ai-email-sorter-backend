from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions
from .models import EmailCategory, GmailAccount, Email
from .serializers import EmailCategorySerializer
from .gmail_services import update_gmail_account_from_social, fetch_and_store_emails

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone

import base64
import html
import os


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_success(request):
    user = request.user
    update_gmail_account_from_social(user)
    print("SUCESSO: Login com", user.email)
    return redirect('http://localhost:3000/auth/success/')

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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fetch_emails(request):
    user = request.user
    print(f"[FETCH] User logado: {user.id} - {user.email}")

    # 1. Lê o parâmetro ?limit= (padrão: 15)
    try:
        ai_limit = int(request.query_params.get('limit', 15))
    except ValueError:
        return Response({"error": "Parâmetro 'limit' inválido"}, status=400)

    print(f"[FETCH] AI processing limit: {ai_limit}")

    # 2. Busca novos e-mails e salva no banco
    fetch_and_store_emails(user, ai_limit=ai_limit)

    # 3. Monta resposta agrupando por conta e categoria
    gmail_accounts = GmailAccount.objects.filter(user=user)
    response_data = []

    for account in gmail_accounts:
        categories = list(EmailCategory.objects.filter(user=user).values('name', 'description'))
        emails = Email.objects.filter(gmail_account=account).order_by('-received_at')

        emails_by_category = {cat['name']: [] for cat in categories}
        emails_by_category['Sem categoria'] = []

        for email in emails:
            email_data = {
                'id': email.message_id,
                'subject': email.subject,
                'body': email.body,
                'summary': email.summary,
                'received_at': email.received_at.isoformat(),
                'wasReviewedByAI': email.wasReviewedByAI,  # <- agora incluímos isso também
            }

            if email.category:
                emails_by_category[email.category.name].append(email_data)
            else:
                emails_by_category['Sem categoria'].append(email_data)

        categories_data = []
        for cat in categories:
            categories_data.append({
                'name': cat['name'],
                'description': cat['description'],
                'emails': emails_by_category.get(cat['name'], [])
            })

        if emails_by_category['Sem categoria']:
            categories_data.append({
                'name': 'Sem categoria',
                'description': 'Emails sem categoria atribuída',
                'emails': emails_by_category['Sem categoria']
            })

        response_data.append({
            'email': account.email,
            'categories': categories_data
        })

    return Response({
        "message": "Fetched and stored emails successfully",
        "accounts": response_data
    })


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

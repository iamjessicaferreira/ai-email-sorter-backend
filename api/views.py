from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions
from .models import EmailCategory, GmailAccount, Email
from .serializers import EmailCategorySerializer
from .gmail_services import archive_email_on_gmail, get_gmail_service, update_gmail_account_from_social, fetch_and_store_emails

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
    """
    Busca os 10 últimos e-mails não lidos eprocessa IA apenas se flag=False.
    Retorna sempre esses 10 e-mails com category/summary de cache ou IA.
    """
    user = request.user

    # chama sem parâmetro de limite: sempre 10
    emails = fetch_and_store_emails(user)

    # agrupa por conta e categoria
    response = []
    for account in GmailAccount.objects.filter(user=user):
        cats = []
        user_cats = EmailCategory.objects.filter(user=user)
        buckets = {c.name: [] for c in user_cats}

        for e in emails:
            if e.gmail_account_id != account.id:
                continue
            entry = {
                'id': e.message_id,
                'subject': e.subject,
                'body': e.body,
                'summary': e.summary,
                'received_at': e.received_at.isoformat(),
                'wasReviewedByAI': e.wasReviewedByAI,
            }
            if e.category:
                buckets[e.category.name].append(entry)
            else:
                # caso não exista categoria, pode ir pra um grupo “Sem categoria”
                buckets.setdefault('Sem categoria', []).append(entry)

        # montar array de categorias
        for c in user_cats:
            cats.append({
                'name': c.name,
                'description': c.description,
                'emails': buckets[c.name]
            })
        # opcional “Sem categoria” no fim
        if buckets.get('Sem categoria'):
            cats.append({
                'name': 'Sem categoria',
                'description': 'E-mails sem categoria',
                'emails': buckets['Sem categoria']
            })

        response.append({
            'email': account.email,
            'categories': cats,
            'raw_emails': buckets.get('Sem categoria', [])
        })

    return Response({
        'message': 'Fetched last 10 unread emails',
        'accounts': response
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

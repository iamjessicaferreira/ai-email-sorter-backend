from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth
from django.shortcuts import redirect
from rest_framework import viewsets, permissions
from .models import EmailCategory, GmailAccount
from .serializers import EmailCategorySerializer
from .gmail_services import update_gmail_account_from_social

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


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
    print("user", user)

    gmail_accounts = GmailAccount.objects.filter(user=user)
    all_emails = []
    print("accounts", gmail_accounts)

    for account in gmail_accounts:
        try:
           
            creds = Credentials(
                token=account.access_token,
                refresh_token=account.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id="REMOVED_CLIENT_ID",
                client_secret="REMOVED_SECRET",
                scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            )
            print("creds", creds)

        
            if account.expires_at and account.expires_at < datetime.now(timezone.utc):
                creds.refresh(Request()) 
                account.access_token = creds.token
                account.expires_at = datetime.fromtimestamp(creds.expiry.timestamp(), timezone.utc)
                account.save()

            service = build('gmail', 'v1', credentials=creds)

            results = service.users().messages().list(
                userId='me', labelIds=['INBOX'], q="is:unread"
            ).execute()

            print("Lista de mensagens retornadas:", results)

            messages = results.get('messages', [])

            for msg in messages:
                message = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                all_emails.append(message)

        except Exception as e:
            print(f"Erro ao buscar emails da conta {account.email}: {e}")

    return Response({"message": "Fetched emails successfully", "emails_count": len(all_emails)})

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
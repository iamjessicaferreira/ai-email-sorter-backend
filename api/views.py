from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from social_django.models import UserSocialAuth


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_success(request):
    user = request.user
    return Response({
        'message': 'Login successful',
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        }
    })

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
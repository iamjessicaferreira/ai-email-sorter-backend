import pytest

from api.gmail_services import update_gmail_account_from_social
from api.models import GmailAccount

from api.tests.conftest import User

from social_django.models import UserSocialAuth


@pytest.mark.django_db
def test_auth_complete_redirect(monkeypatch, client):
    user = User.objects.create_user(username="testuser", password="123")

    def mock_update_gmail_account_from_social(user):
        pass

    monkeypatch.setattr("api.views.update_gmail_account_from_social", mock_update_gmail_account_from_social)

    response = client.get("/api/auth/complete/google-oauth2/")
    
    assert response.status_code == 302  
    assert response["Location"] == "http://localhost:3000/"  

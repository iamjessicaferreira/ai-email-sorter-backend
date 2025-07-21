import pytest
from social_django.models import UserSocialAuth
from api.gmail_services import update_gmail_account_from_social
from api.models import GmailAccount

@pytest.mark.django_db
def test_disconnect_only_user_can_delete(client, user):
    UserSocialAuth.objects.create(user=user, provider='google-oauth2', uid="test@test.com", extra_data={})
    resp = client.post("/api/auth/disconnect-google/", {"uid": "test@test.com"})
    assert resp.status_code == 200
    assert not UserSocialAuth.objects.filter(uid="test@test.com").exists()

@pytest.mark.django_db
def test_disconnect_google_account(client, user):
    social_account = UserSocialAuth.objects.create(
        user=user, provider="google-oauth2", uid="uid123", extra_data={}
    )
    GmailAccount.objects.create(user=user, email="test@example.com", uid="uid123", access_token="token")

    response = client.post("/api/auth/disconnect-google/", {"uid": "uid123"})
    
    assert response.status_code == 200
    assert "Google account disconnected successfully" in response.json().get('message')
    assert UserSocialAuth.objects.filter(uid="uid123").count() == 0
    assert GmailAccount.objects.filter(uid="uid123").count() == 0

@pytest.mark.django_db
def test_list_google_accounts(client, user):
    UserSocialAuth.objects.create(user=user, provider="google-oauth2", uid="uid123", extra_data={"email": "test@example.com", "expires": "123456789"})

    response = client.get("/api/auth/google-accounts/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["email"] == "test@example.com"
    assert data[0]["uid"] == "uid123"

@pytest.mark.django_db
def test_update_gmail_account_from_social(client, monkeypatch, user):
    social_account = UserSocialAuth.objects.create(
        user=user, provider="google-oauth2", uid="uid123", extra_data={"access_token": "new_token", "refresh_token": "new_refresh_token"}
    )
    
    # Mockar a função build do google
    def mock_build(*args, **kwargs):
        class MockProfile:
            def execute(self):
                return {"emailAddress": "test@example.com"}
        class MockUser:
            def getProfile(self, userId):
                return MockProfile()
        class MockService:
            def users(self):
                return MockUser()
        return MockService()
    
    monkeypatch.setattr("api.gmail_services.build", mock_build)

    update_gmail_account_from_social(user)

    account = GmailAccount.objects.get(user=user, uid="uid123")
    assert account.email == "test@example.com"
    assert account.refresh_token == "new_refresh_token"

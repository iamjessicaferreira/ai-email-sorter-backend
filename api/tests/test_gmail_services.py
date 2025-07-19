import pytest
from django.contrib.auth import get_user_model
from social_django.models import UserSocialAuth
from api.models import GmailAccount
from api.gmail_services import update_gmail_account_from_social
from datetime import datetime, timedelta, timezone

User = get_user_model()

@pytest.mark.django_db
def test_refresh_token_preserved_when_none(monkeypatch):
    # Cria usuário e GmailAccount com refresh_token válido
    user = User.objects.create_user(username="testuser", password="123")
    email = "test@example.com"
    original_refresh_token = "valid_refresh_token"

    GmailAccount.objects.create(
        user=user,
        email=email,
        access_token="old_access_token",
        refresh_token=original_refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Cria um UserSocialAuth com refresh_token=None
    UserSocialAuth.objects.create(
        user=user,
        provider="google-oauth2",
        uid="1234567890",
        extra_data={
            "access_token": "new_access_token",
            "refresh_token": None,  # <- o ponto crítico
            "expires": int((datetime.now() + timedelta(hours=1)).timestamp())
        }
    )

    # Mock do Google API para retornar o mesmo email
    def mock_build(*args, **kwargs):
        class MockProfile:
            def execute(self):
                return {"emailAddress": email}

        class MockUser:
            def getProfile(self, userId):
                return MockProfile()

        class MockService:
            def users(self):
                return MockUser()

        return MockService()

    monkeypatch.setattr("api.gmail_services.build", mock_build)

    # Executa a função
    update_gmail_account_from_social(user)

    # Verifica se o refresh_token original foi preservado
    updated_account = GmailAccount.objects.get(user=user, email=email)
    assert updated_account.refresh_token == original_refresh_token
    assert updated_account.access_token == "new_access_token"

@pytest.mark.django_db
def test_account_created_when_refresh_token_present(monkeypatch):
    user = User.objects.create_user(username="newuser", password="123")
    email = "newaccount@gmail.com"
    refresh_token = "new_refresh_token"

    UserSocialAuth.objects.create(
        user=user,
        provider="google-oauth2",
        uid="xyz",
        extra_data={
            "access_token": "some_token",
            "refresh_token": refresh_token,
            "expires": int((datetime.now() + timedelta(hours=1)).timestamp())
        }
    )

    def mock_build(*args, **kwargs):
        class MockProfile:
            def execute(self):
                return {"emailAddress": email}

        class MockUser:
            def getProfile(self, userId):
                return MockProfile()

        class MockService:
            def users(self):
                return MockUser()

        return MockService()

    monkeypatch.setattr("api.gmail_services.build", mock_build)

    update_gmail_account_from_social(user)

    account = GmailAccount.objects.get(user=user, email=email)
    assert account.refresh_token == refresh_token

@pytest.mark.django_db
def test_account_not_created_if_refresh_token_missing(monkeypatch):
    user = User.objects.create_user(username="usernoaccount", password="123")
    email = "should_not_be_created@gmail.com"

    UserSocialAuth.objects.create(
        user=user,
        provider="google-oauth2",
        uid="no_token_case",
        extra_data={
            "access_token": "valid_token",
            "refresh_token": None,
            "expires": int((datetime.now() + timedelta(hours=1)).timestamp())
        }
    )

    def mock_build(*args, **kwargs):
        class MockProfile:
            def execute(self):
                return {"emailAddress": email}

        class MockUser:
            def getProfile(self, userId):
                return MockProfile()

        class MockService:
            def users(self):
                return MockUser()

        return MockService()

    monkeypatch.setattr("api.gmail_services.build", mock_build)

    update_gmail_account_from_social(user)

    assert not GmailAccount.objects.filter(user=user, email=email).exists()

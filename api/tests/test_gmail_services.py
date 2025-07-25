import pytest
from django.contrib.auth import get_user_model
from social_django.models import UserSocialAuth
from api.models import GmailAccount
from api.gmail_services import update_gmail_account_from_social
from datetime import datetime, timedelta, timezone

User = get_user_model()

@pytest.mark.django_db
def test_account_is_created_when_refresh_token_present(monkeypatch):
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
def test_multiple_gmail_accounts(monkeypatch):
    user = User.objects.create_user(username="multigmailuser", password="123")

    emails = ["acc1@gmail.com", "acc2@gmail.com", "acc3@gmail.com"]
    access_tokens = ["token1", "token2", "token3"]
    refresh_tokens = ["refresh1", "refresh2", "refresh3"]

    for i in range(3):
        UserSocialAuth.objects.create(
            user=user,
            provider="google-oauth2",
            uid=f"uid-{i}",
            extra_data={
                "access_token": access_tokens[i],
                "refresh_token": refresh_tokens[i],
                "expires": int((datetime.now() + timedelta(hours=1)).timestamp())
            }
        )

    def mock_build(*args, **kwargs):
        class MockProfile:
            def __init__(self, email):
                self.email = email
            def execute(self):
                return {"emailAddress": self.email}

        class MockUser:
            def __init__(self, email):
                self.email = email
            def getProfile(self, userId):
                return MockProfile(self.email)

        class MockService:
            def __init__(self, email):
                self.email = email
            def users(self):
                return MockUser(self.email)

        token = kwargs["credentials"].token
        index = access_tokens.index(token)
        email = emails[index]
        return MockService(email)

    monkeypatch.setattr("api.gmail_services.build", mock_build)

    update_gmail_account_from_social(user)

    for i in range(3):
        account = GmailAccount.objects.get(user=user, email=emails[i])
        assert account.refresh_token == refresh_tokens[i]
        assert account.access_token == access_tokens[i]

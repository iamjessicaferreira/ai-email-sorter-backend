from django.utils import timezone
import pytest
from rest_framework.test import APIClient
from api.models import GmailAccount, Email

@pytest.fixture
def client(user):
    client = APIClient()
    client.login(username=user.username, password="testpass")
    return client

@pytest.mark.django_db
def test_archive_email(client, user, monkeypatch):
    account = GmailAccount.objects.create(
        user=user, uid="test", email="test@test.com", access_token="x", refresh_token="dummy"
    )
    email = Email.objects.create(
        gmail_account=account, message_id="123", subject="Hello", body="World", received_at=timezone.now()
    )

    # MOCK: Force a “success” result no Gmail
    monkeypatch.setattr("api.views.archive_email_on_gmail", lambda service, message_id: True)

    resp = client.post("/api/archive-emails/", {"message_id": "123"})
    assert resp.status_code == 200
    assert resp.data["message"] == "Email successfully archived"


@pytest.mark.django_db
def test_unsubscribe_emails_handles_failure(client, user, monkeypatch):
    account = GmailAccount.objects.create(user=user, uid="test", email="test@test.com", access_token="x", refresh_token="dummy")
    email = Email.objects.create(gmail_account=account, message_id="unsub1", subject="Teste", body='<a href="http://fail">unsubscribe</a>', received_at=timezone.now())
    monkeypatch.setattr("api.views._automate_unsubscribe", lambda url: "failure")
    resp = client.post("/api/unsubscribe-emails/", {"email_ids": ["unsub1"]}, format="json")
    assert resp.status_code == 207
    print(resp.data)

    assert resp.data["failures"][0]["id"] == "unsub1"

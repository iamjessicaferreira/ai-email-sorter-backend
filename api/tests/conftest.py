import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


User = get_user_model()

@pytest.fixture
def user(db):
    from uuid import uuid4
    username = f"testuser_{uuid4().hex[:8]}"
    return User.objects.create_user(username=username, password="testpass")


@pytest.fixture
def client(user):
    client = APIClient()
    client.login(username=user.username, password="testpass")
    return client
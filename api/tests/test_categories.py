import pytest
from rest_framework.test import APIClient
from api.models import EmailCategory

@pytest.fixture
def client(user):
    client = APIClient()
    client.login(username=user.username, password="testpass")
    return client

@pytest.mark.django_db
def test_create_category(client):
    resp = client.post("/api/categories/", {"name": "Work", "description": "Job stuff"})
    assert resp.status_code == 201
    assert EmailCategory.objects.filter(name="Work").exists()

@pytest.mark.django_db
def test_list_categories(client, user):
    EmailCategory.objects.create(name="Social", description="Redes", user=user)
    resp = client.get("/api/categories/")
    assert resp.status_code == 200
    assert resp.data[0]["name"] == "Social"

@pytest.mark.django_db
def test_cannot_create_without_login():
    client = APIClient()
    resp = client.post("/api/categories/", {"name": "Spam"})
    assert resp.status_code == 403

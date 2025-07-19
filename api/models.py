from django.db import models
from django.contrib.auth.models import User

class GmailAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='gmail_accounts')
    email = models.EmailField()
    uid = models.CharField(max_length=255, unique=True)
    refresh_token = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.email

class EmailCategory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    description = models.TextField()

    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Email(models.Model):
    gmail_account = models.ForeignKey(GmailAccount, on_delete=models.CASCADE, related_name='emails')
    category = models.ForeignKey(EmailCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='emails')
    message_id = models.CharField(max_length=255, unique=True)
    subject = models.CharField(max_length=255, blank=True)
    sender = models.CharField(max_length=255, blank=True)
    snippet = models.TextField(blank=True)
    body = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    received_at = models.DateTimeField()
    is_archived = models.BooleanField(default=False)
    wasReviewedByAI = models.BooleanField(default=False)

    def __str__(self):
        return self.subject or self.snippet or "E-mail"

from django.db import models
from django.contrib.auth.models import User
import json

class GmailAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='gmail_accounts')
    backlog_cleared = models.BooleanField(default=False)
    email = models.EmailField()
    uid = models.CharField(max_length=255, unique=True)
    refresh_token = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_history_id = models.CharField(max_length=64, blank=True, null=True)
    watch_expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.email

class EmailCategory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    description = models.TextField()
    synonyms = models.TextField(blank=True, default='[]', help_text='JSON array of synonyms for this category')

    def get_synonyms(self):
        """Returns the list of synonyms as a Python list"""
        try:
            return json.loads(self.synonyms) if self.synonyms else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_synonyms(self, synonyms_list):
        """Sets the synonyms from a Python list"""
        self.synonyms = json.dumps(synonyms_list) if synonyms_list else '[]'

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
        return self.subject or self.snippet or "Email"

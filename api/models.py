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
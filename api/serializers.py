# serializers.py
from rest_framework import serializers
from .models import EmailCategory, Email

class EmailCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailCategory
        fields = ['id', 'name', 'description']


class EmailSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", default=None)

    class Meta:
        model = Email
        fields = [
            "message_id",
            "subject",
            "body",
            "summary",
            "received_at",
            "category",
            "sender",
        ]
        read_only_fields = fields

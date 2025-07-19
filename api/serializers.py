# serializers.py
from rest_framework import serializers
from .models import EmailCategory

class EmailCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailCategory
        fields = ['id', 'name', 'description']

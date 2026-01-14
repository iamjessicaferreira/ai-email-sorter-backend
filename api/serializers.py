import json
from rest_framework import serializers
from .models import EmailCategory, Email

class EmailCategorySerializer(serializers.ModelSerializer):
    synonyms = serializers.SerializerMethodField()
    
    class Meta:
        model = EmailCategory
        fields = ['id', 'name', 'description', 'synonyms']
    
    def get_synonyms(self, obj):
        """Returns synonyms as a list"""
        return obj.get_synonyms()
    
    def create(self, validated_data):
        """Handle synonyms when creating"""
        synonyms_list = validated_data.pop('synonyms', [])
        category = EmailCategory.objects.create(**validated_data)
        if synonyms_list:
            category.set_synonyms(synonyms_list)
            category.save()
        return category
    
    def update(self, instance, validated_data):
        """Handle synonyms when updating"""
        synonyms_list = validated_data.pop('synonyms', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if synonyms_list is not None:
            instance.set_synonyms(synonyms_list)
        instance.save()
        return instance

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

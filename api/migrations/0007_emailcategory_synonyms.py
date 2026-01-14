# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_gmailaccount_backlog_cleared_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailcategory',
            name='synonyms',
            field=models.TextField(blank=True, default='[]', help_text='JSON array of synonyms for this category'),
        ),
    ]


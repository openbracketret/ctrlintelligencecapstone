# Generated by Django 3.0.5 on 2020-08-30 12:29

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Camera',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lat', models.DecimalField(blank=True, decimal_places=6, default=None, max_digits=9, null=True)),
                ('long', models.DecimalField(blank=True, decimal_places=6, default=None, max_digits=9, null=True)),
                ('unique_key', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cameras', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

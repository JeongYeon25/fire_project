"""모임 제거 1/4: 화분·할 일 체크에 주인(owner) 칸을 비어 있어도 되게 추가한다."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plants", "0002_remove_plant_character"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="plant",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="plants",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
        migrations.AddField(
            model_name="todocheck",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="todo_checks",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
    ]

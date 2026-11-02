"""모임 제거 3/4: 주인 칸을 필수로 바꾸고 모임 칸·체크한 사람 칸을 없앤다."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plants", "0004_owner_fill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="plant", name="unique_plant_slot"),
        migrations.RemoveConstraint(model_name="todocheck", name="unique_todo_check"),
        migrations.AlterField(
            model_name="plant",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="plants",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
        migrations.AlterField(
            model_name="todocheck",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="todo_checks",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
        migrations.RemoveField(model_name="plant", name="group"),
        migrations.RemoveField(model_name="todocheck", name="group"),
        migrations.RemoveField(model_name="todocheck", name="checked_by"),
        migrations.AlterModelOptions(
            name="plant",
            options={"ordering": ["owner", "slot"], "verbose_name": "화분", "verbose_name_plural": "화분"},
        ),
        migrations.AddConstraint(
            model_name="plant",
            constraint=models.UniqueConstraint(fields=("owner", "slot"), name="unique_plant_owner_slot"),
        ),
        migrations.AddConstraint(
            model_name="todocheck",
            constraint=models.UniqueConstraint(fields=("owner", "date", "key"), name="unique_todo_check_owner"),
        ),
    ]

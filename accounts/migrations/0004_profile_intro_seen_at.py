"""사용 안내 슬라이드를 본 시각. 이미 있는 계정은 '본 것'으로 채워서 안내가 뜨지 않게 한다."""

from django.db import migrations, models
from django.utils import timezone


def mark_existing_seen(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(intro_seen_at__isnull=True).update(intro_seen_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_personal")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="intro_seen_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="사용 안내 본 시각"),
        ),
        # 되돌릴 때는 칸이 없어지므로 따로 할 일이 없다.
        migrations.RunPython(mark_existing_seen, migrations.RunPython.noop),
    ]

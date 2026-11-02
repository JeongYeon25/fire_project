"""모임 제거: 프로필에서 모임을 떼고, 모임의 '실험 조건 변경 시각'을 프로필로 옮긴다. 되돌릴 수 없다."""

from django.db import migrations, models


def copy_condition_changed_at(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    for profile in Profile.objects.exclude(group_id=None).select_related("group"):
        if profile.group.condition_changed_at:
            profile.condition_changed_at = profile.group.condition_changed_at
            profile.save(update_fields=["condition_changed_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_remove_profile_character"),
        # 화분·다이어리 주인 채우기가 Profile.group을 읽은 뒤에 지운다.
        ("plants", "0004_owner_fill"),
        ("diary", "0002_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="condition_changed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="실험 조건 변경 시각"),
        ),
        migrations.RunPython(copy_condition_changed_at),
        migrations.RemoveField(model_name="profile", name="group"),
        migrations.RemoveField(model_name="profile", name="creates_first_plant"),
    ]

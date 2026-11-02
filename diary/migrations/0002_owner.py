"""모임 제거: 다이어리를 개인 기록으로. 모임의 다이어리는 그 모임 회원(화분 주인과 같은 사람)에게 넘긴다.

author 칸은 없앤다(개인 다이어리라 쓴 사람이 늘 주인이고, 자동 기록은 원래 작성자가 없음).
회원이 없는 모임의 다이어리가 있으면 아무것도 바꾸지 않고 멈춘다. 되돌릴 수 없다.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def fill_owners(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    DiaryEntry = apps.get_model("diary", "DiaryEntry")
    first = {}
    for group_id, user_id in Profile.objects.exclude(group_id=None).order_by("pk").values_list("group_id", "user_id"):
        first.setdefault(group_id, user_id)

    orphans = list(DiaryEntry.objects.exclude(group_id__in=first).values_list("pk", "group_id"))
    if orphans:
        raise RuntimeError(f"회원이 없는 모임의 다이어리가 있어 주인을 정할 수 없어요. 아무것도 바꾸지 않았어요. (pk, 모임): {orphans}")

    for group_id, user_id in first.items():
        DiaryEntry.objects.filter(group_id=group_id).update(owner_id=user_id)


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0001_initial"),
        ("accounts", "0002_remove_profile_character"),
        ("plants", "0004_owner_fill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="diaryentry",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="diary_entries",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
        migrations.RunPython(fill_owners),
        migrations.AlterField(
            model_name="diaryentry",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="diary_entries",
                to=settings.AUTH_USER_MODEL,
                verbose_name="주인",
            ),
        ),
        migrations.RemoveField(model_name="diaryentry", name="group"),
        migrations.RemoveField(model_name="diaryentry", name="author"),
    ]

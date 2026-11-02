"""모임 제거 2/4: 모임의 화분·할 일 체크를 그 모임 회원에게 넘긴다.

- 회원이 여러 명이면 가장 먼저 가입한 회원(Profile id가 가장 작은 사람)이 주인이 된다.
- 회원이 없는 모임의 화분·체크가 있으면 아무것도 바꾸지 않고 멈춘다(주인을 임의로 정하지 않는다).
- 되돌릴 수 없다(모임 이름·초대 코드를 되살릴 수 없음). 되돌리려면 백업을 쓴다.
"""

from django.db import migrations


def first_member_by_group(apps):
    Profile = apps.get_model("accounts", "Profile")
    first = {}
    for group_id, user_id in Profile.objects.exclude(group_id=None).order_by("pk").values_list("group_id", "user_id"):
        first.setdefault(group_id, user_id)
    return first


def fill_owners(apps, schema_editor):
    Plant = apps.get_model("plants", "Plant")
    TodoCheck = apps.get_model("plants", "TodoCheck")
    first = first_member_by_group(apps)

    orphan_plants = list(Plant.objects.exclude(group_id__in=first).values_list("pk", "group_id", "slot", "name"))
    orphan_checks = list(TodoCheck.objects.exclude(group_id__in=first).values_list("pk", "group_id", "date", "key"))
    if orphan_plants or orphan_checks:
        raise RuntimeError(
            "회원이 없는 모임의 데이터가 있어 주인을 정할 수 없어요. 아무것도 바꾸지 않았어요.\n"
            f"화분(pk, 모임, 자리, 이름): {orphan_plants}\n할 일 체크(pk, 모임, 날짜, 키): {orphan_checks}"
        )

    for group_id, user_id in first.items():
        Plant.objects.filter(group_id=group_id).update(owner_id=user_id)
        TodoCheck.objects.filter(group_id=group_id).update(owner_id=user_id)


class Migration(migrations.Migration):
    dependencies = [
        ("plants", "0003_owner_add"),
        ("accounts", "0002_remove_profile_character"),
    ]

    operations = [migrations.RunPython(fill_owners)]

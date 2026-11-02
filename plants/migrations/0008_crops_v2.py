"""작물 목록 7종(딸기·토마토·바질·강낭콩·해바라기·상추·봉선화).

- 이미 작물이 들어 있는 DB만 고친다. 빈 DB(새로 만든 DB·테스트 DB)는 그대로 두고 fixture(crops.json)가 넣는다.
- 새 4종은 slug 기준으로 만들거나 고친다. 가능하면 fixture와 같은 pk(6~9)를 쓴다.
- 고추·대파는 지우지 않고 선택 목록에서만 뺀다(is_active=False). 그 작물로 등록된 화분은 그대로 동작한다.
- 토마토·바질·상추의 기준값은 바꾸지 않는다(순서만).
- 새 4종 기준값은 추정값이라 수업 실험 후 보정 필요.
"""

from django.db import migrations

ORDER = {"strawberry": 1, "tomato": 2, "basil": 3, "kidney-bean": 4, "sunflower": 5, "lettuce": 6, "balsam": 7}
INACTIVE = {"pepper": 98, "green-onion": 99}
OLD_ORDER = {"tomato": 1, "lettuce": 2, "basil": 3, "pepper": 4, "green-onion": 5}

NEW_CROPS = [
    (6, {"name": "딸기", "slug": "strawberry", "difficulty": "보통", "water": "자주(촉촉하게)", "sun": "많이(하루 6시간+)",
         "water_threshold": 35, "moisture_min": 45, "moisture_max": 70, "light_threshold": 8,
         "temp_min": 15, "temp_max": 25, "humidity_min": 40, "humidity_max": 70, "color": "#e8445a"}),
    (7, {"name": "강낭콩", "slug": "kidney-bean", "difficulty": "쉬움", "water": "보통", "sun": "많이",
         "water_threshold": 30, "moisture_min": 40, "moisture_max": 65, "light_threshold": 7,
         "temp_min": 18, "temp_max": 27, "humidity_min": 40, "humidity_max": 70, "color": "#b5473a"}),
    (8, {"name": "해바라기", "slug": "sunflower", "difficulty": "쉬움", "water": "보통(겉흙이 마르면)", "sun": "아주 많이",
         "water_threshold": 25, "moisture_min": 35, "moisture_max": 60, "light_threshold": 10,
         "temp_min": 18, "temp_max": 30, "humidity_min": 40, "humidity_max": 70, "color": "#f2b705"}),
    (9, {"name": "봉선화", "slug": "balsam", "difficulty": "쉬움", "water": "자주", "sun": "보통(반그늘 가능)",
         "water_threshold": 35, "moisture_min": 45, "moisture_max": 70, "light_threshold": 5,
         "temp_min": 18, "temp_max": 28, "humidity_min": 40, "humidity_max": 70, "color": "#e5628f"}),
]


def forwards(apps, schema_editor):
    Crop = apps.get_model("plants", "Crop")
    if not Crop.objects.exists():
        return  # 빈 DB는 fixture가 채운다.
    for pk, fields in NEW_CROPS:
        crop = Crop.objects.filter(slug=fields["slug"]).first()
        if crop is None:
            crop = Crop(pk=pk) if not Crop.objects.filter(pk=pk).exists() else Crop()
        for key, value in fields.items():
            setattr(crop, key, value)
        crop.save()
    for slug, order in ORDER.items():
        Crop.objects.filter(slug=slug).update(order=order, is_active=True)
    for slug, order in INACTIVE.items():
        Crop.objects.filter(slug=slug).update(order=order, is_active=False)


def backwards(apps, schema_editor):
    """순서·선택 가능 표시만 예전으로. 새 작물 행은 화분이 쓰고 있을 수 있어 지우지 않고 선택 목록에서만 뺀다."""
    Crop = apps.get_model("plants", "Crop")
    for slug, order in OLD_ORDER.items():
        Crop.objects.filter(slug=slug).update(order=order, is_active=True)
    Crop.objects.filter(slug__in=[f["slug"] for _, f in NEW_CROPS]).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("plants", "0007_crop_is_active")]

    operations = [migrations.RunPython(forwards, backwards)]

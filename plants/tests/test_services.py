from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from plants.models import Crop, Plant, SensorReading
from plants.services import DARK, NODATA, OK, SICK, THIRSTY, TIPS, evaluate, plant_status


class EvaluateTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.tomato = Crop.objects.get(slug="tomato")  # 물 30%, 조도 8klux

    def test_ok(self):
        s = evaluate(self.tomato, 50, 20)
        self.assertEqual(s.state, OK)
        self.assertEqual(s.hp, 5)
        self.assertEqual(s.label, "건강해요")
        self.assertEqual(s.message, "잘 크고 있어요!")
        self.assertEqual(s.tips, TIPS[OK])

    def test_thirsty(self):
        s = evaluate(self.tomato, 17, 20)
        self.assertEqual(s.state, THIRSTY)
        self.assertEqual(s.hp, 3)
        self.assertTrue(s.water_low)
        self.assertFalse(s.light_low)
        self.assertEqual(s.message, "목말라요… 물 주세요")
        self.assertEqual(len(s.tips), 2)

    def test_dark(self):
        s = evaluate(self.tomato, 50, 3)
        self.assertEqual(s.state, DARK)
        self.assertEqual(s.hp, 3)
        self.assertEqual(s.label, "빛이 부족해요")

    def test_sick(self):
        s = evaluate(self.tomato, 10, 3)
        self.assertEqual(s.state, SICK)
        self.assertEqual(s.hp, 1)
        self.assertEqual(s.message, "물도 빛도 부족해서 아파요…")

    def test_threshold_is_not_low(self):
        s = evaluate(self.tomato, 30, 8)
        self.assertEqual(s.state, OK)

    def test_just_below_threshold(self):
        s = evaluate(self.tomato, 29.9, 7.9)
        self.assertEqual(s.state, SICK)

    def test_uses_crop_threshold(self):
        green_onion = Crop.objects.get(slug="green-onion")  # 물 20%, 조도 4klux
        self.assertEqual(evaluate(green_onion, 25, 5).state, OK)
        self.assertEqual(evaluate(self.tomato, 25, 5).state, SICK)

    def test_new_crops_thresholds(self):
        """새 작물 기준값(추정값, 실험 후 보정 필요)."""
        sunflower = Crop.objects.get(slug="sunflower")  # 물 25%, 조도 10klux
        self.assertEqual(evaluate(sunflower, 25, 10).state, OK)
        self.assertEqual(evaluate(sunflower, 50, 9).state, DARK)
        strawberry = Crop.objects.get(slug="strawberry")  # 물 35%, 조도 8klux
        self.assertEqual(evaluate(strawberry, 34, 8).state, THIRSTY)
        kidney_bean = Crop.objects.get(slug="kidney-bean")  # 물 30%, 조도 7klux
        self.assertEqual(evaluate(kidney_bean, 30, 7).state, OK)
        self.assertEqual(evaluate(kidney_bean, 29, 6.9).state, SICK)
        balsam = Crop.objects.get(slug="balsam")  # 물 35%, 조도 5klux
        self.assertEqual(evaluate(balsam, 40, 5).state, OK)

    def test_nodata(self):
        s = evaluate(self.tomato, None, None)
        self.assertEqual(s.state, NODATA)
        self.assertIsNone(s.hp)
        self.assertEqual(s.character_state, OK)


class PlantStatusTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        owner = get_user_model().objects.create_user("새싹", password="plant-pass-77")
        self.plant = Plant.objects.create(owner=owner, slot="A", crop=Crop.objects.get(slug="tomato"))
        self.now = timezone.now()

    def add(self, hours_ago, moisture, light):
        SensorReading.objects.create(
            plant=self.plant,
            measured_at=self.now - timedelta(hours=hours_ago),
            moisture=moisture,
            light=light,
            temp=22,
            humidity=55,
        )

    def test_no_readings(self):
        self.assertEqual(plant_status(self.plant, now=self.now).state, NODATA)

    def test_uses_latest_moisture(self):
        self.add(5, 60, 20)
        self.add(1, 15, 0)
        s = plant_status(self.plant, now=self.now)
        self.assertEqual(s.moisture, 15)
        self.assertEqual(s.state, THIRSTY)

    def test_light_uses_24h_max(self):
        self.add(30, 50, 40)  # 24시간 밖의 밝은 값은 무시
        self.add(10, 50, 6)
        self.add(1, 50, 0)
        s = plant_status(self.plant, now=self.now)
        self.assertEqual(s.max_light_24h, 6)
        self.assertEqual(s.state, DARK)

    def test_light_peak_in_window_is_ok(self):
        self.add(12, 50, 9)
        self.add(1, 50, 0)  # 밤이라 지금은 어두워도 낮 최고값이 기준 이상
        self.assertEqual(plant_status(self.plant, now=self.now).state, OK)

    def test_ignores_future_readings(self):
        self.add(1, 50, 20)
        self.add(-2, 5, 20)
        self.assertEqual(plant_status(self.plant, now=self.now).state, OK)

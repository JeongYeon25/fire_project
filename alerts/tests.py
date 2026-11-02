import json
from datetime import datetime, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog, UserSetting
from alerts.services import check_sensor, process_reading
from plants.models import Crop, Plant, SensorReading

User = get_user_model()


def at(day, hour, minute=0):
    """2026-10-<day> <hour>:<minute> 서울 시각."""
    return timezone.make_aware(datetime(2026, 10, day, hour, minute))


class AlertTestBase(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.tomato = Crop.objects.get(slug="tomato")  # 물 30%, 조도 8klux
        self.user = self.make_user("새싹")
        self.plant = Plant.objects.create(owner=self.user, slot="A", crop=self.tomato)

    def make_user(self, name, **setting):
        user = User.objects.create_user(name, password="plant-pass-77")
        Profile.objects.create(user=user, crop=self.tomato, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        UserSetting.objects.create(user=user, **setting)
        return user

    def read(self, when, moisture=50, light=20, plant=None):
        reading = SensorReading.objects.create(
            plant=plant or self.plant, measured_at=when, moisture=moisture, light=light, temp=22, humidity=55
        )
        return process_reading(reading)

    def alerts(self, kind):
        return AlertLog.objects.filter(plant=self.plant, kind=kind)


class WaterAlertTests(AlertTestBase):
    def test_creates_when_below_threshold(self):
        created = self.read(at(1, 10), moisture=25.6)
        self.assertEqual([a.kind for a in created], ["water"])
        alert = self.alerts("water").get()
        self.assertEqual(alert.message, "토양수분이 30% 아래로 내려갔어요(지금 25%). 물을 주세요.")
        self.assertIsNone(alert.resolved_at)
        self.assertEqual(alert.sent_at, at(1, 10))

    def test_threshold_itself_is_ok(self):
        self.read(at(1, 10), moisture=30)
        self.assertFalse(self.alerts("water").exists())

    def test_no_duplicate_while_open(self):
        self.read(at(1, 10), moisture=25)
        self.read(at(1, 11), moisture=22)
        self.read(at(1, 12), moisture=20)
        self.assertEqual(self.alerts("water").count(), 1)

    def test_resolves_and_can_alert_again(self):
        self.read(at(1, 10), moisture=25)
        self.read(at(1, 11), moisture=60)
        alert = self.alerts("water").get()
        self.assertEqual(alert.resolved_at, at(1, 11))
        self.read(at(2, 10), moisture=28)
        self.assertEqual(self.alerts("water").count(), 2)
        self.assertEqual(self.alerts("water").filter(resolved_at__isnull=True).count(), 1)

    def test_uses_crop_threshold(self):
        self.plant.crop = Crop.objects.get(slug="green-onion")  # 물 20%
        self.plant.save()
        self.read(at(1, 10), moisture=25)
        self.assertFalse(self.alerts("water").exists())
        self.read(at(1, 11), moisture=19)
        self.assertIn("20% 아래로", self.alerts("water").get().message)

    def test_other_plant_does_not_block(self):
        b = Plant.objects.create(owner=self.user, slot="B", crop=self.tomato)
        self.read(at(1, 10), moisture=25)
        self.read(at(1, 10), moisture=25, plant=b)
        self.assertEqual(AlertLog.objects.filter(kind="water").count(), 2)


class SettingTests(AlertTestBase):
    def test_owner_off_no_alert(self):
        UserSetting.objects.filter(user=self.user).update(notify_water=False)
        self.read(at(1, 10), moisture=20)
        self.assertFalse(self.alerts("water").exists())

    def test_only_owner_setting_counts(self):
        """다른 사용자가 켜 두어도 화분 주인이 끄면 만들지 않는다."""
        UserSetting.objects.filter(user=self.user).update(notify_water=False)
        self.make_user("친구")  # 켬
        self.read(at(1, 10), moisture=20)
        self.assertFalse(self.alerts("water").exists())

    def test_other_users_off_does_not_matter(self):
        other = self.make_user("친구", notify_water=False)
        other_plant = Plant.objects.create(owner=other, slot="A", crop=self.tomato)
        self.read(at(1, 10), moisture=20)
        self.read(at(1, 10), moisture=20, plant=other_plant)
        self.assertTrue(self.alerts("water").exists())
        self.assertFalse(AlertLog.objects.filter(plant=other_plant).exists())

    def test_setting_is_per_kind(self):
        UserSetting.objects.filter(user=self.user).update(notify_water=False)
        self.read(at(1, 18), moisture=20, light=1)
        self.assertFalse(self.alerts("water").exists())
        self.assertFalse(self.alerts("light").exists())  # 낮 측정값이 없어서 판정 안 함

    def test_owner_without_setting_counts_as_on(self):
        UserSetting.objects.filter(user=self.user).delete()
        self.read(at(1, 10), moisture=20)
        self.assertTrue(self.alerts("water").exists())

    def test_resolve_even_when_off(self):
        self.read(at(1, 10), moisture=20)
        UserSetting.objects.filter(user=self.user).update(notify_water=False)
        self.read(at(1, 11), moisture=60)
        self.assertIsNotNone(self.alerts("water").get().resolved_at)


class LightAlertTests(AlertTestBase):
    def day(self, day, peak):
        for hour in range(9, 18):
            self.read(at(day, hour), light=peak if hour == 13 else peak / 2)

    def test_not_judged_during_day(self):
        for hour in range(9, 18):
            self.read(at(1, hour), light=2)
        self.assertFalse(self.alerts("light").exists())

    def test_dark_day_alert_after_18(self):
        self.day(1, peak=5.2)
        created = self.read(at(1, 18), light=0)
        self.assertEqual([a.kind for a in created], ["light"])
        self.assertEqual(
            self.alerts("light").get().message,
            "오늘 낮(09~18시) 최고 조도가 5,200 lux로 기준(8,000 lux)보다 낮았어요. 밝은 곳으로 옮겨 주세요.",
        )

    def test_judged_once_per_day(self):
        self.day(1, peak=5)
        self.read(at(1, 18), light=0)
        self.alerts("light").update(resolved_at=at(1, 18, 30))  # 해결된 뒤에도
        self.read(at(1, 19), light=0)
        self.read(at(1, 23), light=0)
        self.assertEqual(self.alerts("light").count(), 1)  # 같은 날 다시 판정하지 않는다

    def test_open_alert_not_duplicated_next_day(self):
        self.day(1, peak=5)
        self.read(at(1, 18), light=0)
        self.day(2, peak=4)
        self.read(at(2, 18), light=0)
        self.assertEqual(self.alerts("light").count(), 1)

    def test_bright_day_resolves(self):
        self.day(1, peak=5)
        self.read(at(1, 18), light=0)
        self.day(2, peak=15)
        self.read(at(2, 18, 10), light=0)
        self.assertEqual(self.alerts("light").get().resolved_at, at(2, 18, 10))

    def test_peak_after_18_not_counted(self):
        self.day(1, peak=5)
        self.read(at(1, 18), light=12)  # 18시 값은 낮 구간(09~18시 전)에 넣지 않는다
        self.assertTrue(self.alerts("light").exists())

    def test_no_daytime_readings(self):
        self.read(at(1, 20), light=0)
        self.assertFalse(self.alerts("light").exists())

    def test_morning_reading_not_judged(self):
        self.read(at(1, 3), light=0)
        self.read(at(1, 9, 5), light=0.5)
        self.assertFalse(self.alerts("light").exists())


class SensorAlertTests(AlertTestBase):
    def test_stale_creates_and_fresh_resolves(self):
        SensorReading.objects.create(plant=self.plant, measured_at=at(1, 10), moisture=50, light=10, temp=22, humidity=55)
        self.assertIsNone(check_sensor(self.plant, at(2, 9)))  # 23시간
        alert = check_sensor(self.plant, at(2, 11))  # 25시간
        self.assertEqual(alert.message, "25시간째 측정값이 들어오지 않아요. 센서 전원과 연결을 확인해 주세요.")
        self.assertIsNone(check_sensor(self.plant, at(2, 15)))  # 미해결이라 중복 없음
        self.read(at(2, 16))
        self.assertEqual(self.alerts("sensor").get().resolved_at, at(2, 16))

    def test_never_measured_no_alert(self):
        self.assertIsNone(check_sensor(self.plant, at(5, 10)))

    def test_command(self):
        SensorReading.objects.create(
            plant=self.plant, measured_at=timezone.now() - timedelta(hours=30), moisture=50, light=10, temp=22, humidity=55
        )
        out = StringIO()
        call_command("check_sensors", stdout=out)
        self.assertIn("센서 점검 알림 1개", out.getvalue())
        call_command("check_sensors", stdout=StringIO())
        self.assertEqual(self.alerts("sensor").count(), 1)

    def test_command_respects_setting(self):
        UserSetting.objects.filter(user=self.user).update(notify_sensor=False)
        SensorReading.objects.create(
            plant=self.plant, measured_at=timezone.now() - timedelta(hours=30), moisture=50, light=10, temp=22, humidity=55
        )
        call_command("check_sensors", stdout=StringIO())
        self.assertFalse(self.alerts("sensor").exists())


class ReadingApiAlertTests(AlertTestBase):
    def post(self, plant, **values):
        body = {"moisture": 50, "light": 10, "temp": 22, "humidity": 55, **values}
        return self.client.post(
            "/api/readings/", data=json.dumps(body), content_type="application/json", HTTP_X_API_KEY=plant.api_key
        )

    def test_api_creates_water_alert(self):
        res = self.post(self.plant, moisture=12)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["alerts"], [{"plant": "A", "kind": "water"}])
        self.assertTrue(self.alerts("water").exists())
        self.assertEqual(self.post(self.plant, moisture=11).json()["alerts"], [])

    def test_api_checks_other_plants_sensor(self):
        b = Plant.objects.create(owner=self.user, slot="B", crop=self.tomato)
        SensorReading.objects.create(plant=b, measured_at=timezone.now() - timedelta(hours=26), moisture=50, light=10, temp=22, humidity=55)
        res = self.post(self.plant)
        self.assertEqual(res.json()["alerts"], [{"plant": "B", "kind": "sensor"}])

    def test_api_does_not_check_other_users_plants(self):
        other_plant = Plant.objects.create(owner=self.make_user("친구"), slot="A", crop=self.tomato)
        SensorReading.objects.create(
            plant=other_plant, measured_at=timezone.now() - timedelta(hours=26), moisture=50, light=10, temp=22, humidity=55
        )
        self.assertEqual(self.post(self.plant).json()["alerts"], [])
        self.assertFalse(AlertLog.objects.filter(plant=other_plant).exists())

    def test_alerts_show_on_screens(self):
        self.client.force_login(self.user)
        self.post(self.plant, moisture=12)
        home = self.client.get("/home/")
        self.assertContains(home, "토양수분이 30% 아래로 내려갔어요(지금 12%). 물을 주세요.")
        self.assertContains(home, "확인 필요")
        self.post(self.plant, moisture=60)
        page = self.client.get("/alerts/")
        self.assertContains(page, "토양수분이 30% 아래로 내려갔어요(지금 12%)")
        self.assertContains(page, "해결됨")

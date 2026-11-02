"""사용 안내 슬라이드와 데이터가 없는 처음 상태(센서값 0건)."""

import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog
from plants.models import Crop, Plant, SensorReading
from plants.services import NODATA, OFFLINE, plant_status

User = get_user_model()
APP_PAGES = ["/home/", "/plants/", "/graph/", "/photos/", "/diary/", "/alerts/", "/tasks/"]


def signup_new_user(client, name="새싹"):
    """실제 흐름대로 가입 → 작물 → 이름까지. 센서값 0건인 A 화분이 생긴다."""
    client.post("/start/signup/", {"nickname": name, "password": "plant-pass-77"})
    client.post("/start/crop/", {"crop": Crop.objects.get(slug="basil").pk})
    client.post("/start/name/", {"name": "바질이"})
    return User.objects.get(username=name)


class IntroTests(TestCase):
    fixtures = ["crops"]

    def test_new_user_sees_intro_until_skip(self):
        user = signup_new_user(self.client)
        self.assertIsNone(user.profile.intro_seen_at)
        for url in APP_PAGES:
            self.assertRedirects(self.client.get(url), "/intro/", msg_prefix=url)
        page = self.client.get("/intro/")
        for title in ("식물이 먼저 말해 줘요", "센서를 연결해 주세요", "필요할 때 알려 드려요", "사진과 다이어리로 남겨요"):
            self.assertContains(page, title)
        self.assertContains(page, "물 부족, 빛 부족, 센서 연결 끊김이 생기면")
        self.assertNotContains(page, "할 일")  # 할 일 알림 문구는 챗봇 단계에서
        self.assertNotContains(page, "캐릭터")
        self.assertContains(page, "건너뛰기")

        res = self.client.post("/intro/done/")  # 건너뛰기 한 번
        self.assertRedirects(res, "/home/")
        self.assertIsNotNone(Profile.objects.get(user=user).intro_seen_at)
        for url in APP_PAGES:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_api_and_admin_not_blocked(self):
        user = signup_new_user(self.client)
        plant = Plant.objects.get(owner=user)
        # 센서 수신 API
        res = self.client.post(
            "/api/readings/", data=json.dumps({"moisture": 50, "light": 10, "temp": 22, "humidity": 55}),
            content_type="application/json", HTTP_X_API_KEY=plant.api_key,
        )
        self.assertEqual(res.status_code, 201)
        # 화면 JSON API·저장도 안내로 보내지 않는다
        self.assertEqual(self.client.get("/api/graph/", {"metric": "moisture"}).status_code, 200)
        res = self.client.post("/api/todo/", data=json.dumps({"key": "water:A", "checked": True}), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        # 관리자 화면
        admin = User.objects.create_superuser("관리자", password="plant-pass-77")
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(self.client.get("/admin/plants/plant/").status_code, 200)

    def test_again_from_settings(self):
        user = signup_new_user(self.client)
        self.client.post("/intro/done/")
        seen = Profile.objects.get(user=user).intro_seen_at
        self.assertContains(self.client.get("/alerts/"), "사용 안내 다시 보기")
        page = self.client.get("/intro/?again=1")
        self.assertContains(page, "닫기")
        res = self.client.post("/intro/done/", {"again": "1"})
        self.assertRedirects(res, "/alerts/")
        self.assertEqual(Profile.objects.get(user=user).intro_seen_at, seen)  # 처음 본 시각은 그대로

    def test_seed_demo_skips_intro(self):
        call_command("seed_demo", verbosity=0)
        self.assertIsNotNone(Profile.objects.get(user__username="demo").intro_seen_at)


class EmptyStateTests(TestCase):
    """센서값 0건인 새 사용자 화면: 정상·물 부족으로 판정하지 않고 안내 + 버튼."""

    fixtures = ["crops"]

    def setUp(self):
        self.user = signup_new_user(self.client)
        self.client.post("/intro/done/")
        self.plant = Plant.objects.get(owner=self.user)

    def test_status_is_nodata_not_ok(self):
        status = plant_status(self.plant)
        self.assertEqual(status.state, NODATA)
        self.assertEqual(status.label, "센서 연결 전")
        self.assertFalse(status.water_low or status.light_low or status.has_problem)
        self.assertIsNone(status.hp)

    def test_home(self):
        home = self.client.get("/home/")
        self.assertNotContains(home, "모든 화분이 건강해요")
        self.assertNotContains(home, "건강해요")
        self.assertNotContains(home, "목이 말라요")
        self.assertContains(home, "아직 센서가 연결되지 않은 화분이 <b>1개</b>", html=False)
        self.assertContains(home, f"/plants/?open={self.plant.pk}")
        self.assertContains(home, "센서 연결하기")
        self.assertContains(home, "아직 센서 값이 없어요")
        self.assertContains(home, "아직 받은 알림이 없어요")
        self.assertContains(home, "할 일을 추가해 보세요")
        self.assertContains(home, "is-waiting")

    def test_plant_list_and_panel(self):
        page = self.client.get("/plants/")
        self.assertContains(page, "센서 연결 전")
        self.assertContains(page, "센서 연결하기 ›")
        self.assertNotContains(page, "설명 없음")
        panel = self.client.get(f"/plants/{self.plant.pk}/panel/")
        self.assertContains(panel, "센서를 연결해 주세요")
        self.assertContains(panel, "센서 API 키 받기")
        self.assertNotContains(panel, "data-metric-gauge")  # 빈 게이지 대신 안내
        self.assertContains(panel, "사진 올리기")
        self.assertContains(panel, "+ 설명 추가")
        # 키 받기: 확인창 없이 바로 키를 한 번 보여 준다
        res = self.client.post(f"/plants/{self.plant.pk}/key/reissue/", follow=True)
        self.plant.refresh_from_db()
        self.assertContains(res, self.plant.api_key)
        self.assertContains(res, "센서 설정에 넣어 주세요")

    def test_other_screens(self):
        self.assertContains(self.client.get("/graph/"), "아직 센서 값이 없어요")
        photos = self.client.get("/photos/")
        self.assertContains(photos, "아직 사진이 없어요")
        self.assertContains(photos, "사진 올리기")
        diary = self.client.get("/diary/")
        self.assertContains(diary, "첫 기록 쓰기")
        alerts = self.client.get("/alerts/")
        self.assertContains(alerts, "아직 받은 알림이 없어요")
        self.assertContains(alerts, "센서 연결하기")

    def test_no_plants_at_all(self):
        self.plant.delete()
        self.assertContains(self.client.get("/home/"), "새 식물 추가")
        self.assertContains(self.client.get("/graph/"), "아직 화분이 없어요")
        self.assertContains(self.client.get("/plants/"), "처음 오셨네요")
        self.assertContains(self.client.get("/photos/"), "새 식물 추가")

    def test_never_connected_plant_gets_no_sensor_alert(self):
        call_command("check_sensors", stdout=StringIO())
        self.assertFalse(AlertLog.objects.filter(plant=self.plant).exists())

    def test_offline_after_24h(self):
        SensorReading.objects.create(
            plant=self.plant, measured_at=timezone.now() - timedelta(hours=30), moisture=10, light=1, temp=22, humidity=55
        )
        status = plant_status(self.plant)
        self.assertEqual((status.state, status.label), (OFFLINE, "센서 연결 끊김"))
        self.assertFalse(status.has_problem)  # 오래된 값으로 물 부족을 판정하지 않는다
        home = self.client.get("/home/")
        self.assertContains(home, "센서 연결이 끊긴 화분이 <b>1개</b>", html=False)
        self.assertNotContains(home, "바질이에 물 주기")  # 자동 할 일도 안 생긴다
        panel = self.client.get(f"/plants/{self.plant.pk}/panel/")
        self.assertContains(panel, "마지막 측정")
        call_command("check_sensors", stdout=StringIO())
        self.assertTrue(AlertLog.objects.filter(plant=self.plant, kind="sensor").exists())

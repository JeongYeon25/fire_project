"""내 기기 화면: 등록(키 한 번만), 재발급, 채널 연결, 보관, 소유자만 접근, 기기 수 제한, 전송 주소."""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from plants.devices import save_rows
from plants.models import Crop, DeviceChannel, DeviceReading, Plant, SensorDevice, SensorReading, generate_device_id

User = get_user_model()
KEY_RE = re.compile(r'id="device-key">([^<]+)<')


def make_user(name, crop):
    user = User.objects.create_user(name, password="plant-pass-77")
    Profile.objects.create(user=user, crop=crop, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
    return user


class DevicePageTestCase(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.tomato = Crop.objects.get(slug="tomato")
        self.me = make_user("새싹", self.tomato)
        self.other = make_user("남", self.tomato)
        self.plants = {s: Plant.objects.create(owner=self.me, slot=s, name=f"토{s}", crop=self.tomato) for s in "ABCD"}
        self.other_plant = Plant.objects.create(owner=self.other, slot="A", name="남의화분", crop=self.tomato)
        self.client.force_login(self.me)

    def nonce(self, url="/devices/"):
        res = self.client.get(url)
        return re.search(r'name="nonce" value="([^"]+)"', res.content.decode()).group(1)

    def add(self, name="창가 Pi", nonce=None):
        return self.client.post("/devices/add/", {"name": name, "nonce": nonce or self.nonce()})

    def added_device(self, res):
        raw = KEY_RE.search(res.content.decode()).group(1)
        return SensorDevice.objects.get(owner=self.me, key_hash__isnull=False, key_prefix=raw[:6]), raw

    def post_reading(self, device, raw, time="2026-10-21T14:30:00"):
        import json

        row = {"time": time, "soil1": 269, "soil2": 590, "soil3": 450, "soil4": 450, "light": 900, "temp": 24.0, "hum": 50.0, "n_samples": 1, "note": ""}
        return Client().post(
            "/api/readings", data=json.dumps({"device_id": device.device_id, "readings": [row]}),
            content_type="application/json", HTTP_X_API_KEY=raw,
        )


class DeviceListTests(DevicePageTestCase):
    def test_empty_list_guides_registration(self):
        res = self.client.get("/devices/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "기기를 등록하세요")
        self.assertContains(res, 'href="/devices/"')  # 사이드 메뉴

    def test_menu_link_on_settings_page(self):
        self.assertContains(self.client.get("/alerts/"), 'href="/devices/"')

    def test_register_shows_key_once_and_receives(self):
        res = self.add("창가 Pi")
        self.assertEqual(res.status_code, 200)
        self.assertIn("no-store", res["Cache-Control"])
        device, raw = self.added_device(res)
        self.assertEqual(device.name, "창가 Pi")
        self.assertRegex(device.device_id, r"^pi-[0-9a-f]{4}$")
        self.assertContains(res, "http://testserver/api/readings")
        self.assertContains(res, device.device_id)
        # 목록·상세에는 키 원문이 다시 나오지 않는다
        for url in ("/devices/", f"/devices/{device.pk}/"):
            page = self.client.get(url)
            self.assertNotContains(page, raw)
            self.assertContains(page, raw[:6] + "…")
        self.assertEqual(self.post_reading(device, raw).status_code, 200)

    def test_resubmit_same_form_does_not_create_again(self):
        nonce = self.nonce()
        self.add(nonce=nonce)
        res = self.add(nonce=nonce)
        self.assertRedirects(res, "/devices/")
        self.assertEqual(SensorDevice.objects.filter(owner=self.me).count(), 1)

    def test_name_required(self):
        res = self.add("   ")
        self.assertRedirects(res, "/devices/")
        self.assertFalse(SensorDevice.objects.exists())

    def test_limit_five_devices(self):
        for i in range(4):
            self.assertEqual(self.add(f"pi {i}").status_code, 200)
        spare = self.nonce()  # 다른 탭에서 열어 둔 등록 폼
        self.assertEqual(self.add("pi 4").status_code, 200)
        self.assertNotContains(self.client.get("/devices/"), "등록하고 키 받기")
        res = self.add("여섯째", nonce=spare)
        self.assertRedirects(res, "/devices/")
        self.assertEqual(SensorDevice.objects.filter(owner=self.me).count(), 5)
        # 보관하면 다시 등록할 수 있다
        first = SensorDevice.objects.filter(owner=self.me).first()
        self.client.post(f"/devices/{first.pk}/archive/")
        self.assertEqual(self.add("여섯째").status_code, 200)

    def test_device_id_rules(self):
        self.assertRegex(generate_device_id("Pi Zero 2"), r"^pi-zero-2-[0-9a-f]{4}$")
        self.assertRegex(generate_device_id("창가 기기"), r"^dev-[0-9a-f]{4}$")
        self.assertRegex(generate_device_id("창가 pi-01"), r"^pi-01-[0-9a-f]{4}$")
        self.assertLessEqual(len(generate_device_id("a" * 60)), 40)

    def test_other_users_devices_not_listed(self):
        SensorDevice.objects.create(device_id="pi-77", name="남의기기", owner=self.other)
        self.assertNotContains(self.client.get("/devices/"), "남의기기")

    @override_settings(PUBLIC_BASE_URL="https://plant.example.com")
    def test_public_base_url_overrides(self):
        res = self.add()
        self.assertContains(res, "https://plant.example.com/api/readings")

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), ALLOWED_HOSTS=[".trycloudflare.com", "testserver"])
    def test_forwarded_proto_https(self):
        nonce = self.nonce()
        res = self.client.post(
            "/devices/add/", {"name": "pi", "nonce": nonce}, HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="abc.trycloudflare.com"
        )
        self.assertContains(res, "https://abc.trycloudflare.com/api/readings")

    @override_settings(SECURE_PROXY_SSL_HEADER=None)  # .env의 DJANGO_TRUST_FORWARDED_PROTO와 상관없이
    def test_without_proxy_setting_forwarded_proto_ignored(self):
        res = self.client.post("/devices/add/", {"name": "pi", "nonce": self.nonce()}, HTTP_X_FORWARDED_PROTO="https")
        self.assertContains(res, "http://testserver/api/readings")

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.me)
        self.assertEqual(client.post("/devices/add/", {"name": "pi"}).status_code, 403)


class DeviceDetailTests(DevicePageTestCase):
    def setUp(self):
        super().setUp()
        self.device = SensorDevice.objects.create(device_id="pi-01", name="옥상기기", owner=self.me)
        self.raw = self.device.issue_key()

    def channels(self, mapping):
        data = {f"ch{ch}": (plant.pk if plant else "") for ch, plant in mapping.items()}
        return self.client.post(f"/devices/{self.device.pk}/channels/", data)

    def links(self):
        return dict(DeviceChannel.objects.filter(device=self.device).values_list("channel", "plant__slot"))

    def test_other_user_gets_404(self):
        theirs = SensorDevice.objects.create(device_id="pi-77", owner=self.other)
        theirs_key = theirs.issue_key()
        for url in (f"/devices/{theirs.pk}/",):
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in ("channels/", "key/reissue/", "archive/"):
            self.assertEqual(self.client.post(f"/devices/{theirs.pk}/{url}", {"ch1": self.plants["A"].pk}).status_code, 404)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.archived_at)
        self.assertEqual(SensorDevice.for_key(theirs_key), theirs)
        self.assertFalse(theirs.channels.exists())

    def test_channel_choices_only_my_plants(self):
        res = self.client.get(f"/devices/{self.device.pk}/")
        self.assertContains(res, "토A")
        self.assertNotContains(res, "남의화분")

    def test_link_save_and_rebuild(self):
        p = self.plants
        res = self.channels({1: p["A"], 2: p["B"], 3: None, 4: None})
        self.assertRedirects(res, f"/devices/{self.device.pk}/")
        self.assertEqual(self.links(), {1: "A", 2: "B", 3: None, 4: None})
        self.assertEqual(self.post_reading(self.device, self.raw).status_code, 200)
        self.assertEqual(SensorReading.objects.get(plant=p["A"]).moisture, 100.0)
        # 맞바꾸기 → 다시 계산
        self.channels({1: p["B"], 2: p["A"], 3: None, 4: None})
        self.assertEqual(SensorReading.objects.get(plant=p["B"]).moisture, 100.0)
        self.assertEqual(SensorReading.objects.get(plant=p["A"]).moisture, 0.0)

    def test_same_plant_twice_refused(self):
        self.channels({1: self.plants["A"], 2: self.plants["A"], 3: None, 4: None})
        self.assertFalse(DeviceChannel.objects.filter(plant__isnull=False).exists())

    def test_other_users_plant_refused(self):
        self.channels({1: self.other_plant, 2: None, 3: None, 4: None})
        self.assertFalse(DeviceChannel.objects.filter(plant=self.other_plant).exists())

    def test_plant_on_my_other_device_refused(self):
        second = SensorDevice.objects.create(device_id="pi-02", owner=self.me)
        DeviceChannel.objects.create(device=second, channel=1, plant=self.plants["A"])
        data = {"ch1": self.plants["A"].pk, "ch2": "", "ch3": "", "ch4": ""}
        res = self.client.post(f"/devices/{self.device.pk}/channels/", data, follow=True)
        self.assertFalse(DeviceChannel.objects.filter(device=self.device, plant=self.plants["A"]).exists())
        self.assertContains(res, "이미 pi-02의 soil1에 연결돼 있어요")

    def test_reissue_shows_new_key_once(self):
        res = self.client.post(f"/devices/{self.device.pk}/key/reissue/", {"nonce": self.nonce(f"/devices/{self.device.pk}/")})
        self.assertEqual(res.status_code, 200)
        new = KEY_RE.search(res.content.decode()).group(1)
        self.assertNotEqual(new, self.raw)
        self.assertEqual(self.post_reading(self.device, self.raw).status_code, 401)
        self.assertEqual(self.post_reading(self.device, new).status_code, 200)
        self.assertNotContains(self.client.get(f"/devices/{self.device.pk}/"), new)

    def test_reissue_resubmit_does_not_change_key_again(self):
        nonce = self.nonce(f"/devices/{self.device.pk}/")
        res = self.client.post(f"/devices/{self.device.pk}/key/reissue/", {"nonce": nonce})
        new = KEY_RE.search(res.content.decode()).group(1)
        again = self.client.post(f"/devices/{self.device.pk}/key/reissue/", {"nonce": nonce})
        self.assertRedirects(again, f"/devices/{self.device.pk}/")
        self.assertEqual(SensorDevice.for_key(new), self.device)

    def test_archive_keeps_data(self):
        DeviceChannel.objects.create(device=self.device, channel=1, plant=self.plants["A"])
        save_rows(self.device, [(0, {"time": "2026-10-21T14:30:00", "soil1": 300, "soil2": "", "soil3": "", "soil4": "", "light": 900, "temp": 24, "hum": 50, "n_samples": 1, "note": ""})])
        before = (DeviceReading.objects.count(), SensorReading.objects.count())
        self.assertEqual(before, (1, 1))
        res = self.client.post(f"/devices/{self.device.pk}/archive/")
        self.assertRedirects(res, "/devices/")
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.archived_at)
        self.assertIsNone(self.device.key_hash)
        self.assertFalse(self.device.channels.exists())
        self.assertEqual((DeviceReading.objects.count(), SensorReading.objects.count()), before)
        self.assertEqual(self.post_reading(self.device, self.raw).status_code, 401)
        self.assertEqual(self.client.get(f"/devices/{self.device.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/devices/"), "옥상기기")
        # device_id는 다시 쓰지 않는다
        self.assertTrue(SensorDevice.objects.filter(device_id="pi-01").exists())

    def test_archived_device_not_rebuilt(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        from plants.devices import ArchivedDeviceError, archive_device, rebuild_device

        archive_device(self.device)
        with self.assertRaises(ArchivedDeviceError):
            rebuild_device(self.device)
        with self.assertRaises(CommandError):
            call_command("rebuild_device_readings", "--device", "pi-01")

    def test_status_labels(self):
        self.assertContains(self.client.get("/devices/"), "아직 수신 없음")
        self.device.last_seen = timezone.now()
        self.device.save()
        self.assertContains(self.client.get("/devices/"), "연결됨")
        self.device.last_seen = timezone.now() - timezone.timedelta(hours=2)
        self.device.save()
        self.assertContains(self.client.get("/devices/"), "연결 끊김")

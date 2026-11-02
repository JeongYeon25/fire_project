"""기기 수신 API: POST /api/readings (규격 docs/hardware/api_spec_261021.txt), /health, 조도 lux 표시."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog
from plants.devices import parse_time
from plants.models import Crop, DeviceChannel, DeviceReading, Plant, SensorDevice, SensorReading
from plants.services import THIRSTY, plant_status

User = get_user_model()
KEY = "test-device-key"
CALIBRATION = {1: (590, 269), 2: (578, 252), 3: (577, 248), 4: (571, 216)}  # 테스트용으로 고정
DRY = (590, 578, 577, 576)  # 0%
WET = (269, 252, 248, 216)  # 100%


def local_str(dt):
    return timezone.localtime(dt).replace(tzinfo=None, microsecond=0).isoformat()


def row(time, soil=(450, 450, 450, 450), light=900, temp=24.0, hum=50.0, n=1, note=""):
    return {
        "time": time, "soil1": soil[0], "soil2": soil[1], "soil3": soil[2], "soil4": soil[3],
        "light": light, "temp": temp, "hum": hum, "n_samples": n, "note": note,
    }


@override_settings(SOIL_CALIBRATION=CALIBRATION)
class DeviceApiTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.owner = User.objects.create_user("8jo", password="plant-pass-77")
        self.tomato = Crop.objects.get(slug="tomato")
        Profile.objects.create(user=self.owner, crop=self.tomato, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        self.device = SensorDevice.objects.create(device_id="pi-01", owner=self.owner)
        self.device.set_key(KEY)  # 키는 DB에 해시로
        other_owner = User.objects.create_user("다른사람", password="plant-pass-77")
        SensorDevice.objects.create(device_id="pi-02", owner=other_owner).set_key("other-device-key")
        self.plants = {}
        for ch, slot in zip(range(1, 5), "ABCD"):
            plant = Plant.objects.create(owner=self.owner, slot=slot, crop=self.tomato)
            DeviceChannel.objects.create(device=self.device, channel=ch, plant=plant)
            self.plants[slot] = plant

    def send(self, readings, key=KEY, device_id="pi-01", url="/api/readings", client=None, raw=None):
        body = raw if raw is not None else json.dumps({"device_id": device_id, "readings": readings})
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return (client or self.client).post(url, data=body, content_type="application/json", **headers)

    def minutes_ago(self, minutes):
        return local_str(timezone.now() - timedelta(minutes=minutes))

    # 인증
    def test_missing_or_wrong_key_401(self):
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], key=None).status_code, 401)
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], key="wrong").status_code, 401)
        # 화분 키로 기기 본문을 보내도 401
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], key=self.plants["A"].api_key).status_code, 401)
        self.assertEqual(DeviceReading.objects.count(), 0)

    def test_unknown_device_or_other_device_key_403(self):
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], device_id="pi-99").status_code, 403)
        # pi-02 키로 pi-01 행을 보냄
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], key="other-device-key").status_code, 403)
        self.assertEqual(DeviceReading.objects.count(), 0)

    # 본문 형식
    def test_200_rows_ok_201_rows_400(self):
        start = parse_time("2026-10-21T00:00:00")
        rows = [row(local_str(start + timedelta(minutes=i))) for i in range(201)]
        res = self.send(rows)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(DeviceReading.objects.count(), 0)
        res = self.send(rows[:200])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"saved": 200, "skipped": []})
        self.assertEqual(DeviceReading.objects.count(), 200)
        self.assertEqual(SensorReading.objects.count(), 800)

    def test_bad_body_400(self):
        self.assertEqual(self.send(None, raw="{not json").status_code, 400)
        self.assertEqual(self.send(None, raw=json.dumps({"device_id": "pi-01", "readings": {"time": "x"}})).status_code, 400)
        self.assertEqual(self.send(None, raw=json.dumps({"readings": []})).status_code, 400)  # device_id 없음

    def test_empty_readings_200(self):
        self.assertEqual(self.send([]).json(), {"saved": 0, "skipped": []})

    def test_bad_rows_skipped_rest_saved_200(self):
        rows = [
            row("2026-10-21T14:30:00"),
            {"time": "어제", "soil1": 500},
            row("2026-10-21T14:31:00", temp="hot"),
            "not an object",
            row("2026-10-21T14:32:00"),
        ]
        res = self.send(rows)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["saved"], 2)
        self.assertEqual([s["index"] for s in data["skipped"]], [1, 2, 3])
        self.assertTrue(all(s["reason"] for s in data["skipped"]))
        self.assertEqual(DeviceReading.objects.count(), 2)

    def test_duplicate_time_in_request_reports_earlier_row(self):
        res = self.send([row("2026-10-21T14:30:00", temp=20), row("2026-10-21T14:30:00", temp=21)])
        self.assertEqual(res.json()["saved"], 1)
        self.assertEqual([s["index"] for s in res.json()["skipped"]], [0])
        self.assertEqual(DeviceReading.objects.get().temp, 21)

    def test_upsert_twice_same_result(self):
        rows = [row("2026-10-21T14:30:00"), row("2026-10-21T14:31:00", soil=WET)]
        self.assertEqual(self.send(rows).json()["saved"], 2)
        first = list(SensorReading.objects.order_by("plant__slot", "measured_at").values_list("plant__slot", "measured_at", "moisture"))
        self.assertEqual(self.send(rows).json()["saved"], 2)
        self.assertEqual(DeviceReading.objects.count(), 2)
        second = list(SensorReading.objects.order_by("plant__slot", "measured_at").values_list("plant__slot", "measured_at", "moisture"))
        self.assertEqual(first, second)

    def test_light_float_and_null_cells_saved(self):
        res = self.send([{"time": "2026-10-21T14:30:00", "soil1": None, "soil2": 500, "soil3": None, "soil4": None,
                          "light": 3421.7, "temp": None, "hum": None, "n_samples": 1, "note": "bad_lines=3"}])
        self.assertEqual(res.json(), {"saved": 1, "skipped": []})
        reading = DeviceReading.objects.get()
        self.assertEqual((reading.light, reading.soil1, reading.note), (3421.7, None, "bad_lines=3"))
        self.assertEqual(list(SensorReading.objects.values_list("plant__slot", flat=True)), ["B"])

    # 칸별 null
    def test_dht_fail_keeps_water_judgment(self):
        at = self.minutes_ago(2)
        res = self.send([row(at, soil=DRY, temp=None, hum=None, note="dht_fail")])
        self.assertEqual(res.status_code, 200)
        sr = SensorReading.objects.get(plant=self.plants["A"])
        self.assertEqual((sr.moisture, sr.temp, sr.humidity), (0.0, None, None))
        self.assertEqual(plant_status(self.plants["A"]).state, THIRSTY)
        self.assertTrue(AlertLog.objects.filter(plant=self.plants["A"], kind="water").exists())

    def test_no_data_and_zero_samples_make_no_plant_values(self):
        self.send([
            {"time": "2026-10-21T14:30:00", "soil1": None, "soil2": None, "soil3": None, "soil4": None,
             "light": None, "temp": None, "hum": None, "n_samples": 0, "note": "no_data"},
            row("2026-10-21T14:31:00", n=0),  # 값이 있어도 n_samples=0이면 쓰지 않는다
        ])
        self.assertEqual(DeviceReading.objects.count(), 2)
        self.assertEqual(SensorReading.objects.count(), 0)
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_seen, parse_time("2026-10-21T14:31:00"))

    # 교정 구간
    def test_rows_before_ignore_time_keep_raw_only(self):
        self.send([row("2026-10-12T08:14:00"), row("2026-10-12T08:15:00")])
        self.assertEqual(DeviceReading.objects.count(), 2)
        times = set(SensorReading.objects.values_list("measured_at", flat=True))
        self.assertEqual(times, {parse_time("2026-10-12T08:15:00")})

    @override_settings(SENSOR_IGNORE_BEFORE=None)
    def test_ignore_time_can_be_turned_off(self):
        self.send([row("2026-10-12T08:14:00")])
        self.assertEqual(SensorReading.objects.count(), 4)

    # 주소·CSRF
    def test_with_and_without_slash_no_redirect(self):
        for debug in (False, True):
            with override_settings(DEBUG=debug):
                for i, url in enumerate(["/api/readings", "/api/readings/"]):
                    res = self.send([row(f"2026-10-21T1{i}:0{int(debug)}:00")], url=url)
                    self.assertEqual(res.status_code, 200, (debug, url))
        self.assertEqual(DeviceReading.objects.count(), 4)

    def test_csrf_exempt(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.send([row("2026-10-21T14:30:00")], client=client).status_code, 200)

    # 기존 화분별 키 API 호환
    def test_plant_key_api_still_works_on_both_urls(self):
        plant = Plant.objects.create(owner=self.owner, slot="E", crop=self.tomato)
        body = json.dumps({"moisture": 42.5, "light": 12.3, "temp": 23.1, "humidity": 55})
        for url in ("/api/readings/", "/api/readings"):
            res = self.client.post(url, data=body, content_type="application/json", HTTP_X_API_KEY=plant.api_key)
            self.assertEqual(res.status_code, 201, url)
        self.assertEqual(plant.readings.count(), 2)
        # 화분 키로 깨진 JSON은 400, 틀린 키는 401 (기존 그대로)
        res = self.client.post("/api/readings", data="{", content_type="application/json", HTTP_X_API_KEY=plant.api_key)
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/readings", data="{", content_type="application/json", HTTP_X_API_KEY="nope")
        self.assertEqual(res.status_code, 401)

    def test_device_key_with_plant_body_400(self):
        body = json.dumps({"moisture": 42.5, "light": 12.3, "temp": 23.1, "humidity": 55})
        res = self.client.post("/api/readings", data=body, content_type="application/json", HTTP_X_API_KEY=KEY)
        self.assertEqual(res.status_code, 401)  # 기기 키는 화분이 아니다
        res = self.client.post("/api/readings", data="{", content_type="application/json", HTTP_X_API_KEY=KEY)
        self.assertEqual(res.status_code, 400)

    # 알림
    def test_alert_only_for_recent_latest_row(self):
        self.send([row(self.minutes_ago(30), soil=WET), row(self.minutes_ago(3), soil=DRY)])
        self.assertEqual(AlertLog.objects.filter(kind="water").count(), 4)

    def test_no_alert_for_rows_older_than_one_hour(self):
        self.send([row(self.minutes_ago(90), soil=DRY)])
        self.assertEqual(AlertLog.objects.count(), 0)

    def test_no_alert_for_resent_older_rows(self):
        self.send([row(self.minutes_ago(2), soil=WET)])
        self.send([row(self.minutes_ago(10), soil=DRY)])  # 밀린 옛 줄을 다시 보냄
        self.assertFalse(AlertLog.objects.filter(kind="water").exists())

    def test_first_upload_query_count(self):
        start = parse_time("2026-10-15T00:00:00")
        rows = [row(local_str(start + timedelta(minutes=i))) for i in range(200)]
        body = json.dumps({"device_id": "pi-01", "readings": rows})
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.post("/api/readings", data=body, content_type="application/json", HTTP_X_API_KEY=KEY)
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 25, [q["sql"][:80] for q in ctx.captured_queries])


class HealthTests(TestCase):
    @override_settings(SENSOR_DEVICE_KEYS={"pi-01": "secret-device-key"})
    def test_health_without_login(self):
        for url in ("/health", "/health/"):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"status": "ok"})
            self.assertNotIn("secret", res.content.decode())
        self.assertEqual(self.client.post("/health").status_code, 405)


class LuxDisplayTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.user = User.objects.create_user("새싹", password="plant-pass-77")
        tomato = Crop.objects.get(slug="tomato")
        Profile.objects.create(user=self.user, crop=tomato, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        self.plant = Plant.objects.create(owner=self.user, slot="A", name="토토", crop=tomato)
        SensorReading.objects.create(
            plant=self.plant, measured_at=timezone.now() - timedelta(minutes=5), moisture=50, light=3.4217, temp=22, humidity=55
        )
        self.client.force_login(self.user)

    def test_panel_shows_lux(self):
        res = self.client.get(f"/plants/{self.plant.pk}/panel/")
        self.assertContains(res, "3,422")
        self.assertContains(res, "lux")
        self.assertContains(res, "낮 최고 8,000 lux 이상이면 충분해요")
        self.assertNotContains(res, "klux")

    def test_graph_values_in_lux(self):
        # range=today는 자정 직후(5분 전 값이 어제)에 비므로 7d로 본다
        data = self.client.get("/api/graph/?metric=light&range=7d").json()
        self.assertEqual(data["unit"], "lux")
        self.assertEqual(data["series"][0]["values"], [3421.7])
        self.assertEqual(data["thresholds"][0]["value"], 8000)
        self.assertEqual(data["thresholds"][0]["label"], "토마토 조도 기준 8,000lux")
        self.assertIsNone(data["light_unit_changed_at"])

    def test_graph_marks_light_sensor_change(self):
        since = timezone.localtime() - timedelta(hours=1)
        with override_settings(LIGHT_LUX_SINCE=since.replace(tzinfo=None, microsecond=0).isoformat()):
            light = self.client.get("/api/graph/?metric=light&range=7d").json()
            moisture = self.client.get("/api/graph/?metric=moisture&range=7d").json()
        self.assertEqual(light["light_unit_changed_at"], since.replace(microsecond=0).isoformat())
        self.assertIsNone(moisture["light_unit_changed_at"])

    def test_graph_keeps_empty_cds_period_on_axis_when_marked(self):
        # 교체 전(CdS) 값은 light가 비어 있다 → 세로선이 있으면 가로축에 남고 값은 None
        SensorReading.objects.create(
            plant=self.plant, measured_at=timezone.now() - timedelta(hours=3), moisture=50, light=None, temp=22, humidity=55
        )
        self.assertEqual(len(self.client.get("/api/graph/?metric=light&range=7d").json()["times"]), 1)
        since = timezone.localtime() - timedelta(hours=1)
        with override_settings(LIGHT_LUX_SINCE=since.replace(tzinfo=None, microsecond=0).isoformat()):
            data = self.client.get("/api/graph/?metric=light&range=7d").json()
        self.assertEqual(len(data["times"]), 2)
        self.assertEqual(data["series"][0]["values"], [None, 3421.7])

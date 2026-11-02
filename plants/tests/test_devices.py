"""하드웨어 센서 기기: 원시값 저장(UPSERT), 화분 값 계산, 판정 연결, CSV 가져오기, 기기 등록."""

import shutil
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog
from alerts.services import check_light, check_sensor
from plants.devices import RowError, clean_row, light_klux, parse_time, rebuild_device, save_rows, soil_percent
from plants.models import Crop, DeviceChannel, DeviceReading, Plant, SensorDevice, SensorReading
from plants.services import OFFLINE, OK, THIRSTY, DARK, evaluate, plant_status

User = get_user_model()
SEOUL = ZoneInfo("Asia/Seoul")
HEADER = "time,soil1,soil2,soil3,soil4,light,temp,hum,n_samples,note\n"
# 테스트는 보정값을 고정해 둔다(settings.SOIL_CALIBRATION을 바꿔도 계산 규칙 테스트가 흔들리지 않게).
CALIBRATION = {1: (590, 269), 2: (578, 252), 3: (577, 248), 4: (571, 216)}


def row(time, soil=(450, 450, 450, 450), light=900, temp=24.0, hum=50.0, n=1, note=""):
    return {
        "time": time,
        "soil1": soil[0],
        "soil2": soil[1],
        "soil3": soil[2],
        "soil4": soil[3],
        "light": light,
        "temp": temp,
        "hum": hum,
        "n_samples": n,
        "note": note,
    }


def no_data(time):
    return {"time": time, "soil1": "", "soil2": "", "soil3": "", "soil4": "", "light": "", "temp": "", "hum": "", "n_samples": 0, "note": "no_data"}


def local_str(dt):
    """aware → CSV처럼 시간대 없는 서울 시각 문자열."""
    return timezone.localtime(dt).replace(tzinfo=None, microsecond=0).isoformat()


@override_settings(SOIL_CALIBRATION=CALIBRATION)
class DeviceTestCase(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.owner = User.objects.create_user("8jo", password="plant-pass-77")
        self.tomato = Crop.objects.get(slug="tomato")
        Profile.objects.create(user=self.owner, crop=self.tomato, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        self.device = SensorDevice.objects.create(device_id="pi-01", owner=self.owner)
        self.plants = {}
        for ch, slot in zip(range(1, 5), "ABCD"):
            plant = Plant.objects.create(owner=self.owner, slot=slot, crop=self.tomato)
            DeviceChannel.objects.create(device=self.device, channel=ch, plant=plant)
            self.plants[slot] = plant

    def save(self, rows, **kw):
        return save_rows(self.device, [(i, r) for i, r in enumerate(rows)], **kw)


@override_settings(SOIL_CALIBRATION=CALIBRATION)
class SoilPercentTests(TestCase):
    """보정값(공기, 물속): ch1 590/269, ch2 578/252, ch3 577/248, ch4 571/216 — 분모 321/326/329/355.
    0~100으로 자르고, 0·1023 초과는 판정에서 뺀다."""

    def test_calibration_per_channel(self):
        self.assertEqual(soil_percent(1, 590), 0.0)
        self.assertEqual(soil_percent(1, 269), 100.0)
        # 10-21 18:02 원시값 299/234/306/254 → 90.7 / (105.5 → 100) / 82.4 / 89.3
        self.assertEqual(soil_percent(1, 299), 90.7)
        self.assertEqual(soil_percent(2, 234), 100.0)
        self.assertEqual(soil_percent(3, 306), 82.4)
        self.assertEqual(soil_percent(4, 254), 89.3)

    def test_channel4_dry_soil_and_right_after_watering(self):
        # 4번: 마른 흙 571 = 0%, 물 흠뻑 준 직후 216 = 100%. 11-01 원시값 429 → 40.0
        self.assertEqual(soil_percent(4, 571), 0.0)
        self.assertEqual(soil_percent(4, 216), 100.0)
        self.assertEqual(soil_percent(4, 429), 40.0)

    def test_clamped_above_100_right_after_watering(self):
        # 물 준 직후처럼 물속 기준보다 낮은 원시값 → 100을 넘는 계산값은 100
        self.assertEqual(soil_percent(1, 265), 100.0)
        self.assertEqual(soil_percent(2, 218), 100.0)
        self.assertEqual(soil_percent(4, 210), 100.0)

    def test_clamped_below_0(self):
        # 공기 기준보다 큰 원시값(sample_data soil4 713) → 0
        self.assertEqual(soil_percent(4, 713), 0.0)

    def test_invalid_raw_excluded(self):
        for raw in (None, 0, 1024, 5000, -3):
            self.assertIsNone(soil_percent(1, raw), raw)
        self.assertIsNotNone(soil_percent(1, 1023))

    @override_settings(SOIL_CALIBRATION={1: (600, 300), 2: (578, 326), 3: (577, 329), 4: (576, 325)})
    def test_calibration_from_settings(self):
        self.assertEqual(soil_percent(1, 450), 50.0)


class ParseTests(TestCase):
    def test_naive_time_is_seoul(self):
        dt = parse_time("2026-10-12T08:15:00")
        self.assertEqual(dt, datetime(2026, 10, 11, 23, 15, tzinfo=ZoneInfo("UTC")))

    def test_clean_row_numbers(self):
        values = clean_row({"time": "2026-10-12T08:15:00", "soil1": "575", "soil2": 567.0, "light": "64", "temp": "29.1", "n_samples": "1"})
        self.assertEqual((values["soil1"], values["soil2"], values["light"], values["temp"]), (575, 567, 64.0, 29.1))
        self.assertIsNone(values["soil3"])

    def test_clean_row_errors(self):
        for bad in (
            {"time": ""},
            {"time": "어제"},
            {"time": "2026-10-12T08:15:00", "soil1": "abc"},
            {"time": "2026-10-12T08:15:00", "soil1": 1.5},
            {"time": "2026-10-12T08:15:00", "temp": True},
            {"time": "2026-10-12T08:15:00", "light": float("nan")},
            {"time": "2026-10-12T08:15:00", "n_samples": -1},
            ["2026-10-12T08:15:00"],
        ):
            with self.assertRaises(RowError, msg=bad):
                clean_row(bad)


class SaveRowsTests(DeviceTestCase):
    def test_upsert_same_time_overwrites(self):
        first = self.save([row("2026-10-12T09:00:00", soil=(590, 578, 577, 576))])
        self.assertEqual((first.created, first.updated), (1, 0))
        again = self.save([row("2026-10-12T09:00:00", soil=(269, 252, 248, 216), temp=25.5)])
        self.assertEqual((again.created, again.updated), (0, 1))

        self.assertEqual(DeviceReading.objects.count(), 1)
        reading = DeviceReading.objects.get()
        self.assertEqual((reading.soil1, reading.temp), (269, 25.5))
        # 화분 값도 한 화분에 한 행, 새 값으로
        self.assertEqual(SensorReading.objects.count(), 4)
        self.assertEqual(set(SensorReading.objects.values_list("moisture", flat=True)), {100.0})
        self.assertEqual(SensorReading.objects.get(plant=self.plants["A"]).temp, 25.5)

    def test_duplicate_time_in_same_batch_keeps_last(self):
        result = self.save([row("2026-10-12T09:00:00", temp=20), row("2026-10-12T09:00:00", temp=21)])
        self.assertEqual((result.created, result.duplicates), (1, 1))
        self.assertEqual(DeviceReading.objects.get().temp, 21)

    def test_no_data_row_kept_but_not_judged(self):
        result = self.save([row("2026-10-12T09:00:00"), no_data("2026-10-12T09:01:00")])
        self.assertEqual((result.created, result.no_data), (2, 1))
        empty = DeviceReading.objects.get(note="no_data")
        self.assertIsNone(empty.soil1)
        self.assertEqual(empty.n_samples, 0)
        # 화분 값은 유효한 행에서만
        self.assertEqual(SensorReading.objects.filter(plant=self.plants["A"]).count(), 1)
        self.assertEqual(SensorReading.objects.filter(device_reading=empty).count(), 0)
        # 기기 last_seen은 값이 빈 행까지
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_seen, parse_time("2026-10-12T09:01:00"))

    def test_latest_valid_value_drives_status(self):
        now = timezone.now()
        dry = (590, 578, 577, 576)  # 0%
        self.save([row(local_str(now - timedelta(minutes=3)), soil=dry), no_data(local_str(now - timedelta(minutes=1)))])
        status = plant_status(self.plants["A"], now)
        self.assertEqual(status.state, THIRSTY)
        self.assertEqual(status.moisture, 0.0)

    def test_invalid_channel_raw_skips_only_that_plant(self):
        # sample_data 10-12 08:08 soil2=0
        self.save([row("2026-10-12T09:08:01", soil=(575, 0, 569, 568))])
        self.assertFalse(SensorReading.objects.filter(plant=self.plants["B"]).exists())
        self.assertEqual(SensorReading.objects.filter(plant__in=[self.plants[s] for s in "ACD"]).count(), 3)
        self.assertEqual(DeviceReading.objects.get().soil2, 0)  # 원시값은 그대로 남는다

    def test_bad_rows_reported_rest_saved(self):
        result = self.save([row("2026-10-12T09:00:00"), {"time": "nope"}, row("2026-10-12T09:01:00", temp="hot")])
        self.assertEqual(result.created, 1)
        self.assertEqual([where for where, _ in result.errors], [1, 2])

    def test_since_skips_earlier_rows(self):
        result = self.save(
            [row("2026-10-12T08:14:59"), row("2026-10-12T08:15:00")], since=parse_time("2026-10-12T08:15:00")
        )
        self.assertEqual((result.created, result.before_since), (1, 1))

    def test_unlinked_channel_and_out_of_range_values(self):
        DeviceChannel.objects.filter(channel=4).update(plant=None)
        self.save([row("2026-10-12T09:00:00", temp=99, hum=1)])
        self.assertFalse(SensorReading.objects.filter(plant=self.plants["D"]).exists())
        sr = SensorReading.objects.get(plant=self.plants["A"])
        self.assertIsNone(sr.temp)  # 범위 밖 → 비움
        self.assertEqual(sr.humidity, 1)

    def test_no_alerts_created(self):
        self.save([row(local_str(timezone.now()), soil=(590, 578, 577, 576))])
        self.assertEqual(AlertLog.objects.count(), 0)


class LightTests(DeviceTestCase):
    def test_light_unverified_by_default(self):
        self.assertIsNone(light_klux(900, parse_time("2026-10-12T12:00:00"), None))
        self.save([row("2026-10-12T12:00:00", light=900)])
        self.assertIsNone(SensorReading.objects.get(plant=self.plants["A"]).light)

    @override_settings(LIGHT_LUX_SINCE="2026-10-20T00:00:00")
    def test_lux_after_since(self):
        self.save([row("2026-10-19T12:00:00", light=900), row("2026-10-20T12:00:00", light=9500)])
        values = list(SensorReading.objects.filter(plant=self.plants["A"]).order_by("measured_at").values_list("light", flat=True))
        self.assertEqual(values, [None, 9.5])

    def test_water_only_judgment_when_light_unverified(self):
        s = evaluate(self.tomato, 20, None)
        self.assertEqual((s.state, s.water_low, s.light_low, s.light_judged, s.hp), (THIRSTY, True, False, False, 3))
        s = evaluate(self.tomato, 50, None)
        self.assertEqual((s.state, s.hp), (OK, 5))
        self.assertEqual(evaluate(self.tomato, None, None).state, "nodata")

    def test_status_with_unverified_light(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(minutes=2)), light=5)])  # CdS 값이 작아도 '어두움'으로 보지 않는다
        status = plant_status(self.plants["A"], now)
        self.assertEqual(status.state, OK)
        self.assertFalse(status.light_judged)

    def test_no_light_alert_when_unverified(self):
        day = "2026-10-12"
        self.save([row(f"{day}T{h:02d}:00:00", light=5) for h in range(9, 18)] + [row(f"{day}T18:05:00", light=5)])
        reading = SensorReading.objects.filter(plant=self.plants["A"]).order_by("-measured_at").first()
        self.assertIsNone(check_light(self.plants["A"], reading))
        self.assertFalse(AlertLog.objects.filter(kind="light").exists())

    @override_settings(LIGHT_LUX_SINCE="2026-10-01T00:00:00")
    def test_dark_when_lux_verified(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(minutes=2)), light=2000)])  # 2klux < 토마토 8klux
        status = plant_status(self.plants["A"], now)
        self.assertEqual(status.state, DARK)
        self.assertTrue(status.light_judged)

    def test_graph_api_skips_empty_light(self):
        self.save([row(local_str(timezone.now() - timedelta(minutes=5)))])
        self.client.force_login(self.owner)
        # range=today는 자정 직후(5분 전 값이 어제)에 비므로 7d로 본다
        res = self.client.get("/api/graph/?metric=light&range=7d")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["times"], [])
        res = self.client.get("/api/graph/?metric=moisture&range=7d")
        self.assertEqual(len(res.json()["times"]), 1)


class StaleTests(DeviceTestCase):
    def test_device_plant_offline_after_one_hour(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(minutes=50)))])
        self.assertNotEqual(plant_status(self.plants["A"], now).state, OFFLINE)
        later = now + timedelta(minutes=11)
        status = plant_status(self.plants["A"], later)
        self.assertEqual(status.state, OFFLINE)
        self.assertEqual(status.message, "1시간 넘게 센서 값이 오지 않았어요")

    def test_no_data_rows_do_not_keep_plant_online(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(minutes=90))), no_data(local_str(now - timedelta(minutes=1)))])
        self.assertEqual(plant_status(self.plants["A"], now).state, OFFLINE)

    def test_sensor_alert_uses_device_threshold(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(minutes=61)))])
        alert = check_sensor(self.plants["A"], now)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.kind, "sensor")

    def test_manual_plant_keeps_24_hours(self):
        manual = Plant.objects.create(owner=self.owner, slot="E", crop=self.tomato)
        now = timezone.now()
        SensorReading.objects.create(plant=manual, measured_at=now - timedelta(hours=5), moisture=50, light=10, temp=22, humidity=55)
        self.assertEqual(plant_status(manual, now).state, OK)
        self.assertIsNone(check_sensor(manual, now))
        status = plant_status(manual, now + timedelta(hours=20))
        self.assertEqual((status.state, status.message), (OFFLINE, "하루 넘게 센서 값이 오지 않았어요"))

    @override_settings(DEVICE_STALE_AFTER_HOURS=3)
    def test_threshold_from_settings(self):
        now = timezone.now()
        self.save([row(local_str(now - timedelta(hours=2)))])
        self.assertNotEqual(plant_status(self.plants["A"], now).state, OFFLINE)


class RebuildTests(DeviceTestCase):
    def test_rebuild_after_calibration_change(self):
        self.save([row("2026-10-12T09:00:00", soil=(450, 450, 450, 450))])
        before = SensorReading.objects.get(plant=self.plants["A"]).moisture
        with override_settings(SOIL_CALIBRATION={1: (600, 300), 2: (578, 326), 3: (577, 329), 4: (576, 325)}):
            made = rebuild_device(self.device)
        self.assertEqual(made, 4)
        after = SensorReading.objects.get(plant=self.plants["A"]).moisture
        self.assertNotEqual(before, after)
        self.assertEqual(after, 50.0)

    def test_rebuild_after_channel_remap(self):
        self.save([row("2026-10-12T09:00:00", soil=(590, 252, 577, 576))])  # soil2만 100%
        a, b = self.plants["A"], self.plants["B"]
        DeviceChannel.objects.filter(channel=2).update(plant=None)
        DeviceChannel.objects.filter(channel=1).update(plant=b)
        DeviceChannel.objects.filter(channel=2).update(plant=a)
        rebuild_device(self.device)
        self.assertEqual(SensorReading.objects.get(plant=a).moisture, 100.0)
        self.assertEqual(SensorReading.objects.get(plant=b).moisture, 0.0)

    def test_rebuild_command(self):
        self.save([row("2026-10-12T09:00:00")])
        out = StringIO()
        call_command("rebuild_device_readings", "--device", "pi-01", stdout=out)
        self.assertIn("4행 → 4행", out.getvalue())
        self.assertEqual(SensorReading.objects.count(), 4)


class ImportCsvTests(DeviceTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="fire_csv_"))
        lines = [
            "2026-10-12T08:08:01,575,0,569,568,735,26.7,54.0,1,",
            "2026-10-12T08:15:00,576,567,570,563,64,29.1,48.0,1,",
            "2026-10-12T08:16:00,265,567,570,713,147,28.7,49.0,1,",
            "2026-10-12T08:17:00,,,,,,,,0,no_data",
        ]
        (self.tmp / "sensors_2026-10-12.csv").write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
        (self.tmp / "sensors_2026-10-13.csv").write_text(
            HEADER + "2026-10-13T02:34:00,,,,,,,,0,no_data\n2026-10-13T02:35:00,500,500,500,500,900,24.0,50.0,1,\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_import(self, *extra):
        out = StringIO()
        call_command("import_sensor_csv", str(self.tmp), "--device", "pi-01", *extra, stdout=out)
        return out.getvalue()

    def snapshot(self):
        return (
            list(DeviceReading.objects.order_by("time").values_list("time", "soil1", "soil2", "soil4", "light", "note")),
            list(SensorReading.objects.order_by("plant__slot", "measured_at").values_list("plant__slot", "measured_at", "moisture")),
        )

    def test_import_twice_same_result(self):
        out = self.run_import()
        self.assertIn("저장 6 (새로 6, 덮어씀 0), 그중 값 없음(no_data) 2", out)
        self.assertIn("기간 2026-10-12 08:08:01 ~ 2026-10-13 02:35:00", out)
        first = self.snapshot()
        out = self.run_import()
        self.assertIn("저장 6 (새로 0, 덮어씀 6)", out)
        self.assertEqual(self.snapshot(), first)
        self.assertEqual(AlertLog.objects.count(), 0)
        # 1023 넘는 값·0은 판정 제외, 100 넘는 계산값은 100, 0 아래는 0
        self.assertFalse(SensorReading.objects.filter(plant=self.plants["B"], measured_at=parse_time("2026-10-12T08:08:01")).exists())
        self.assertEqual(SensorReading.objects.get(plant=self.plants["A"], measured_at=parse_time("2026-10-12T08:16:00")).moisture, 100.0)
        self.assertEqual(SensorReading.objects.get(plant=self.plants["D"], measured_at=parse_time("2026-10-12T08:16:00")).moisture, 0.0)

    def test_dry_run_saves_nothing(self):
        out = self.run_import("--dry-run")
        self.assertIn("[dry-run]", out)
        self.assertIn("읽은 행 6", out)
        self.assertEqual(DeviceReading.objects.count(), 0)
        self.assertEqual(SensorReading.objects.count(), 0)
        self.device.refresh_from_db()
        self.assertIsNone(self.device.last_seen)

    def test_since_option(self):
        out = self.run_import("--since", "2026-10-12T08:15:00")
        self.assertIn("since 이전 1", out)
        self.assertEqual(DeviceReading.objects.count(), 5)
        self.assertFalse(DeviceReading.objects.filter(time__lt=parse_time("2026-10-12T08:15:00")).exists())

    def test_unknown_device(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("import_sensor_csv", str(self.tmp), "--device", "pi-99", stdout=StringIO())


class SetupDeviceTests(TestCase):
    fixtures = ["crops"]

    def test_existing_owner_gets_four_pots(self):
        User.objects.create_user("8jo", password="plant-pass-77")
        out = StringIO()
        call_command("setup_device", "pi-01", "--owner", "8jo", stdout=out)
        device = SensorDevice.objects.get(device_id="pi-01")
        links = list(device.channels.order_by("channel").values_list("channel", "plant__slot", "plant__condition", "plant__crop__slug"))
        self.assertEqual(
            links,
            [(1, "A", "정상", "tomato"), (2, "B", "물 줄임", "tomato"), (3, "C", "빛 줄임", "tomato"), (4, "D", "물+빛 줄임", "tomato")],
        )
        profile = Profile.objects.get(user__username="8jo")
        self.assertEqual((profile.onboarding_step, profile.crop.slug), (Profile.STEP_DONE, "tomato"))
        # 다시 실행해도 그대로
        call_command("setup_device", "pi-01", "--owner", "8jo", stdout=StringIO())
        self.assertEqual(Plant.objects.filter(owner__username="8jo").count(), 4)
        self.assertEqual(DeviceChannel.objects.count(), 4)

    def test_new_owner_password_from_terminal(self):
        with mock.patch("plants.management.commands.setup_device.getpass", side_effect=["plant-pass-77", "plant-pass-77"]):
            call_command("setup_device", "pi-01", "--owner", "8jo", stdout=StringIO())
        user = User.objects.get(username="8jo")
        self.assertTrue(user.check_password("plant-pass-77"))
        self.assertEqual(user.plants.count(), 4)

    def test_device_of_other_owner_refused(self):
        from django.core.management.base import CommandError

        other = User.objects.create_user("다른사람", password="plant-pass-77")
        SensorDevice.objects.create(device_id="pi-01", owner=other)
        User.objects.create_user("8jo", password="plant-pass-77")
        with self.assertRaises(CommandError):
            call_command("setup_device", "pi-01", "--owner", "8jo", stdout=StringIO())
        self.assertFalse(Plant.objects.filter(owner__username="8jo").exists())


class DeviceAdminTests(DeviceTestCase):
    def setUp(self):
        super().setUp()
        self.device.set_key("secret-device-key")
        self.admin = User.objects.create_superuser("관리자", password="plant-pass-77")
        self.client.force_login(self.admin)

    def test_device_page_hides_key_and_shows_channels(self):
        res = self.client.get(f"/admin/plants/sensordevice/{self.device.pk}/change/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "secret-device-key")
        self.assertContains(res, "발급됨(secret…)")
        self.assertContains(res, "soil4")

    def test_changing_channel_rebuilds(self):
        self.save([row("2026-10-12T09:00:00", soil=(269, 578, 577, 576))])  # soil1만 100%
        channels = list(self.device.channels.order_by("channel"))
        # soil1 ↔ soil2 화분을 한 번에 맞바꾼다
        swap = {1: self.plants["B"], 2: self.plants["A"], 3: self.plants["C"], 4: self.plants["D"]}
        self.post_channels(channels, swap)
        self.assertEqual(SensorReading.objects.get(plant=self.plants["B"]).moisture, 100.0)
        self.assertEqual(SensorReading.objects.get(plant=self.plants["A"]).moisture, 0.0)

    def test_same_plant_on_two_channels_refused(self):
        channels = list(self.device.channels.order_by("channel"))
        same = {1: self.plants["A"], 2: self.plants["A"], 3: self.plants["C"], 4: self.plants["D"]}
        res = self.post_channels(channels, same, expect_ok=False)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "함께 연결돼 있어요")
        self.assertEqual(DeviceChannel.objects.get(channel=2).plant, self.plants["B"])

    def post_channels(self, channels, mapping, expect_ok=True):
        data = {
            "device_id": "pi-01",
            "owner": self.owner.pk,
            "channels-TOTAL_FORMS": "4",
            "channels-INITIAL_FORMS": "4",
            "channels-MIN_NUM_FORMS": "0",
            "channels-MAX_NUM_FORMS": "4",
        }
        swap = mapping
        for i, ch in enumerate(channels):
            data.update(
                {
                    f"channels-{i}-id": ch.pk,
                    f"channels-{i}-device": self.device.pk,
                    f"channels-{i}-channel": ch.channel,
                    f"channels-{i}-plant": swap[ch.channel].pk,
                }
            )
        res = self.client.post(f"/admin/plants/sensordevice/{self.device.pk}/change/", data)
        if expect_ok and res.status_code != 302:
            formset = res.context["inline_admin_formsets"][0].formset
            self.fail((formset.errors, formset.non_form_errors()))
        return res

    def test_raw_readings_read_only(self):
        self.save([row("2026-10-12T09:00:00")])
        self.assertEqual(self.client.get("/admin/plants/devicereading/").status_code, 200)
        self.assertEqual(self.client.get("/admin/plants/devicereading/add/").status_code, 403)

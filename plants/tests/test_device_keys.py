"""기기 키(DB 해시) — 발급·재발급·검증, .env 키 이어받기, setup_device 출력, 키 원문이 DB·로그에 남지 않음."""

import json
import logging
import re
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Profile
from plants.models import Crop, DeviceChannel, DeviceReading, Plant, SensorDevice, hash_device_key

User = get_user_model()


def body(device_id="pi-01", time="2026-10-21T14:30:00"):
    row = {"time": time, "soil1": 450, "soil2": 450, "soil3": 450, "soil4": 450, "light": 900, "temp": 24.0, "hum": 50.0, "n_samples": 1, "note": ""}
    return json.dumps({"device_id": device_id, "readings": [row]})


class CaptureAllLogs(logging.Handler):
    """테스트 동안 모든 로거의 기록을 모은다."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))

    def __enter__(self):
        root = logging.getLogger()
        self.old_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self)
        return self

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self.old_level)

    @property
    def text(self):
        return "\n".join(self.lines)


def db_dump():
    """테스트 DB(SQLite) 전체를 SQL 글로. 세션 표 포함."""
    connection.ensure_connection()
    return "\n".join(connection.connection.iterdump())


class KeyTestCase(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.owner = User.objects.create_user("8jo", password="plant-pass-77")
        tomato = Crop.objects.get(slug="tomato")
        Profile.objects.create(user=self.owner, crop=tomato, onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        self.device = SensorDevice.objects.create(device_id="pi-01", name="pi-01", owner=self.owner)
        plant = Plant.objects.create(owner=self.owner, slot="A", name="토토", crop=tomato)
        DeviceChannel.objects.create(device=self.device, channel=1, plant=plant)

    def send(self, key, device_id="pi-01", time="2026-10-21T14:30:00"):
        return self.client.post("/api/readings", data=body(device_id, time), content_type="application/json", HTTP_X_API_KEY=key)


class DeviceKeyModelTests(KeyTestCase):
    def test_issue_stores_hash_and_prefix_only(self):
        raw = self.device.issue_key()
        self.device.refresh_from_db()
        self.assertGreaterEqual(len(raw), 40)
        self.assertEqual(self.device.key_hash, hash_device_key(raw))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", self.device.key_hash))
        self.assertEqual(self.device.key_prefix, raw[:6])
        self.assertIsNotNone(self.device.key_issued_at)
        self.assertEqual(SensorDevice.for_key(raw), self.device)
        self.assertIsNone(SensorDevice.for_key(raw + "x"))
        self.assertIsNone(SensorDevice.for_key(""))

    def test_devices_without_key_are_null_and_many_allowed(self):
        for i in range(3):
            SensorDevice.objects.create(device_id=f"dev-000{i}", owner=self.owner)
        self.assertEqual(SensorDevice.objects.filter(key_hash__isnull=True).count(), 4)
        self.assertFalse(SensorDevice.objects.filter(key_hash="").exists())

    def test_same_key_hash_twice_refused(self):
        self.device.set_key("same-key-value")
        other = SensorDevice.objects.create(device_id="pi-02", owner=self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            other.set_key("same-key-value")


class DeviceKeyApiTests(KeyTestCase):
    def test_issued_key_receives(self):
        raw = self.device.issue_key()
        res = self.send(raw)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["saved"], 1)

    def test_reissue_rejects_old_key(self):
        old = self.device.issue_key()
        self.assertEqual(self.send(old).status_code, 200)
        new = self.device.issue_key()
        self.assertEqual(self.send(old, time="2026-10-21T14:31:00").status_code, 401)
        self.assertEqual(self.send(new, time="2026-10-21T14:32:00").status_code, 200)
        self.assertEqual(DeviceReading.objects.count(), 2)

    def test_other_device_key_403(self):
        other_owner = User.objects.create_user("다른사람", password="plant-pass-77")
        other = SensorDevice.objects.create(device_id="pi-77", owner=other_owner)
        other_key = other.issue_key()
        self.device.issue_key()
        self.assertEqual(self.send(other_key, device_id="pi-01").status_code, 403)
        self.assertEqual(DeviceReading.objects.filter(device=self.device).count(), 0)

    def test_archived_device_key_401(self):
        from plants.devices import archive_device

        raw = self.device.issue_key()
        archive_device(self.device)
        self.assertEqual(self.send(raw).status_code, 401)

    def test_raw_key_not_in_db_queries_or_logs(self):
        with CaptureAllLogs() as logs, CaptureQueriesContext(connection) as queries:
            raw = self.device.issue_key()
            self.assertEqual(self.send(raw).status_code, 200)
            self.assertEqual(self.send(raw, device_id="pi-99").status_code, 403)
            self.assertEqual(self.send(raw + "-wrong").status_code, 401)
        self.assertNotIn(raw, logs.text)
        self.assertTrue(any("readings" in line for line in logs.lines))  # 401·403 경고는 남는다(키 없이)
        self.assertFalse(any(raw in q["sql"] for q in queries.captured_queries))
        self.assertNotIn(raw, db_dump())
        self.assertIn(hash_device_key(raw), db_dump())


OLD_KEY = "old-env-key-for-test"  # .env에 있던 예전 키 자리


@override_settings(SENSOR_DEVICE_KEYS={"pi-01": OLD_KEY, "pi-02": ""})
class AdoptEnvKeysTests(KeyTestCase):
    def run_adopt(self, *args):
        out = StringIO()
        call_command("adopt_env_device_keys", *args, stdout=out)
        return out.getvalue()

    def test_adopt_twice_is_safe(self):
        out1 = self.run_adopt()
        self.device.refresh_from_db()
        first = (self.device.key_hash, self.device.key_prefix, self.device.key_issued_at)
        out2 = self.run_adopt()
        self.device.refresh_from_db()
        self.assertEqual((self.device.key_hash, self.device.key_prefix, self.device.key_issued_at), first)
        self.assertIn("옮겼어요(old-en…)", out1)
        self.assertIn("이미 옮겼어요", out2)
        self.assertIn("pi-02: .env에 키가 없어요", out1)
        for out in (out1, out2):
            self.assertNotIn(OLD_KEY, out)
        self.assertEqual(self.device.key_prefix, "old-en")

    def test_old_key_keeps_working_without_env(self):
        self.run_adopt()
        with override_settings(SENSOR_DEVICE_KEYS={}):
            self.assertEqual(self.send(OLD_KEY).status_code, 200)

    def test_reissued_key_not_overwritten_unless_force(self):
        self.run_adopt()
        new = self.device.issue_key()
        out = self.run_adopt()
        self.assertIn("다른 키", out)
        self.assertEqual(self.send(new).status_code, 200)
        self.assertEqual(self.send(OLD_KEY, time="2026-10-21T14:31:00").status_code, 401)
        self.run_adopt("--force")
        self.assertEqual(self.send(OLD_KEY, time="2026-10-21T14:32:00").status_code, 200)

    def test_dry_run_changes_nothing(self):
        out = self.run_adopt("--dry-run")
        self.device.refresh_from_db()
        self.assertIsNone(self.device.key_hash)
        self.assertIn("옮길 예정", out)

    def test_missing_device_skipped(self):
        with override_settings(SENSOR_DEVICE_KEYS={"pi-55": "some-key"}):
            out = self.run_adopt()
        self.assertIn("등록된 기기가 없어요", out)


class SetupDeviceKeyTests(TestCase):
    fixtures = ["crops"]

    def run_setup(self, *args):
        out = StringIO()
        call_command("setup_device", "pi-01", "--owner", "8jo", *args, stdout=out)
        return out.getvalue()

    def test_key_printed_once(self):
        User.objects.create_user("8jo", password="plant-pass-77")
        out = self.run_setup()
        match = re.search(r"기기 키\(지금 한 번만 보여 드려요\): (\S+)", out)
        self.assertIsNotNone(match)
        raw = match.group(1)
        device = SensorDevice.objects.get(device_id="pi-01")
        self.assertEqual(device.key_hash, hash_device_key(raw))
        self.assertEqual(device.name, "pi-01")
        out2 = self.run_setup()
        self.assertNotIn(raw, out2)
        self.assertIn(f"기기 키는 이미 있어요({raw[:6]}…)", out2)
        out3 = self.run_setup("--reissue-key")
        raw3 = re.search(r"기기 키\(지금 한 번만 보여 드려요\): (\S+)", out3).group(1)
        self.assertNotEqual(raw3, raw)
        self.assertIsNone(SensorDevice.for_key(raw))
        self.assertEqual(SensorDevice.for_key(raw3), device)

    def test_archived_device_refused(self):
        from django.core.management.base import CommandError

        owner = User.objects.create_user("8jo", password="plant-pass-77")
        SensorDevice.objects.create(device_id="pi-01", owner=owner, archived_at=timezone.now())
        with self.assertRaises(CommandError):
            self.run_setup()

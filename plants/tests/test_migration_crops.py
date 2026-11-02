"""작물 목록 7종 마이그레이션(plants 0008) 검증. 임시 SQLite 파일에서만 실행한다(db.sqlite3는 건드리지 않음)."""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BEFORE_0008 = [
    ("plants", "0007_crop_is_active"),
    ("accounts", "0003_personal"),
    ("diary", "0002_owner"),
    ("alerts", "0002_alert_resolved_at"),
]

MIGRATE_TO = """
import django, sys, json
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
MigrationExecutor(connection).migrate([tuple(t) for t in json.loads(sys.argv[1])])
"""

OLD_CROPS = [
    # id, slug, name, water, light, order (예전 5종)
    (1, "tomato", "토마토", 30, 8, 1),
    (2, "lettuce", "상추", 35, 5, 2),
    (3, "basil", "바질", 30, 8, 3),
    (4, "pepper", "고추", 30, 8, 4),
    (5, "green-onion", "대파", 20, 4, 5),
]


class CropsV2MigrationTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fire_crops_"))
        self.db = self.tmp / "old.sqlite3"
        self.env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "plants.tests.migration_settings",
            "MIGRATION_TEST_DB": str(self.db),
            "PYTHONIOENCODING": "utf-8",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_py(self, *args):
        result = subprocess.run(
            [sys.executable, *args], cwd=settings.BASE_DIR, env=self.env, capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode != 0:
            self.fail(f"명령 실패: {args}\n{result.stdout}\n{result.stderr}")

    def query(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_existing_db_gets_seven_crops(self):
        import json

        self.run_py("-c", MIGRATE_TO, json.dumps(BEFORE_0008))
        con = sqlite3.connect(self.db)
        for pk, slug, name, water, light, order in OLD_CROPS:
            con.execute(
                'INSERT INTO plants_crop (id, name, slug, difficulty, water, sun, water_threshold, moisture_min, moisture_max,'
                ' light_threshold, temp_min, temp_max, humidity_min, humidity_max, color, "order", is_active)'
                " VALUES (?, ?, ?, '보통', '보통', '보통', ?, 40, 65, ?, 18, 28, 40, 70, '#000000', ?, 1)",
                (pk, name, slug, water, light, order),
            )
        con.execute(
            "INSERT INTO auth_user (id, password, last_login, is_superuser, username, last_name, email, is_staff, is_active, date_joined, first_name)"
            " VALUES (1, '!', '2026-10-01 00:00:00', 0, 'u1', '', '', 0, 1, '2026-10-01 00:00:00', '')"
        )
        con.execute(
            "INSERT INTO plants_plant (id, slot, name, condition, api_key, is_demo, created_at, crop_id, owner_id)"
            " VALUES (10, 'A', '고추장', '', 'key-a', 0, '2026-10-01 00:00:00', 4, 1)"
        )
        con.execute(
            "INSERT INTO plants_sensorreading (id, measured_at, moisture, light, temp, humidity, plant_id)"
            " VALUES (1, '2026-10-02 00:00:00', 20, 9, 22, 55, 10)"
        )
        con.commit()
        con.close()

        self.run_py("manage.py", "migrate", "--noinput")

        active = self.query('SELECT slug, name FROM plants_crop WHERE is_active=1 ORDER BY "order"')
        self.assertEqual(
            active,
            [("strawberry", "딸기"), ("tomato", "토마토"), ("basil", "바질"), ("kidney-bean", "강낭콩"),
             ("sunflower", "해바라기"), ("lettuce", "상추"), ("balsam", "봉선화")],
        )
        self.assertEqual(
            self.query('SELECT slug FROM plants_crop WHERE is_active=0 ORDER BY "order"'), [("pepper",), ("green-onion",)]
        )
        # 새 작물은 fixture와 같은 pk(6~9)
        self.assertEqual(
            self.query("SELECT id, slug FROM plants_crop WHERE id >= 6 ORDER BY id"),
            [(6, "strawberry"), (7, "kidney-bean"), (8, "sunflower"), (9, "balsam")],
        )
        # 기존 작물 기준값은 그대로
        self.assertEqual(
            self.query("SELECT slug, water_threshold, light_threshold FROM plants_crop WHERE id <= 5 ORDER BY id"),
            [(slug, float(w), float(lt)) for _, slug, _, w, lt, _ in OLD_CROPS],
        )
        # 고추 화분과 센서값은 그대로
        self.assertEqual(self.query("SELECT id, name, crop_id FROM plants_plant"), [(10, "고추장", 4)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM plants_sensorreading")[0][0], 1)

    def test_empty_db_left_for_fixture(self):
        self.run_py("manage.py", "migrate", "--noinput")
        self.assertEqual(self.query("SELECT COUNT(*) FROM plants_crop")[0][0], 0)

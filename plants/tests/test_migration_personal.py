"""모임 제거 마이그레이션 검증.

임시 SQLite 파일을 따로 만들어 예전(모임) 구조까지만 마이그레이션하고, 그 구조로 데이터를 넣은 뒤
끝까지 마이그레이션해서 데이터가 그대로 남는지 본다. 개발 DB(db.sqlite3)는 건드리지 않는다.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

OLD_STATE = [
    ("accounts", "0002_remove_profile_character"),
    ("plants", "0002_remove_plant_character"),
    ("diary", "0001_initial"),
    ("alerts", "0002_alert_resolved_at"),
]

MIGRATE_TO_OLD = f"""
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
MigrationExecutor(connection).migrate({OLD_STATE!r})
"""


class GroupRemovalMigrationTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fire_mig_"))
        self.db = self.tmp / "old.sqlite3"
        self.env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "plants.tests.migration_settings",
            "MIGRATION_TEST_DB": str(self.db),
            "PYTHONIOENCODING": "utf-8",
        }
        self.run_py("-c", MIGRATE_TO_OLD)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_py(self, *args, check=True):
        result = subprocess.run(
            [sys.executable, *args], cwd=settings.BASE_DIR, env=self.env, capture_output=True, text=True, encoding="utf-8"
        )
        if check and result.returncode != 0:
            self.fail(f"명령 실패: {args}\n{result.stdout}\n{result.stderr}")
        return result

    def migrate_all(self, check=True):
        return self.run_py("manage.py", "migrate", "--noinput", check=check)

    def sql(self, statements):
        con = sqlite3.connect(self.db)
        con.executescript(statements)
        con.commit()
        con.close()

    def query(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def insert_old_data(self):
        """예전 구조: 모임 1(회원 u1, u2) / 모임 2(회원 u3)."""
        self.sql(
            """
            INSERT INTO auth_user (id, password, last_login, is_superuser, username, last_name, email, is_staff, is_active, date_joined, first_name)
            VALUES (1, '!', '2026-10-01 00:00:00', 0, 'u1', '', '', 0, 1, '2026-10-01 00:00:00', ''),
                   (2, '!', '2026-10-01 00:00:00', 0, 'u2', '', '', 0, 1, '2026-10-01 00:00:00', ''),
                   (3, '!', '2026-10-01 00:00:00', 0, 'u3', '', '', 0, 1, '2026-10-01 00:00:00', '');
            INSERT INTO plants_crop (id, name, slug, difficulty, water, sun, water_threshold, moisture_min, moisture_max,
                                     light_threshold, temp_min, temp_max, humidity_min, humidity_max, color, "order")
            VALUES (1, '토마토', 'tomato', '보통', '보통', '많이', 30, 40, 70, 8, 18, 28, 40, 70, '#e5533d', 1);
            INSERT INTO plants_group (id, name, invite_code, condition_changed_at, is_demo, created_at)
            VALUES (10, '실험반', 'AAAAAA', '2026-10-04 00:00:00', 0, '2026-10-01 00:00:00'),
                   (20, '혼자반', 'BBBBBB', NULL, 0, '2026-10-01 00:00:00');
            INSERT INTO accounts_profile (id, onboarding_step, creates_first_plant, crop_id, group_id, user_id)
            VALUES (1, 4, 0, 1, 10, 1), (2, 4, 0, 1, 10, 2), (3, 4, 0, 1, 20, 3);
            INSERT INTO plants_plant (id, slot, name, condition, api_key, is_demo, created_at, crop_id, group_id)
            VALUES (100, 'A', '토토', '정상 관리', 'key-a', 0, '2026-10-01 00:00:00', 1, 10),
                   (101, 'B', '토순', '물 줄임', 'key-b', 0, '2026-10-01 00:00:00', 1, 10),
                   (200, 'A', '민주', '', 'key-c', 0, '2026-10-01 00:00:00', 1, 20);
            INSERT INTO plants_sensorreading (id, measured_at, moisture, light, temp, humidity, plant_id)
            VALUES (1, '2026-10-02 00:00:00', 50, 10, 22, 55, 100),
                   (2, '2026-10-02 01:00:00', 25, 3, 21, 60, 101),
                   (3, '2026-10-02 02:00:00', 40, 9, 23, 50, 200);
            INSERT INTO plants_plantphoto (id, image, taken_at, diagnosis, recommendation, plant_id)
            VALUES (1, 'photos/10/A/x.jpg', '2026-10-02 09:00:00', '잎이 건강해요', '', 100);
            INSERT INTO diary_diaryentry (id, content, is_auto, created_at, author_id, group_id, plant_id)
            VALUES (1, 'u2가 쓴 일기', 0, '2026-10-02 10:00:00', 2, 10, 101),
                   (2, '자동 기록', 1, '2026-10-02 11:00:00', NULL, 10, 100),
                   (3, 'u3 일기', 0, '2026-10-02 12:00:00', 3, 20, NULL);
            INSERT INTO plants_todocheck (id, date, key, checked_at, checked_by_id, group_id)
            VALUES (1, '2026-10-02', 'water:B', '2026-10-02 10:00:00', 2, 10);
            INSERT INTO alerts_alertlog (id, kind, message, channel, sent_at, is_demo, plant_id, resolved_at)
            VALUES (1, 'water', '토양수분이 30% 아래로 내려갔어요(지금 25%). 물을 주세요.', 'telegram', '2026-10-02 01:00:00', 0, 101, NULL);
            """
        )

    def test_data_kept_and_owned(self):
        self.insert_old_data()
        # 뒤 마이그레이션에서 칸이 늘어날 수 있어(센서값 device_reading 등) 예전 칸만 비교한다
        columns = {
            "plants_sensorreading": "id, measured_at, moisture, light, temp, humidity, plant_id",
            "plants_plantphoto": "*",
            "alerts_alertlog": "*",
        }
        before = {t: self.query(f"SELECT {c} FROM {t} ORDER BY id") for t, c in columns.items()}
        self.migrate_all()

        # 센서값·사진·알림 행은 내용까지 그대로
        for table, rows in before.items():
            self.assertEqual(self.query(f"SELECT {columns[table]} FROM {table} ORDER BY id"), rows, table)

        # 화분: 모임의 첫 회원(Profile id가 가장 작은 u1)이 주인, 이름·키·작물 그대로
        self.assertEqual(
            self.query("SELECT id, slot, name, api_key, crop_id, owner_id FROM plants_plant ORDER BY id"),
            [(100, "A", "토토", "key-a", 1, 1), (101, "B", "토순", "key-b", 1, 1), (200, "A", "민주", "key-c", 1, 3)],
        )
        # 다이어리: 내용 그대로, 주인은 모임의 첫 회원, author 칸은 없어짐
        self.assertEqual(
            self.query("SELECT id, content, is_auto, plant_id, owner_id FROM diary_diaryentry ORDER BY id"),
            [(1, "u2가 쓴 일기", 0, 101, 1), (2, "자동 기록", 1, 100, 1), (3, "u3 일기", 0, None, 3)],
        )
        diary_cols = [r[1] for r in self.query("PRAGMA table_info(diary_diaryentry)")]
        self.assertNotIn("author_id", diary_cols)
        self.assertNotIn("group_id", diary_cols)
        # 할 일 체크: 주인으로, checked_by 칸은 없어짐
        self.assertEqual(self.query("SELECT key, owner_id FROM plants_todocheck"), [("water:B", 1)])
        self.assertNotIn("checked_by_id", [r[1] for r in self.query("PRAGMA table_info(plants_todocheck)")])
        # 조건 변경 시각은 프로필로
        self.assertEqual(
            self.query("SELECT user_id, condition_changed_at FROM accounts_profile ORDER BY user_id"),
            [(1, "2026-10-04 00:00:00"), (2, "2026-10-04 00:00:00"), (3, None)],
        )
        profile_cols = [r[1] for r in self.query("PRAGMA table_info(accounts_profile)")]
        self.assertNotIn("group_id", profile_cols)
        self.assertNotIn("creates_first_plant", profile_cols)
        # 모임 표는 없어짐
        self.assertEqual(self.query("SELECT name FROM sqlite_master WHERE name='plants_group'"), [])

    def test_orphan_group_stops_without_changes(self):
        self.insert_old_data()
        self.sql(
            """
            INSERT INTO plants_group (id, name, invite_code, condition_changed_at, is_demo, created_at)
            VALUES (30, '빈 모임', 'CCCCCC', NULL, 0, '2026-10-01 00:00:00');
            INSERT INTO plants_plant (id, slot, name, condition, api_key, is_demo, created_at, crop_id, group_id)
            VALUES (300, 'A', '외톨이', '', 'key-d', 0, '2026-10-01 00:00:00', 1, 30);
            """
        )
        result = self.migrate_all(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("회원이 없는 모임", result.stdout + result.stderr)
        # 아무것도 지워지지 않았고, 모임 칸도 그대로
        self.assertEqual(self.query("SELECT COUNT(*) FROM plants_plant")[0][0], 4)
        self.assertEqual(self.query("SELECT group_id FROM plants_plant WHERE id=300"), [(30,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM plants_group")[0][0], 3)
        self.assertEqual(self.query("SELECT COUNT(*) FROM diary_diaryentry")[0][0], 3)

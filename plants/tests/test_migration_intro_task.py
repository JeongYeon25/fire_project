"""accounts 0004(사용 안내 본 시각)·plants 0009(할 일) 마이그레이션 검증. 임시 SQLite 파일에서만 실행한다."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BEFORE = [
    ("accounts", "0003_personal"),
    ("plants", "0008_crops_v2"),
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


class IntroTaskMigrationTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fire_intro_"))
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

    def test_existing_profiles_marked_seen(self):
        self.run_py("-c", MIGRATE_TO, json.dumps(BEFORE))
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO auth_user (id, password, last_login, is_superuser, username, last_name, email, is_staff, is_active, date_joined, first_name)"
            " VALUES (1, '!', '2026-10-01 00:00:00', 0, 'u1', '', '', 0, 1, '2026-10-01 00:00:00', '')"
        )
        con.execute("INSERT INTO accounts_profile (id, onboarding_step, crop_id, user_id, condition_changed_at) VALUES (1, 4, NULL, 1, NULL)")
        con.commit()
        con.close()

        self.run_py("manage.py", "migrate", "--noinput")

        con = sqlite3.connect(self.db)
        try:
            seen = con.execute("SELECT intro_seen_at FROM accounts_profile WHERE id=1").fetchone()[0]
            task_cols = [r[1] for r in con.execute("PRAGMA table_info(plants_task)")]
        finally:
            con.close()
        self.assertIsNotNone(seen)  # 기존 계정에는 안내가 뜨지 않는다
        for col in ("owner_id", "plant_id", "title", "due_date", "due_time", "notify", "done_at", "notified_at"):
            self.assertIn(col, task_cols)

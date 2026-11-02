"""마이그레이션 테스트 전용 설정: 임시 SQLite 파일(MIGRATION_TEST_DB)에만 연결한다."""

import os

from config.settings import *  # noqa: F401,F403
from config.settings import DATABASES

DATABASES["default"]["NAME"] = os.environ["MIGRATION_TEST_DB"]

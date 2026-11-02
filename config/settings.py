"""
Django settings for config project.

시크릿과 환경별 값은 프로젝트 루트의 .env에서 읽는다 (.env.example 참고).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = (os.environ.get(name) or "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        raise RuntimeError(f".env의 {name}는 숫자여야 해요.") from None


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(".env에 DJANGO_SECRET_KEY를 설정하세요. (.env.example 참고)")

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

# https 임시 링크(cloudflared)나 LAN 주소로 웹 화면의 로그인·저장 폼을 쓰려면 필요하다. 예: https://*.trycloudflare.com
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "plants",
    "diary",
    "alerts",
    "advisor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.profile",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:onboarding"
LOGIN_REDIRECT_URL = "plants:home"
LOGOUT_REDIRECT_URL = "accounts:onboarding"


LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# 하드웨어 센서 기기 (plants/devices.py)
# 기기 키는 DB(SensorDevice.key_hash)에 해시로만 둔다. 수신 API는 DB만 본다.
# 아래는 예전 .env 키를 DB로 옮기는 `python manage.py adopt_env_device_keys` 전용(옮긴 뒤에는 .env에서 지워도 된다).
SENSOR_DEVICE_KEYS = {"pi-01": os.environ.get("SENSOR_KEY_PI01", "").strip()}
# 한 사용자가 쓸 수 있는 기기 수(보관한 기기는 세지 않는다)
DEVICE_LIMIT_PER_USER = 5

# 내 기기 화면에 보여 줄 전송 주소의 앞부분. 비어 있으면 접속한 주소로 만든다. 예: https://abc.trycloudflare.com
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
# cloudflared 같은 https 프록시 뒤에서 X-Forwarded-Proto를 믿을지(기본 꺼짐). 켜면 전송 주소가 https로 나온다.
if env_bool("DJANGO_TRUST_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 토양수분 채널별 보정값 (공기 중 원시값, 물속 원시값). 수분 % = (공기 - 원시) / (공기 - 물) × 100, 0~100으로 자름.
# ※ 하드웨어 담당자 확인 전의 임시값. 규격(docs/hardware/api_spec_261021.txt 6번) 예시 "(590 - raw) / 321"의
#   321을 분모(공기 - 물속)로 보고 물속 원시값을 590 - 321 = 269 등으로 계산했다(교정 이후 실제 최저 원시값 284/218/256/224).
#   납땜 후 다시 재면 바꾸고 `python manage.py rebuild_device_readings --device pi-01`을 실행한다.
SOIL_CALIBRATION = {
    1: (590, 269),  # 분모 321
    2: (578, 252),  # 분모 326
    3: (577, 248),  # 분모 329
    4: (576, 251),  # 분모 325
}
# 이 범위를 벗어난 원시값(0, 1023 초과)은 센서 오류로 보고 판정에 쓰지 않는다.
SOIL_RAW_VALID = (1, 1023)

# 조도가 lux 단위로 바뀐 시각(서울, "YYYY-MM-DDTHH:MM:SS"). 그 전 값은 CdS 상대값이라 빛 판정에 쓰지 않는다.
# 비워 두면 모든 조도 값을 아직 확인 전으로 보고 빛 판정을 하지 않는다.
LIGHT_LUX_SINCE = os.environ.get("LIGHT_LUX_SINCE", "").strip() or None

# 센서를 만지며 교정한 구간. 이 시각(서울) 이전 행은 원시값만 저장하고 화분 측정값은 만들지 않는다.
SENSOR_IGNORE_BEFORE = os.environ.get("SENSOR_IGNORE_BEFORE", "").strip() or "2026-10-12T08:15:00"

# 기기 수신 API(POST /api/readings, 본문에 device_id·readings) 한 번에 받을 최대 줄 수
DEVICE_MAX_ROWS = 200

# '센서 연결 끊김' 기준: 마지막 유효 측정값이 이보다 오래되면 판정하지 않고 센서 점검 알림을 만든다.
SENSOR_STALE_AFTER_HOURS = 24  # 화분별 키로 직접 보내는 화분
DEVICE_STALE_AFTER_HOURS = 1  # 기기 채널에 연결된 화분 (1분 간격)


# 식물 상담(AI에게 물어보기, advisor 앱). 회사·키·모델이 모두 있어야 켜진다(없으면 "AI 상담은 준비 중이에요").
# 키와 모델명은 코드에 쓰지 않는다. 지금 지원하는 회사: openai
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip().lower()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()
LLM_TIMEOUT_SECONDS = env_int("LLM_TIMEOUT_SECONDS", 20)
# 출력 한도(추론 토큰 포함). 추론 모델은 생각하는 데도 이 한도를 쓰므로 답변 길이보다 넉넉히 둔다.
LLM_MAX_OUTPUT_TOKENS = env_int("LLM_MAX_OUTPUT_TOKENS", 1000)
# 추론 강도(지원하는 모델만). 비우면 보내지 않는다.
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low").strip().lower()
# 하루(서울 날짜) 질문 한도. 0이면 제한 없음. 켜져 있으면 답을 받지 못한 질문도 센다.
CHAT_DAILY_LIMIT = env_int("CHAT_DAILY_LIMIT", 0)  # 사용자당
CHAT_GLOBAL_DAILY_LIMIT = env_int("CHAT_GLOBAL_DAILY_LIMIT", 0)  # 서비스 전체
CHAT_QUESTION_MAX = 200  # 질문 글자 수
CHAT_HISTORY_SHOWN = 10  # 화면에 보여 줄 최근 대화 수
CHAT_HISTORY_PAIRS = 2  # 이어지는 질문을 위해 함께 보내는 직전 대화(질문+답) 쌍

# 테스트 중에는 실제 LLM·네트워크 호출을 막는다(.env에 키가 있어도). config/test_runner.py
TEST_RUNNER = "config.test_runner.NoNetworkTestRunner"

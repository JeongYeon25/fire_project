"""화분 상태 판정.

물 부족 = 최신 토양수분 < 작물의 물주기 기준
빛 부족 = 최근 24시간 최고 조도 < 작물의 조도 기준
  (조도 값이 없으면 — 기기 조도를 아직 확인하기 전 — 물만 판정하고 빛은 판정하지 않는다)
판정 기준값은 Crop(fixture)에 있고, 수업 실험 후 보정 필요.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

OK, THIRSTY, DARK, SICK = "ok", "thirsty", "dark", "sick"
# 판정할 수 없는 상태: 한 번도 측정값이 없음(nodata) / 연결된 적은 있지만 24시간 넘게 값이 없음(offline)
NODATA, OFFLINE = "nodata", "offline"
WAITING = (NODATA, OFFLINE)
STATES = [OK, THIRSTY, DARK, SICK]

LABELS = {
    OK: "건강해요",
    THIRSTY: "목이 말라요",
    DARK: "빛이 부족해요",
    SICK: "많이 아파요",
    NODATA: "센서 연결 전",
    OFFLINE: "센서 연결 끊김",
}

MESSAGES = {
    OK: "잘 크고 있어요!",
    THIRSTY: "목말라요… 물 주세요",
    DARK: "너무 어두워요… 햇빛 보고 싶어요",
    SICK: "물도 빛도 부족해서 아파요…",
    NODATA: "아직 센서가 연결되지 않았어요",
    OFFLINE: "하루 넘게 센서 값이 오지 않았어요",
}

TIPS = {
    OK: ["지금처럼 흙 위쪽이 말랐을 때 물을 주세요"],
    THIRSTY: [
        "흙 위쪽 2cm를 손가락으로 눌러보세요. 말라 있으면 물을 주세요",
        "한 번에 150mL 정도, 화분 아래로 조금 흘러나올 때까지 천천히 주세요",
    ],
    DARK: [
        "창가처럼 밝은 곳으로 옮겨 주세요",
        "줄기가 가늘고 길게 자라면 빛이 부족하다는 신호예요",
    ],
    SICK: [
        "먼저 물을 주세요. 많이 말랐다면 나눠서 천천히요",
        "그다음 밝은 곳으로 옮겨 주세요",
    ],
    NODATA: ["화분 센서에 이 화분의 API 키를 넣고 전원을 켜 주세요"],
    OFFLINE: ["센서 전원과 와이파이 연결을 확인해 주세요", "센서를 다시 켰는데도 안 되면 API 키를 새로 받아 넣어 주세요"],
}

# 창 제목줄 색 이름(CSS modifier)과 캐릭터 액자 소프트 색 이름
TITLE_COLORS = {OK: "green", THIRSTY: "orange", DARK: "purple", SICK: "pink", NODATA: "teal", OFFLINE: "blue"}
SOFT_COLORS = {OK: "green", THIRSTY: "yellow", DARK: "lavender", SICK: "pink", NODATA: "sky", OFFLINE: "sky"}

MAX_HP = 5
LIGHT_WINDOW = timedelta(hours=24)


def stale_after(plant):
    """'센서 연결 끊김' 기준. 기기 채널에 연결된 화분(1분 간격)은 짧게, 직접 보내는 화분은 24시간."""
    from .models import DeviceChannel

    if DeviceChannel.objects.filter(plant=plant).exists():
        return timedelta(hours=settings.DEVICE_STALE_AFTER_HOURS)
    return timedelta(hours=settings.SENSOR_STALE_AFTER_HOURS)


@dataclass
class PlantStatus:
    state: str
    moisture: float | None = None
    max_light_24h: float | None = None
    water_low: bool = False
    light_low: bool = False
    hp: int | None = None
    tips: list = field(default_factory=list)
    # 조도 값이 없어서 빛을 판정하지 않았으면 False
    light_judged: bool = True
    # 기본 한마디 대신 쓸 문구(연결 끊김 기준이 24시간이 아닌 기기 화분)
    message_override: str = ""

    @property
    def label(self):
        return LABELS[self.state]

    @property
    def message(self):
        return self.message_override or MESSAGES[self.state]

    @property
    def title_color(self):
        return TITLE_COLORS[self.state]

    @property
    def soft_color(self):
        return SOFT_COLORS[self.state]

    @property
    def character_state(self):
        """그림 상태. 판정할 수 없으면(연결 전·끊김) 건강한 그림을 흐리게 쓴다."""
        return OK if self.state in WAITING else self.state

    @property
    def has_problem(self):
        return self.state in (THIRSTY, DARK, SICK)

    @property
    def is_waiting(self):
        """센서 연결 전이거나 끊겨서 상태를 판정할 수 없음."""
        return self.state in WAITING


def evaluate(crop, moisture, max_light_24h):
    """측정값으로 상태를 판정한다. 토양수분이 없으면 nodata(연결 끊김은 plant_status가 구분).
    조도만 없으면(기기 조도 확인 전) 물만 판정한다."""
    if moisture is None:
        return PlantStatus(state=NODATA, moisture=moisture, max_light_24h=max_light_24h, tips=list(TIPS[NODATA]))

    water_low = moisture < crop.water_threshold
    light_judged = max_light_24h is not None
    light_low = light_judged and max_light_24h < crop.light_threshold
    if water_low and light_low:
        state = SICK
    elif water_low:
        state = THIRSTY
    elif light_low:
        state = DARK
    else:
        state = OK
    hp = MAX_HP - (2 if water_low else 0) - (2 if light_low else 0)
    return PlantStatus(
        state=state,
        moisture=moisture,
        max_light_24h=max_light_24h,
        water_low=water_low,
        light_low=light_low,
        hp=hp,
        tips=list(TIPS[state]),
        light_judged=light_judged,
    )


def plant_status(plant, now=None):
    """DB의 측정값으로 화분 상태를 판정한다."""
    now = now or timezone.now()
    readings = plant.readings.filter(measured_at__lte=now)
    latest = readings.order_by("-measured_at").first()
    if latest is None:
        return evaluate(plant.crop, None, None)  # 한 번도 연결된 적 없음
    limit = stale_after(plant)
    if latest.measured_at <= now - limit:
        # 연결된 적은 있지만 기준 시간 넘게 값이 없음 → 판정하지 않는다(센서 점검 알림과 같은 기준).
        hours = int(limit.total_seconds() // 3600)
        override = "" if hours == 24 else f"{hours}시간 넘게 센서 값이 오지 않았어요"
        return PlantStatus(state=OFFLINE, moisture=latest.moisture, tips=list(TIPS[OFFLINE]), message_override=override)
    max_light = readings.filter(measured_at__gt=now - LIGHT_WINDOW).aggregate(m=Max("light"))["m"]
    return evaluate(plant.crop, latest.moisture, max_light)


def latest_reading(plant, now=None):
    now = now or timezone.now()
    return plant.readings.filter(measured_at__lte=now).order_by("-measured_at").first()

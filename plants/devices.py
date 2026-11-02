"""하드웨어 센서 기기 값 저장과 화분 측정값 계산.

기기 한 행 = 시각 + 토양수분 원시값 4채널(soil1~4) + 조도 원시값 + 온도 + 습도.
- 원시값은 DeviceReading에 그대로 저장한다(같은 기기·같은 시각이면 덮어씀). 값이 빈 행(no_data)도 남긴다.
- 채널에 화분이 연결돼 있으면 계산한 값을 그 화분의 SensorReading으로 넣는다. 판정·그래프·알림은 SensorReading만 읽는다.
  - 토양수분 % = (공기 - 원시) / (공기 - 물) × 100, 0~100으로 자름 (settings.SOIL_CALIBRATION)
  - 원시값이 비었거나 0, 1023 초과면 그 화분 값은 만들지 않는다(판정에서 빠짐).
  - 조도는 settings.LIGHT_LUX_SINCE 이후 값만 lux → klux로 넣고, 그 전 값(CdS 상대값)은 비워 둔다(빛 판정 안 함).
  - 칸 단위로 처리한다: dht_fail(온도·습도 null)이어도 토양수분이 있으면 물 판정에 쓴다.
  - n_samples=0(그 1분에 데이터를 못 받음, no_data)이거나 settings.SENSOR_IGNORE_BEFORE(교정 구간) 이전이면 화분 값을 만들지 않는다.
- 보정값·채널 연결·LIGHT_LUX_SINCE를 바꾸면 rebuild_device()로 화분 값을 다시 만든다(알림은 만들지 않음).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DeviceChannel, DeviceReading, SensorReading

SOIL_FIELDS = ("soil1", "soil2", "soil3", "soil4")
INT_FIELDS = SOIL_FIELDS + ("n_samples",)
FLOAT_FIELDS = ("light", "temp", "hum")
VALUE_FIELDS = SOIL_FIELDS + FLOAT_FIELDS
SAVE_FIELDS = INT_FIELDS + FLOAT_FIELDS + ("note",)
NOTE_MAX = 40

# 화분 값으로 넣을 때 허용 범위. 벗어나면 그 항목만 비운다(원시값은 그대로 남음).
TEMP_LIMITS = (-30, 70)
HUMIDITY_LIMITS = (0, 100)
LIGHT_KLUX_LIMITS = (0, 200)

CHUNK = 500  # SQLite 변수 개수 제한 안쪽으로 나눠 처리


class RowError(ValueError):
    pass


def local_tz():
    return ZoneInfo(settings.TIME_ZONE)


def parse_time(value):
    """'YYYY-MM-DDTHH:MM:SS'. 시간대가 없으면 서울 시각으로 본다."""
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str) or not value.strip():
            raise RowError("time이 비어 있어요.")
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            raise RowError(f"time 형식이 아니에요: {value}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt


def _setting_time(name):
    value = getattr(settings, name, None)
    return parse_time(value) if value else None


def lux_since():
    """조도가 lux로 바뀐 시각. 설정이 비어 있으면 None(모든 조도 값 확인 전)."""
    return _setting_time("LIGHT_LUX_SINCE")


def ignore_before():
    """교정 구간 끝. 이 시각 이전 행은 화분 값을 만들지 않는다."""
    return _setting_time("SENSOR_IGNORE_BEFORE")


@dataclass(frozen=True)
class Rules:
    """화분 값 계산 규칙(설정에서 한 번 읽어 둔다)."""

    lux_since: datetime | None
    ignore_before: datetime | None

    @classmethod
    def from_settings(cls):
        return cls(lux_since=lux_since(), ignore_before=ignore_before())


def _blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _number(name, value, integer):
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise RowError(f"{name}은(는) 숫자여야 해요.")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise RowError(f"{name}은(는) 숫자여야 해요.") from None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RowError(f"{name}은(는) 숫자여야 해요.")
    if integer:
        if float(value) != int(value):
            raise RowError(f"{name}은(는) 정수여야 해요.")
        return int(value)
    return float(value)


def clean_row(raw):
    """기기 한 행(dict)을 저장할 값으로 바꾼다. 잘못된 행이면 RowError."""
    if not isinstance(raw, dict):
        raise RowError("행은 JSON 객체여야 해요.")
    values = {"time": parse_time(raw.get("time"))}
    for name in INT_FIELDS:
        values[name] = _number(name, raw.get(name), integer=True)
    for name in FLOAT_FIELDS:
        values[name] = _number(name, raw.get(name), integer=False)
    if values["n_samples"] is not None and values["n_samples"] < 0:
        raise RowError("n_samples는 0 이상이어야 해요.")
    note = raw.get("note")
    values["note"] = "" if _blank(note) else str(note).strip()[:NOTE_MAX]
    return values


def is_empty(values):
    """측정값이 하나도 없는 행(no_data)."""
    return all(values.get(name) is None for name in VALUE_FIELDS)


def soil_percent(channel, raw):
    """원시값 → 토양수분 %(0~100). 판정에 쓸 수 없는 값이면 None."""
    lo, hi = settings.SOIL_RAW_VALID
    if raw is None or not lo <= raw <= hi:
        return None
    air, water = settings.SOIL_CALIBRATION[channel]
    percent = (air - raw) / (air - water) * 100
    return round(max(0.0, min(100.0, percent)), 1)


def light_klux(raw, at, since):
    """조도 원시값 → klux. lux로 바뀌기 전(또는 설정 전)이면 None."""
    if raw is None or since is None or at < since:
        return None
    klux = raw / 1000
    lo, hi = LIGHT_KLUX_LIMITS
    return klux if lo <= klux <= hi else None


def _in(value, limits):
    lo, hi = limits
    return value if value is not None and lo <= value <= hi else None


def plant_readings_for(reading, channels, rules):
    """원시값 한 행 → 연결된 화분들의 SensorReading(저장 전) 목록."""
    if reading.n_samples == 0:
        return []  # 그 1분에 데이터를 못 받음 — 값이 있어도 쓰지 않는다
    if rules.ignore_before is not None and reading.time < rules.ignore_before:
        return []  # 교정 구간
    result = []
    for ch in channels:
        moisture = soil_percent(ch.channel, reading.soil(ch.channel))
        if moisture is None:
            continue
        result.append(
            SensorReading(
                plant_id=ch.plant_id,
                measured_at=reading.time,
                moisture=moisture,
                light=light_klux(reading.light, reading.time, rules.lux_since),
                temp=_in(reading.temp, TEMP_LIMITS),
                humidity=_in(reading.hum, HUMIDITY_LIMITS),
                device_reading=reading,
            )
        )
    return result


def linked_channels(device):
    return list(DeviceChannel.objects.filter(device=device, plant__isnull=False))


def _derive(device_readings, channels, rules):
    ids = [r.id for r in device_readings]
    SensorReading.objects.filter(device_reading_id__in=ids).delete()
    rows = [sr for r in device_readings for sr in plant_readings_for(r, channels, rules)]
    SensorReading.objects.bulk_create(rows, batch_size=CHUNK)
    return rows


@dataclass
class SaveResult:
    received: int = 0
    created: int = 0
    updated: int = 0
    no_data: int = 0
    before_since: int = 0
    duplicates: int = 0  # 같은 요청·파일 안에서 시각이 겹친 행(뒤의 행을 저장)
    errors: list = field(default_factory=list)  # (위치, 이유)
    duplicate_rows: list = field(default_factory=list)  # (덮어쓰인 앞 행 위치, 이유)
    first: datetime | None = None
    last: datetime | None = None
    plant_rows: int = 0
    # 화분별 가장 최신 계산값(알림 처리용) {plant_id: SensorReading}
    latest: dict = field(default_factory=dict)

    @property
    def saved(self):
        return self.created + self.updated

    def merge(self, other):
        for name in ("received", "created", "updated", "no_data", "before_since", "duplicates", "plant_rows"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.errors += other.errors
        self.duplicate_rows += other.duplicate_rows
        self.first = min(filter(None, [self.first, other.first]), default=None)
        self.last = max(filter(None, [self.last, other.last]), default=None)
        for plant_id, sr in other.latest.items():
            if plant_id not in self.latest or sr.measured_at > self.latest[plant_id].measured_at:
                self.latest[plant_id] = sr


@transaction.atomic
def save_rows(device, rows, since=None):
    """기기 행들을 저장(UPSERT)하고 화분 값을 만든다. 알림은 만들지 않는다.

    rows: [(위치 표시, dict), ...]. 잘못된 행은 errors에 남기고 나머지는 저장한다.
    since: 이 시각 이전 행은 건너뛴다(교정 구간 제외용).
    """
    result = SaveResult()
    cleaned = {}
    positions = {}
    for where, raw in rows:
        result.received += 1
        try:
            values = clean_row(raw)
        except RowError as exc:
            result.errors.append((where, str(exc)))
            continue
        if since is not None and values["time"] < since:
            result.before_since += 1
            continue
        if values["time"] in cleaned:
            result.duplicates += 1
            result.duplicate_rows.append((positions[values["time"]], "같은 시각의 행이 뒤에 또 있어서 뒤의 행을 저장했어요."))
        cleaned[values["time"]] = values
        positions[values["time"]] = where

    channels = linked_channels(device)
    rules = Rules.from_settings()
    times = sorted(cleaned)
    for start in range(0, len(times), CHUNK):
        chunk = times[start : start + CHUNK]
        existing = set(DeviceReading.objects.filter(device=device, time__in=chunk).values_list("time", flat=True))
        result.updated += len(existing)
        result.created += len(chunk) - len(existing)
        DeviceReading.objects.bulk_create(
            [DeviceReading(device=device, **cleaned[t]) for t in chunk],
            update_conflicts=True,
            unique_fields=["device", "time"],
            update_fields=list(SAVE_FIELDS) + ["received_at"],
        )
        saved = list(DeviceReading.objects.filter(device=device, time__in=chunk))
        made = _derive(saved, channels, rules)
        result.plant_rows += len(made)
        for sr in made:
            current = result.latest.get(sr.plant_id)
            if current is None or sr.measured_at > current.measured_at:
                result.latest[sr.plant_id] = sr

    result.no_data = sum(1 for t in times if is_empty(cleaned[t]))
    if times:
        result.first, result.last = times[0], times[-1]
        # 값이 빈 행도 기기가 살아 있다는 뜻이라 last_seen에 넣는다.
        if device.last_seen is None or times[-1] > device.last_seen:
            device.last_seen = times[-1]
            device.save(update_fields=["last_seen"])
    return result


def run_alerts(result, now=None):
    """요청 하나에서 화분마다 가장 최신 유효 값으로만 알림을 판정한다. 새로 만든 AlertLog 목록.

    그 값이 기기 연결 끊김 기준(1시간)보다 오래됐거나, DB에 그 화분의 더 새 값이 있으면(밀린 줄 재전송) 판정하지 않는다.
    """
    from alerts.services import process_reading

    now = now or timezone.now()
    oldest = now - timedelta(hours=settings.DEVICE_STALE_AFTER_HOURS)
    created = []
    for plant_id, made in result.latest.items():
        if made.measured_at < oldest:
            continue
        newest = (
            SensorReading.objects.filter(plant_id=plant_id, measured_at__lte=now)
            .select_related("plant__crop", "plant__owner")
            .order_by("-measured_at")
            .first()
        )
        if newest is None or newest.measured_at != made.measured_at:
            continue
        created += process_reading(newest)
    return created


class ArchivedDeviceError(Exception):
    """보관한 기기는 채널이 해제돼 있어서 다시 계산하면 남겨 둔 화분 값이 지워진다."""


@transaction.atomic
def archive_device(device):
    """기기 보관: 키 무효화 + 채널 해제 + 목록에서 숨김. 원시값과 이미 계산한 화분 값은 그대로 둔다(다시 계산하지 않음).
    device_id는 행이 남아 있어 다시 쓸 수 없다. 완전 삭제는 관리자 화면에서만."""
    device.key_hash = None
    device.key_prefix = ""
    device.archived_at = timezone.now()
    device.save(update_fields=["key_hash", "key_prefix", "archived_at"])
    return DeviceChannel.objects.filter(device=device).delete()[0]


@transaction.atomic
def rebuild_device(device):
    """이 기기에서 계산한 화분 값을 모두 지우고 원시값으로 다시 만든다. 만든 행 수를 돌려준다."""
    if device.archived_at is not None:
        raise ArchivedDeviceError(f"{device.device_id}는 보관한 기기라 화분 값을 다시 계산하지 않아요.")
    SensorReading.objects.filter(device_reading__device=device).delete()
    channels = linked_channels(device)
    if not channels:
        return 0
    rules = Rules.from_settings()
    total = 0
    batch = []
    for reading in DeviceReading.objects.filter(device=device).order_by("time").iterator(chunk_size=CHUNK):
        batch.extend(plant_readings_for(reading, channels, rules))
        if len(batch) >= CHUNK:
            SensorReading.objects.bulk_create(batch)
            total += len(batch)
            batch = []
    SensorReading.objects.bulk_create(batch)
    return total + len(batch)

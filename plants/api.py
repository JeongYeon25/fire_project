import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.http import JsonResponse as _JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import app_view
from alerts.services import check_owner_sensors, process_reading

from .devices import lux_since, run_alerts, save_rows
from .metrics import METRICS, display_value
from .models import Plant, SensorDevice, SensorReading, TodoCheck
from .services import plant_status

def JsonResponse(data, status=200):
    """한글 메시지가 curl·PowerShell에서 그대로 읽히도록 UTF-8로 보낸다."""
    return _JsonResponse(
        data, status=status, json_dumps_params={"ensure_ascii": False}, content_type="application/json; charset=utf-8"
    )


RANGES = {
    "today": 10 * 60,  # 버킷 크기(초)
    "7d": 60 * 60,
    "all": 60 * 60,
}

# 센서 값 허용 범위 (센서 고장으로 튀는 값을 막는다)
READING_LIMITS = {
    "moisture": (0, 100),
    "light": (0, 200),
    "temp": (-30, 70),
    "humidity": (0, 100),
}


def _range_start(range_key, now):
    if range_key == "today":
        local = timezone.localtime(now)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "7d":
        return now - timedelta(days=7)
    return None


@app_view
@require_GET
def graph_data(request):
    metric = request.GET.get("metric", "moisture")
    if metric not in METRICS:
        return JsonResponse({"error": "metric은 moisture, light, temp, humidity 중 하나예요."}, status=400)
    range_key = request.GET.get("range", "7d")
    if range_key not in RANGES:
        range_key = "7d"
    plants = list(Plant.objects.filter(owner=request.user).select_related("crop"))
    wanted = [s for s in request.GET.get("plants", "").split(",") if s]
    if wanted:
        plants = [p for p in plants if p.slot in wanted]

    now = timezone.now()
    start = _range_start(range_key, now)

    def in_range(at):
        return timezone.localtime(at).isoformat() if at and (start is None or at >= start) else None

    changed_iso = in_range(request.profile.condition_changed_at)
    # 조도 센서 교체(CdS → BH1750) 시각: 조도 그래프에만 세로선
    light_changed_iso = in_range(lux_since()) if metric == "light" else None

    qs = SensorReading.objects.filter(plant__in=plants, measured_at__lte=now)
    if not light_changed_iso:
        # 값이 빈 시간(기기 조도 확인 전 등)은 가로축에서 뺀다. 센서 교체 세로선이 있으면
        # 교체 전(값 없음) 구간도 가로축에 남겨서 선 앞은 비고 뒤부터 그려지게 한다.
        qs = qs.filter(**{f"{metric}__isnull": False})
    if start is not None:
        qs = qs.filter(measured_at__gte=start)

    step = RANGES[range_key]
    factor = METRICS[metric]["factor"]  # 조도는 화면에 lux로
    buckets = defaultdict(lambda: defaultdict(list))
    for plant_id, measured_at, value in qs.values_list("plant_id", "measured_at", metric).iterator():
        bucket = buckets[int(measured_at.timestamp()) // step * step]
        if value is not None:
            bucket[plant_id].append(value)
    keys = sorted(buckets)

    series = []
    for plant in plants:
        values = []
        for key in keys:
            vals = buckets[key].get(plant.id)
            values.append(round(sum(vals) / len(vals) * factor, 2) if vals else None)
        series.append({"slot": plant.slot, "label": plant.title, "color": plant.color, "values": values})

    thresholds = []
    if metric in ("moisture", "light"):
        seen = set()
        for plant in plants:
            crop = plant.crop
            value = crop.water_threshold if metric == "moisture" else crop.light_threshold
            if (crop.id, value) in seen:
                continue
            seen.add((crop.id, value))
            name = "물주기 기준" if metric == "moisture" else "조도 기준"
            shown = display_value(metric, value)
            thresholds.append({"value": shown, "label": f"{crop.name} {name} {shown:,g}{METRICS[metric]['unit']}"})

    meta = METRICS[metric]
    return JsonResponse(
        {
            "metric": metric,
            "label": meta["label"],
            "unit": meta["unit"],
            "digits": meta["digits"],
            "range": range_key,
            "times": [timezone.localtime(datetime.fromtimestamp(k, tz=dt_timezone.utc)).isoformat() for k in keys],
            "series": series,
            "thresholds": thresholds,
            "condition_changed_at": changed_iso,
            "light_unit_changed_at": light_changed_iso,
        }
    )


def _parse_json(request):
    """본문 JSON. 깨졌으면 None과 이유."""
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "JSON 형식이 아니에요."


def _device_for_key(api_key):
    """기기 키와 맞는 기기(DB의 키 해시로 찾는다). 없으면 None."""
    return SensorDevice.for_key(api_key)


@csrf_exempt
@require_POST
def receive_reading(request):
    """센서 수신: POST /api/readings (슬래시 있어도 됨), 헤더 X-API-Key.

    - 본문에 device_id나 readings가 있으면 하드웨어 기기(라즈베리파이) 여러 줄 → receive_device_rows
    - 아니면 화분별 키 + 값 하나 {moisture, light, temp, humidity} (기존 방식)
    """
    api_key = request.headers.get("X-API-Key", "").strip()
    if not api_key:
        return JsonResponse({"error": "X-API-Key가 없거나 맞지 않아요."}, status=401)
    data, json_error = _parse_json(request)
    key_device = _device_for_key(api_key)
    if isinstance(data, dict) and ("device_id" in data or "readings" in data):
        return receive_device_rows(data, key_device)
    if json_error and key_device:
        return JsonResponse({"error": json_error}, status=400)

    plant = Plant.objects.select_related("crop").filter(api_key=api_key).first()
    if plant is None:
        return JsonResponse({"error": "X-API-Key가 없거나 맞지 않아요."}, status=401)
    if json_error:
        return JsonResponse({"error": json_error}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "JSON 객체로 보내 주세요."}, status=400)

    values, errors = {}, {}
    for field, (lo, hi) in READING_LIMITS.items():
        raw = data.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            errors[field] = "숫자가 필요해요."
        elif not lo <= raw <= hi:
            errors[field] = f"{lo}~{hi} 사이 값이어야 해요."
        else:
            values[field] = float(raw)
    if errors:
        return JsonResponse({"error": "값을 확인해 주세요.", "fields": errors}, status=400)

    reading = SensorReading.objects.create(plant=plant, **values)
    created = process_reading(reading)
    created += check_owner_sensors(plant.owner, now=reading.measured_at, exclude=plant)
    status = plant_status(plant)
    return JsonResponse(
        {
            "id": reading.id,
            "plant": plant.slot,
            "measured_at": timezone.localtime(reading.measured_at).isoformat(),
            "state": status.state,
            "alerts": [{"plant": a.plant.slot, "kind": a.kind} for a in created],
        },
        status=201,
    )


def receive_device_rows(data, key_device):
    """기기 여러 줄 수신. 규격: docs/hardware/api_spec_261021.txt

    키가 틀리면 401, 모르는 기기·다른 기기의 키면 403, 본문 형식이 틀리면 400.
    그 밖에는 잘못된 행이 있어도 건너뛰고 나머지를 저장한 뒤 항상 200 {"saved", "skipped"}
    (Pi는 200이 아니면 그 줄부터 계속 다시 보낸다).
    """
    if key_device is None:
        return JsonResponse({"error": "X-API-Key가 없거나 맞지 않아요."}, status=401)
    device_id = data.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return JsonResponse({"error": "device_id가 필요해요."}, status=400)
    rows = data.get("readings")
    if not isinstance(rows, list):
        return JsonResponse({"error": "readings는 배열이어야 해요."}, status=400)
    if len(rows) > settings.DEVICE_MAX_ROWS:
        return JsonResponse({"error": f"readings는 한 번에 {settings.DEVICE_MAX_ROWS}줄까지 보낼 수 있어요."}, status=400)
    if key_device.device_id != device_id.strip():
        return JsonResponse({"error": "등록되지 않은 기기이거나 이 기기의 키가 아니에요."}, status=403)

    device = key_device
    result = save_rows(device, list(enumerate(rows)))
    run_alerts(result)
    skipped = sorted(result.errors + result.duplicate_rows, key=lambda item: item[0])
    return JsonResponse({"saved": result.saved, "skipped": [{"index": i, "reason": reason} for i, reason in skipped]})


@require_GET
def health(request):
    """서버 확인용. 로그인 없이, 인증·설정 정보는 넣지 않는다."""
    return JsonResponse({"status": "ok"})


@app_view
@require_POST
def todo_check(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        key = str(data["key"])[:40]
        checked = bool(data["checked"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "잘못된 요청이에요."}, status=400)
    today = timezone.localdate()
    if checked:
        TodoCheck.objects.update_or_create(
            owner=request.user, date=today, key=key
        )
    else:
        TodoCheck.objects.filter(owner=request.user, date=today, key=key).delete()
    return JsonResponse({"key": key, "checked": checked})

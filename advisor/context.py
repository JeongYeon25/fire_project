"""AI 상담에 보낼 화분 데이터 요약.

- build_context(plant, now): DB에서 그 화분의 정보만 모아 dict로 만든다. 사용자 정보(닉네임·이메일·계정 ID)는 넣지 않는다.
- summarize(points), render_context(ctx): DB 없이 동작하는 순수 함수(테스트 대상).
- 원시 행 전체가 아니라 24시간·7일 요약(개수·최소·최대·평균·마지막 값과 시각)만 보낸다.
- 판정(상태·HP·물/빛 부족)은 plants.services.plant_status 결과를 그대로 넣는다. AI는 이 판정을 바꾸지 않는다.
- 조도는 화면처럼 lux로. 기기 조도 단위를 아직 확인하기 전이면 "미검증"이라고 적고 값을 넣지 않는다.
- 사용자가 입력한 글(이름·설명·할 일 제목)은 길이를 자르고 따옴표로 감싸 데이터로만 넣는다.
"""

import json
from datetime import timedelta

from django.utils import timezone

from alerts.models import AlertLog
from plants.devices import lux_since
from plants.metrics import METRICS
from plants.models import DeviceChannel, Task
from plants.services import NODATA, OFFLINE, WAITING, plant_status, stale_after

METRIC_ORDER = ["moisture", "light", "temp", "humidity"]
USER_TEXT_MAX = 40
ALERT_DAYS = 7
ALERT_MAX = 5
TODO_MAX = 5

LIGHT_JUDGED = "판정함"
LIGHT_UNVERIFIED = "미검증(조도 센서 단위를 확인하는 중이라 빛은 판정하지 않음)"
LIGHT_NOT_JUDGED = "판정 안 함(센서 값이 없거나 끊겨서 상태를 판정하지 않음)"


def quote(text, limit=USER_TEXT_MAX):
    """사용자가 입력한 글 → 길이를 자르고 JSON 문자열로 감싼 데이터. 비었으면 None."""
    text = " ".join((text or "").split())[:limit]
    return json.dumps(text, ensure_ascii=False) if text else None


def local(dt):
    return timezone.localtime(dt).strftime("%m-%d %H:%M") if dt else None


def summarize(points, factor=1):
    """[(시각, 값), …] → {count, min, max, avg, last, last_at}. 값이 None인 점은 뺀다. 남은 점이 없으면 None."""
    values = [(at, v * factor) for at, v in points if v is not None]
    if not values:
        return None
    nums = [v for _, v in values]
    last_at, last = max(values, key=lambda p: p[0])
    return {
        "count": len(nums),
        "min": round(min(nums), 1),
        "max": round(max(nums), 1),
        "avg": round(sum(nums) / len(nums), 1),
        "last": round(last, 1),
        "last_at": last_at,
    }


def light_state(status, light_unverified):
    if status.state in WAITING:
        return LIGHT_NOT_JUDGED
    if light_unverified or not status.light_judged:
        return LIGHT_UNVERIFIED
    return LIGHT_JUDGED


def build_context(plant, now=None):
    now = now or timezone.now()
    crop = plant.crop
    status = plant_status(plant, now)
    is_device = DeviceChannel.objects.filter(plant=plant).exists()
    light_unverified = is_device and lux_since() is None
    light = light_state(status, light_unverified)

    rows = list(
        plant.readings.filter(measured_at__gt=now - timedelta(days=7), measured_at__lte=now)
        .order_by("measured_at")
        .values_list("measured_at", "moisture", "light", "temp", "humidity")
    )
    latest = plant.readings.filter(measured_at__lte=now).order_by("-measured_at").values_list("measured_at", flat=True).first()
    windows = {}
    for key, start in (("24h", now - timedelta(hours=24)), ("7d", now - timedelta(days=7))):
        part = [r for r in rows if r[0] > start]
        metrics = {}
        for i, metric in enumerate(METRIC_ORDER, start=1):
            if metric == "light" and light == LIGHT_UNVERIFIED:
                metrics[metric] = "unverified"
                continue
            metrics[metric] = summarize([(r[0], r[i]) for r in part], METRICS[metric]["factor"])
        windows[key] = {"count": len(part), "metrics": metrics}

    alerts = [
        {"kind": a.get_kind_display(), "message": a.message, "at": a.sent_at, "resolved": a.is_resolved}
        for a in AlertLog.objects.filter(plant=plant, sent_at__gt=now - timedelta(days=ALERT_DAYS), sent_at__lte=now)[:ALERT_MAX]
    ]

    todos = []
    if status.water_low:
        todos.append("물 주기 (자동: 토양수분이 물주기 기준보다 낮음)")
    if status.light_low:
        todos.append("밝은 곳으로 옮기기 (자동: 최근 24시간 최고 조도가 기준보다 낮음)")
    today = timezone.localdate(now)
    tasks = Task.objects.filter(plant=plant, done_at__isnull=True, due_date__lte=today).order_by("due_date", "due_time")[:TODO_MAX]
    for task in tasks:
        when = "오늘" if task.due_date == today else f"{task.due_date:%m-%d} (지남)"
        todos.append(f"{quote(task.title)} — {when}")

    return {
        "now": now,
        "plant": {
            "crop": crop.name,
            "name": quote(plant.name),
            "slot": plant.slot,
            "condition": quote(plant.condition),
            "day_number": plant.day_number,
            "source": "센서 기기(1분 간격)" if is_device else "화분 센서",
        },
        "crop": {
            "difficulty": crop.difficulty,
            "water": crop.water,
            "sun": crop.sun,
            "water_threshold": crop.water_threshold,
            "moisture": (crop.moisture_min, crop.moisture_max),
            "light_threshold_lux": crop.light_threshold * 1000,
            "temp": (crop.temp_min, crop.temp_max),
            "humidity": (crop.humidity_min, crop.humidity_max),
        },
        "status": {
            "state": status.state,
            "label": status.label,
            "message": status.message,
            "hp": status.hp,
            "water_low": status.water_low if status.state not in WAITING else None,
            "light_low": status.light_low if light == LIGHT_JUDGED else None,
            "light": light,
            "stale_hours": int(stale_after(plant).total_seconds() // 3600),
        },
        "last_reading_at": latest,
        "windows": windows,
        "alerts": alerts,
        "todos": todos,
    }


def _num(value, unit):
    return f"{value:,g}{unit}"


def _yes_no(value):
    return "판정 안 함" if value is None else ("예" if value else "아니요")


def render_context(ctx):
    """build_context 결과 → AI에게 보낼 글. 순수 함수."""
    p, c, s = ctx["plant"], ctx["crop"], ctx["status"]
    lines = [f"[기준 시각] {timezone.localtime(ctx['now']):%Y-%m-%d %H:%M} (서울)"]

    plant_bits = [f"작물 {p['crop']}", f"자리 {p['slot']}"]
    if p["name"]:
        plant_bits.append(f"이름 {p['name']}")
    if p["condition"]:
        plant_bits.append(f"설명(실험 조건) {p['condition']}")
    plant_bits += [f"키운 지 {p['day_number']}일째", f"측정: {p['source']}"]
    lines.append("[화분] " + " / ".join(plant_bits))

    lines.append(
        "[작물 기준] "
        f"토양수분 {_num(c['water_threshold'], '%')} 미만이면 물 부족 / "
        f"적정 토양수분 {c['moisture'][0]:g}~{c['moisture'][1]:g}% / "
        f"최근 24시간 최고 조도 {_num(c['light_threshold_lux'], ' lux')} 미만이면 빛 부족 / "
        f"적정 온도 {c['temp'][0]:g}~{c['temp'][1]:g}°C / 적정 습도 {c['humidity'][0]:g}~{c['humidity'][1]:g}% / "
        f"물 {c['water']} / 햇빛 {c['sun']} / 난이도 {c['difficulty']}"
    )

    hp = f"{s['hp']}/5" if s["hp"] is not None else "측정 전(–)"
    lines.append(
        "[현재 판정 — 서비스 규칙이 정한 값, 바꾸지 말 것] "
        f"상태 {s['label']}({s['state']}) / 한마디 \"{s['message']}\" / HP {hp} / "
        f"물 부족 {_yes_no(s['water_low'])} / 빛 부족 {_yes_no(s['light_low'])} / 빛 판정: {s['light']} / "
        f"연결 끊김 기준: 마지막 값이 {s['stale_hours']}시간보다 오래되면"
    )
    if s["state"] == NODATA:
        lines.append("[주의] 이 화분은 아직 센서 값이 한 번도 오지 않았다. 이 화분의 측정값은 없다.")
    elif s["state"] == OFFLINE:
        lines.append("[주의] 센서 값이 끊겼다. 아래 값은 끊기기 전 기록이라 지금 상태가 아닐 수 있다.")

    lines.append(f"[마지막 수신] {local(ctx['last_reading_at']) or '없음'}")
    for key, title in (("24h", "최근 24시간"), ("7d", "최근 7일")):
        window = ctx["windows"][key]
        lines.append(f"[측정값 요약 · {title}] 측정 {window['count']:,}개")
        for metric in METRIC_ORDER:
            meta = METRICS[metric]
            summary = window["metrics"][metric]
            unit = " lux" if metric == "light" else meta["unit"]
            if summary == "unverified":
                lines.append(f"- {meta['label']}: 미검증이라 값을 쓰지 않음")
            elif summary is None:
                lines.append(f"- {meta['label']}: 측정값 없음")
            else:
                lines.append(
                    f"- {meta['label']}: 마지막 {_num(summary['last'], unit)} ({local(summary['last_at'])}), "
                    f"최소 {_num(summary['min'], unit)}, 최대 {_num(summary['max'], unit)}, 평균 {_num(summary['avg'], unit)}, "
                    f"{summary['count']:,}개"
                )

    lines.append(f"[최근 {ALERT_DAYS}일 알림]" + ("" if ctx["alerts"] else " 없음"))
    for a in ctx["alerts"]:
        lines.append(f"- {local(a['at'])} {a['kind']}: {a['message']} ({'해결됨' if a['resolved'] else '아직 해결 안 됨'})")

    lines.append("[열린 할 일]" + ("" if ctx["todos"] else " 없음"))
    lines += [f"- {t}" for t in ctx["todos"]]
    return "\n".join(lines)

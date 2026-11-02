"""알림 자동 생성.

- 물 부족: 측정값을 받을 때마다 토양수분 < 작물의 물주기 기준이면
- 빛 부족: 18시 이후 첫 측정값을 받을 때, 그날 09~18시 최고 조도 < 작물의 조도 기준이면 (하루 1번 판정)
- 센서 연결 점검: 마지막 측정이 기준 시간보다 오래됐으면 (수신 API에서 같은 주인의 다른 화분 + check_sensors 명령)
  기준은 plants.services.stale_after: 직접 보내는 화분 24시간, 기기 채널에 연결된 화분 1시간(settings)
- 조도 값이 없는 날(기기 조도 확인 전)은 빛 부족을 판정하지 않는다.

같은 화분·같은 종류의 미해결 알림이 있으면 새로 만들지 않고, 정상으로 돌아오면 해결 시각을 기록한다.
화분 주인이 그 종류의 알림을 꺼 두었으면 만들지 않는다.
텔레그램 발송은 2단계에서 여기서 만든 AlertLog를 보고 주인에게 보낸다.
"""

from django.db.models import Max
from django.utils import timezone

from .models import AlertLog, UserSetting

SETTING_FIELDS = {
    "water": "notify_water",
    "light": "notify_light",
    "sensor": "notify_sensor",
    "summary": "notify_summary",
}

DAY_START_HOUR = 9
DAY_END_HOUR = 18


def water_message(threshold, moisture):
    return f"토양수분이 {threshold:g}% 아래로 내려갔어요(지금 {int(moisture)}%). 물을 주세요."


def light_message(threshold, peak):
    """기준·측정값은 klux, 문구는 lux."""
    return f"오늘 낮(09~18시) 최고 조도가 {peak * 1000:,.0f} lux로 기준({threshold * 1000:,.0f} lux)보다 낮았어요. 밝은 곳으로 옮겨 주세요."


def sensor_message(hours):
    return f"{int(hours)}시간째 측정값이 들어오지 않아요. 센서 전원과 연결을 확인해 주세요."


def owner_wants(owner_id, kind):
    """화분 주인이 이 종류의 알림을 켰으면 True. 설정을 저장한 적이 없으면 기본값(켬)."""
    field = SETTING_FIELDS[kind]
    return not UserSetting.objects.filter(user_id=owner_id, **{field: False}).exists()


def open_alert(plant, kind):
    return AlertLog.objects.filter(plant=plant, kind=kind, resolved_at__isnull=True).first()


def raise_alert(plant, kind, message, at):
    """미해결 알림이 없고 주인이 그 알림을 켜 두었을 때만 만든다. 만들었으면 AlertLog, 아니면 None."""
    if open_alert(plant, kind) is not None:
        return None
    if not owner_wants(plant.owner_id, kind):
        return None
    return AlertLog.objects.create(plant=plant, kind=kind, message=message, sent_at=at, is_demo=plant.is_demo)


def resolve(plant, kind, at):
    """미해결 알림을 해결됨으로 표시한다. 바꾼 개수를 돌려준다."""
    return AlertLog.objects.filter(plant=plant, kind=kind, resolved_at__isnull=True).update(resolved_at=at)


def check_water(plant, reading):
    threshold = plant.crop.water_threshold
    if reading.moisture < threshold:
        return raise_alert(plant, "water", water_message(threshold, reading.moisture), reading.measured_at)
    resolve(plant, "water", reading.measured_at)
    return None


def check_light(plant, reading):
    """18시 이후 그날 첫 측정값일 때만 그날 09~18시 최고 조도로 판정한다."""
    local = timezone.localtime(reading.measured_at)
    if local.hour < DAY_END_HOUR:
        return None
    day_end = local.replace(hour=DAY_END_HOUR, minute=0, second=0, microsecond=0)
    day_start = day_end.replace(hour=DAY_START_HOUR)
    already_judged = (
        plant.readings.filter(measured_at__gte=day_end, measured_at__lt=reading.measured_at).exclude(pk=reading.pk).exists()
    )
    if already_judged:
        return None
    peak = plant.readings.filter(measured_at__gte=day_start, measured_at__lt=day_end).aggregate(m=Max("light"))["m"]
    if peak is None:
        return None  # 낮 동안 측정값이 없으면 판정하지 않는다(센서 점검 알림이 따로 있다).
    threshold = plant.crop.light_threshold
    if peak < threshold:
        return raise_alert(plant, "light", light_message(threshold, peak), reading.measured_at)
    resolve(plant, "light", reading.measured_at)
    return None


def check_sensor(plant, now=None):
    """마지막 측정이 기준 시간보다 오래됐으면 알림, 아니면 해결. 측정값이 한 번도 없으면 아무것도 하지 않는다."""
    from plants.services import stale_after

    now = now or timezone.now()
    last = plant.readings.filter(measured_at__lte=now).aggregate(m=Max("measured_at"))["m"]
    if last is None:
        return None
    gap = now - last
    if gap >= stale_after(plant):  # 화면의 '센서 연결 끊김'(plants.services OFFLINE)과 같은 기준
        return raise_alert(plant, "sensor", sensor_message(gap.total_seconds() // 3600), now)
    resolve(plant, "sensor", now)
    return None


def process_reading(reading):
    """측정값을 저장한 뒤 부른다. 새로 만든 AlertLog 목록을 돌려준다."""
    plant = reading.plant
    created = [
        check_water(plant, reading),
        check_light(plant, reading),
        check_sensor(plant, reading.measured_at),
    ]
    return [a for a in created if a is not None]


def check_owner_sensors(owner, now=None, exclude=None):
    """같은 주인의 다른 화분들 센서 점검."""
    from plants.models import Plant

    plants = Plant.objects.filter(owner=owner)
    if exclude is not None:
        plants = plants.exclude(pk=exclude.pk)
    return [a for a in (check_sensor(p, now) for p in plants) if a is not None]

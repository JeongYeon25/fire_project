import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.decorators import app_view
from plants.views import my_alerts, my_plants, plant_rows, waiting_summary

from .models import CHANNELS, UserSetting

TOGGLES = [
    ("notify_water", "물 부족", "토양수분이 물주기 기준 아래로 내려가면 알려요"),
    ("notify_light", "빛 부족", "낮(09~18시) 최고 조도가 기준보다 낮으면 저녁 6시 이후 한 번 알려요"),
    ("notify_sensor", "센서 연결 점검", "24시간 넘게 센서 값이 들어오지 않으면 알려요"),
    ("notify_summary", "하루 한 번 요약", "매일 아침 화분 상태를 모아서 보내요"),
]


@app_view
def settings_page(request):
    setting, _ = UserSetting.objects.get_or_create(user=request.user)
    slot = request.GET.get("plant", "")
    context = {
        "alerts": my_alerts(request.user, slot=slot or None, limit=80),
        "plants": my_plants(request.user),
        "slot": slot,
        "setting": setting,
        "toggles": [{"name": n, "label": l, "help": h, "on": getattr(setting, n)} for n, l, h in TOGGLES],
        "channels": CHANNELS,
        # 알림이 없을 때 '센서 연결하기' 안내를 띄울 화분(연결 전·끊김)
        "first_waiting": waiting_summary(plant_rows(request.user))["first_waiting"],
        "nav": "alerts",
    }
    return render(request, "alerts/settings.html", context)


@app_view
@require_POST
def save_setting(request):
    """토글·받을 곳을 바꿀 때마다 저장한다. JSON {field, value}."""
    setting, _ = UserSetting.objects.get_or_create(user=request.user)
    try:
        data = json.loads(request.body.decode("utf-8"))
        field, value = data["field"], data["value"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "잘못된 요청이에요."}, status=400)
    if field in {n for n, _, _ in TOGGLES}:
        setattr(setting, field, bool(value))
    elif field == "channel" and value in dict(CHANNELS):
        setting.channel = value
    else:
        return JsonResponse({"error": "바꿀 수 없는 항목이에요."}, status=400)
    setting.save()
    return JsonResponse({"field": field, "value": getattr(setting, field)})

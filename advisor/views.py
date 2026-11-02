"""식물 상담소 API (홈 화면의 식물 상담소에서 쓴다).

- POST /plants/<pk>/chat/          질문
- GET  /plants/<pk>/chat/history/  그 화분의 최근 대화·추천 질문·안내 (화분을 바꿀 때)
- POST /plants/<pk>/chat/clear/    그 화분의 대화 전체 지우기
다른 사람 화분은 404. 질문·답변 원문은 로그에 남기지 않는다. 글은 JSON 문자열로만 보내고 화면에서는 textContent로 넣는다.
"""

import json

from django.contrib import messages
from django.http import JsonResponse as _JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import app_view
from plants.models import Plant
from plants.text import josa

from . import services


def JsonResponse(data, status=200):
    return _JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def message_json(m):
    at = timezone.localtime(m.created_at)
    # 템플릿의 {{ created_at|date:"n/j H:i" }}와 같은 모양
    return {"role": m.role, "content": m.content, "is_error": m.is_error, "at": f"{at.month}/{at.day} {at:%H:%M}"}


def counsel_url(plant):
    return reverse("plants:home") + f"?ask={plant.pk}#plant-counsel"


@app_view
@require_POST
def chat_ask(request, pk):
    plant = get_object_or_404(Plant.objects.select_related("crop"), pk=pk, owner=request.user)
    try:
        data = json.loads(request.body.decode("utf-8"))
        text = data.get("question") if isinstance(data, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "잘못된 요청이에요."}, status=400)
    try:
        result = services.ask(request.user, plant, text)
    except services.ChatRefused as exc:
        return JsonResponse({"error": exc.message, "remaining": services.remaining(request.user)}, status=exc.status)
    return JsonResponse(
        {
            "plant": plant.pk,
            "question": message_json(result.question),
            "answer": message_json(result.answer),
            "remaining": services.remaining(request.user),
        }
    )


@app_view
@never_cache
@require_GET
def chat_history(request, pk):
    plant = get_object_or_404(Plant.objects.select_related("crop"), pk=pk, owner=request.user)
    chat = services.panel_context(request.user, plant)
    return JsonResponse(
        {
            "plant": plant.pk,
            "enabled": chat["enabled"],
            "messages": [message_json(m) for m in chat["messages"]],
            "suggestions": chat["suggestions"],
            "note": chat["note"],
            "remaining": chat["remaining"],
        }
    )


@app_view
@require_POST
def chat_clear(request, pk):
    plant = get_object_or_404(Plant, pk=pk, owner=request.user)
    removed = services.clear(request.user, plant)
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"cleared": removed})
    messages.success(request, f"{josa(plant.title, '과', '와')} 나눈 상담소 대화를 지웠어요.")
    return redirect(counsel_url(plant))

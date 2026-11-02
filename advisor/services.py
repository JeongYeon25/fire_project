"""식물 상담: 질문 하나 처리(검사 → 한도 → 저장 → AI 호출 → 저장)와 상세 팝업용 데이터."""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from plants.services import NODATA, OFFLINE, plant_status

from . import llm
from .context import build_context, render_context
from .models import ChatMessage, ChatUsage
from .prompts import build_system, wrap_question

DISABLED_TEXT = "식물 상담소는 준비 중이에요."
USER_LIMIT_TEXT = "오늘 질문은 여기까지예요. 내일 다시 물어봐 주세요."
GLOBAL_LIMIT_TEXT = "오늘은 식물 상담소 질문이 많아 여기까지 받을게요. 내일 다시 물어봐 주세요."
ERROR_TEXTS = {
    "timeout": "AI가 답하는 데 너무 오래 걸렸어요. 잠시 후 다시 물어봐 주세요.",
    "rate_limit": "지금 식물 상담소 요청이 많아요. 잠시 후 다시 물어봐 주세요.",
    "auth": "식물 상담소 연결 설정을 확인해야 해요. 관리자에게 알려 주세요.",
}
DEFAULT_ERROR_TEXT = "AI 답변을 받지 못했어요. 잠시 후 다시 물어봐 주세요."

SUGGESTIONS = ["왜 이런 상태예요?", "오늘 뭐 해야 해요?", "물은 언제 줘요?"]
WAITING_SUGGESTIONS = ["센서 없이 뭘 할 수 있어요?", "오늘 뭐 해야 해요?"]
WAITING_NOTES = {
    NODATA: "센서 값이 없어서 일반적인 관리법만 알려 드려요.",
    OFFLINE: "센서 값이 끊겨서 끊기기 전 기록까지만 참고해요.",
}


class ChatRefused(Exception):
    """AI를 부르지 않고 돌려보내는 경우. status는 HTTP 상태."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class ChatResult:
    question: ChatMessage
    answer: ChatMessage


def clean_question(text):
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise ChatRefused("질문을 적어 주세요.", 400)
    if len(text) > settings.CHAT_QUESTION_MAX:
        raise ChatRefused(f"질문은 {settings.CHAT_QUESTION_MAX}자까지 적을 수 있어요.", 400)
    return text


def today(now=None):
    return timezone.localdate(now or timezone.now())


def used_today(user, now=None):
    return ChatUsage.objects.filter(owner=user, date=today(now)).values_list("count", flat=True).first() or 0


def remaining(user, now=None):
    """오늘 남은 질문 수. 사용자 한도가 꺼져 있으면(0) None."""
    limit = settings.CHAT_DAILY_LIMIT
    if limit <= 0:
        return None
    return max(0, limit - used_today(user, now))


def check_limits(user, now=None):
    if settings.CHAT_DAILY_LIMIT > 0 and used_today(user, now) >= settings.CHAT_DAILY_LIMIT:
        raise ChatRefused(USER_LIMIT_TEXT, 429)
    if settings.CHAT_GLOBAL_DAILY_LIMIT > 0:
        total = ChatUsage.objects.filter(date=today(now)).aggregate(n=Sum("count"))["n"] or 0
        if total >= settings.CHAT_GLOBAL_DAILY_LIMIT:
            raise ChatRefused(GLOBAL_LIMIT_TEXT, 429)


def count_question(user, now=None):
    """AI를 부르기 전에 센다(실패한 질문도 한도에 들어간다)."""
    usage, _ = ChatUsage.objects.get_or_create(owner=user, date=today(now))
    ChatUsage.objects.filter(pk=usage.pk).update(count=F("count") + 1)


def recent_pairs(plant, before_id, pairs=None):
    """직전 대화(질문 + 정상 답변) 쌍. 오류 안내 답은 뺀다. [Message, …] 오래된 순."""
    pairs = settings.CHAT_HISTORY_PAIRS if pairs is None else pairs
    if pairs <= 0:
        return []
    rows = list(ChatMessage.objects.filter(plant=plant, id__lt=before_id).order_by("-created_at", "-id")[: pairs * 4])
    rows.reverse()
    found = []
    for prev, cur in zip(rows, rows[1:]):
        if prev.role == ChatMessage.USER and cur.role == ChatMessage.ASSISTANT and not cur.is_error:
            found.append([llm.Message("user", wrap_question(prev.content)), llm.Message("assistant", cur.content)])
    return [m for pair in found[-pairs:] for m in pair]


def ask(user, plant, text, now=None):
    """질문 하나 처리. 다른 사람 화분은 뷰에서 404로 막는다(여기서도 확인)."""
    if plant.owner_id != user.pk:
        raise ChatRefused("화분을 찾을 수 없어요.", 404)
    question_text = clean_question(text)
    if not llm.is_enabled():
        raise ChatRefused(DISABLED_TEXT, 503)
    with transaction.atomic():
        check_limits(user, now)
        count_question(user, now)
        question = ChatMessage.objects.create(owner=user, plant=plant, role=ChatMessage.USER, content=question_text)

    system = build_system(render_context(build_context(plant, now)))
    messages = recent_pairs(plant, question.id) + [llm.Message("user", wrap_question(question_text))]
    try:
        content, is_error = llm.complete(system, messages), False
    except llm.LLMError as exc:
        content, is_error = ERROR_TEXTS.get(exc.kind, DEFAULT_ERROR_TEXT), True
    answer = ChatMessage.objects.create(owner=user, plant=plant, role=ChatMessage.ASSISTANT, content=content, is_error=is_error)
    return ChatResult(question, answer)


def clear(user, plant):
    return ChatMessage.objects.filter(owner=user, plant=plant).delete()[0]


def pick_plant(rows, wanted=None):
    """홈 식물 상담소에서 처음 고를 화분 row. rows = plants.views.plant_rows(user) (내 화분만).
    ?ask=<pk>가 내 화분이면 그것, 아니면(다른 사람 화분·없는 번호 포함) 돌봐 줄 화분 우선, 없으면 첫 화분."""
    if not rows:
        return None
    try:
        wanted = int(wanted) if wanted not in (None, "") else None
    except (TypeError, ValueError):
        wanted = None
    for row in rows:
        if wanted is not None and row["plant"].pk == wanted:
            return row
    return next((r for r in rows if r["status"].has_problem), rows[0])


def panel_context(user, plant, status=None):
    """식물 상담소에서 고른 화분의 기록·추천 질문·안내."""
    status = status or plant_status(plant)
    shown = list(ChatMessage.objects.filter(owner=user, plant=plant).order_by("-created_at", "-id")[: settings.CHAT_HISTORY_SHOWN])
    shown.reverse()
    waiting = status.state in (NODATA, OFFLINE)
    return {
        "enabled": llm.is_enabled(),
        "messages": shown,
        "remaining": remaining(user),
        "suggestions": WAITING_SUGGESTIONS if waiting else SUGGESTIONS,
        "note": WAITING_NOTES.get(status.state, ""),
        "max_len": settings.CHAT_QUESTION_MAX,
        "disabled_text": DISABLED_TEXT,
    }

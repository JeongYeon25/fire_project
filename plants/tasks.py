"""할 일(Task) 날짜 계산과 챗봇용 조회. 날짜는 모두 서울(settings.TIME_ZONE) 기준이다.

- 오늘 = timezone.localdate(now). 예: UTC 10-19 15:30 = 서울 10-20 00:30 → 오늘은 20일.
- 지난 할 일 = 날짜가 오늘보다 앞이고 아직 체크하지 않은 것.
- 예정 = 날짜가 오늘보다 뒤이고 아직 체크하지 않은 것.
- 챗봇(2단계)은 tasks_due_for_notification()으로 오늘 알림 켠 할 일을 시각 순으로 받아 보내고,
  mark_notified()로 표시해 같은 할 일을 두 번 보내지 않는다. 시각이 비어 있으면 아침 9시로 친다.
"""

from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .models import Task

RECENT_DONE_DAYS = 7


def today(now=None):
    return timezone.localdate(now or timezone.now())


def overdue(owner, now=None):
    return Task.objects.filter(owner=owner, due_date__lt=today(now), done_at__isnull=True).select_related("plant")


def due_today(owner, now=None):
    return Task.objects.filter(owner=owner, due_date=today(now)).select_related("plant")


def upcoming(owner, now=None):
    return Task.objects.filter(owner=owner, due_date__gt=today(now), done_at__isnull=True).select_related("plant")


def recently_done(owner, now=None):
    """오늘보다 앞 날짜인데 최근 7일 안에 체크한 것(오늘 할 일은 오늘 목록에 그대로 보인다)."""
    now = now or timezone.now()
    return (
        Task.objects.filter(owner=owner, due_date__lt=today(now), done_at__gte=now - timedelta(days=RECENT_DONE_DAYS))
        .select_related("plant")
        .order_by("-done_at")
    )


def group_upcoming_by_date(tasks):
    """[(날짜, [할 일…]), …]"""
    groups = []
    for task in tasks:
        if groups and groups[-1][0] == task.due_date:
            groups[-1][1].append(task)
        else:
            groups.append((task.due_date, [task]))
    return groups


def tasks_due_for_notification(now=None, owner=None):
    """챗봇용: 오늘 날짜, 알림 켬, 미완료, 아직 안 보낸 할 일을 알림 시각 순으로.

    now까지 시각이 된 것만 고르려면 [t for t in ... if t.notify_at() <= now]처럼 거르면 된다.
    """
    qs = Task.objects.filter(due_date=today(now), notify=True, done_at__isnull=True, notified_at__isnull=True)
    if owner is not None:
        qs = qs.filter(owner=owner)
    tasks = list(qs.select_related("owner", "plant").order_by(F("due_time").asc(nulls_last=True), "created_at"))
    # 시각이 비어 있으면 09:00으로 친 순서로 다시 정렬한다.
    return sorted(tasks, key=lambda t: (t.notify_at(), t.created_at))


def mark_notified(task, at=None):
    """보냈다고 표시한다. 이미 표시돼 있으면 바꾸지 않고 False."""
    updated = Task.objects.filter(pk=task.pk, notified_at__isnull=True).update(notified_at=at or timezone.now())
    return bool(updated)

"""할 일 화면(/tasks/)과 추가·수정·체크·삭제. 홈의 '오늘 할 일' 창에서 링크로 들어온다(메뉴에는 없음)."""

import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import app_view

from . import tasks as task_service
from .forms import TaskForm, first_error
from .models import Task

BACK = {"home": "plants:home", "tasks": "plants:tasks"}


def _back(request):
    return redirect(BACK.get(request.POST.get("next"), "plants:tasks"))


def _my_task(request, pk):
    return get_object_or_404(Task, pk=pk, owner=request.user)


@app_view
def tasks_page(request):
    user = request.user
    upcoming = list(task_service.upcoming(user))
    context = {
        "today": task_service.today(),
        "overdue_tasks": task_service.overdue(user),
        "today_tasks": task_service.due_today(user),
        "upcoming_groups": task_service.group_upcoming_by_date(upcoming),
        "upcoming_count": len(upcoming),
        "done_tasks": task_service.recently_done(user),
        "task_form": TaskForm(owner=user, initial={"due_date": task_service.today(), "notify": True}),
        "nav": "home",
    }
    return render(request, "plants/tasks.html", context)


@app_view
def task_panel(request, pk):
    """수정 팝업 본문(HTML 조각)."""
    task = _my_task(request, pk)
    return render(request, "plants/_task_form.html", {"form": TaskForm(instance=task, owner=request.user), "task": task})


@app_view
@require_POST
def task_add(request):
    form = TaskForm(request.POST, owner=request.user)
    if not form.is_valid():
        messages.error(request, "할 일을 추가하지 못했어요. " + first_error(form))
        return _back(request)
    task = form.save(commit=False)
    task.owner = request.user
    task.save()
    when = "오늘" if task.due_date == task_service.today() else f"{task.due_date.month}월 {task.due_date.day}일"
    messages.success(request, f"{when} 할 일에 넣었어요: {task.title}")
    return _back(request)


@app_view
@require_POST
def task_edit(request, pk):
    task = _my_task(request, pk)
    form = TaskForm(request.POST, instance=task, owner=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "할 일을 고쳤어요.")
    else:
        messages.error(request, "고치지 못했어요. " + first_error(form))
    return _back(request)


@app_view
@require_POST
def task_delete(request, pk):
    task = _my_task(request, pk)
    task.delete()
    messages.success(request, "할 일을 지웠어요.")
    return _back(request)


@app_view
@require_POST
def task_move_today(request, pk):
    """지난 할 일을 오늘로 옮긴다(날짜가 바뀌므로 알림도 다시 대상이 된다)."""
    task = _my_task(request, pk)
    task.due_date = task_service.today()
    task.notified_at = None
    task.save(update_fields=["due_date", "notified_at", "updated_at"])
    messages.success(request, f"오늘 할 일로 옮겼어요: {task.title}")
    return _back(request)


@app_view
@require_POST
def task_check(request, pk):
    """체크/체크 해제(JSON {done: true/false})."""
    task = _my_task(request, pk)
    try:
        done = bool(json.loads(request.body.decode("utf-8"))["done"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "잘못된 요청이에요."}, status=400)
    task.done_at = timezone.now() if done else None
    task.save(update_fields=["done_at", "updated_at"])
    return JsonResponse({"id": task.pk, "done": task.is_done})

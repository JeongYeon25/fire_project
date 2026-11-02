from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.decorators import app_view
from advisor.services import panel_context as advisor_panel
from advisor.services import pick_plant
from alerts.models import AlertLog

from . import tasks as task_service
from .forms import PlantAddForm, PlantEditForm, TaskForm, first_error
from .metrics import METRICS, gauges
from .models import PLANT_NAME_MAX, Plant, PlantPhoto, SensorReading, TodoCheck, next_slot, selectable_crops
from .photos import MAX_UPLOAD_BYTES, PhotoUploadForm, now_input_value
from .services import NODATA, OFFLINE, latest_reading, plant_status
from .text import josa, josa_ro


def my_plants(user):
    """그 사용자의 화분만."""
    return Plant.objects.filter(owner=user).select_related("crop")


def plant_rows(user):
    """화분 + 상태 + 최신 측정값 목록."""
    rows = []
    for plant in my_plants(user):
        rows.append({"plant": plant, "status": plant_status(plant), "latest": latest_reading(plant)})
    return rows


def todo_items(user, rows):
    """자동 할 일: 물·빛 부족일 때 생긴다(센서 연결 전·끊김 화분은 판정하지 않으니 생기지 않는다)."""
    today = timezone.localdate()
    checked = set(TodoCheck.objects.filter(owner=user, date=today).values_list("key", flat=True))
    items = []
    for row in rows:
        plant, status = row["plant"], row["status"]
        if status.water_low:
            items.append(("water:" + plant.slot, f"{plant.title}에 물 주기 (토양수분 {int(status.moisture)}%)"))
        if status.light_low:
            items.append(("light:" + plant.slot, f"{josa(plant.title, '을', '를')} 밝은 곳으로 옮기기"))
    return [{"key": key, "text": text, "checked": key in checked} for key, text in items]


def my_alerts(user, slot=None, limit=None):
    qs = AlertLog.objects.filter(plant__owner=user).select_related("plant")
    if slot:
        qs = qs.filter(plant__slot=slot)
    return qs[:limit] if limit else qs


def waiting_summary(rows):
    """센서 연결 전·끊김 화분 정리(홈 요약·빈 화면 안내용)."""
    nodata = [r["plant"] for r in rows if r["status"].state == NODATA]
    offline = [r["plant"] for r in rows if r["status"].state == OFFLINE]
    return {
        "nodata_plants": nodata,
        "offline_plants": offline,
        "first_waiting": (nodata or offline or [None])[0],
        "any_connected": any(r["latest"] for r in rows),
    }


@app_view
def home(request):
    rows = plant_rows(request.user)
    sensor_tiles = []
    for key, meta in METRICS.items():
        values = []
        for row in rows:
            latest = row["latest"]
            values.append({"plant": row["plant"], "status": row["status"], "value": getattr(latest, key) if latest else None})
        sensor_tiles.append({"key": key, **meta, "values": values})
    upcoming = list(task_service.upcoming(request.user))
    # 식물 상담소: 내 화분만 선택지. ?ask=<pk>(내 화분일 때만) → 돌봐 줄 화분 → 첫 화분
    counsel_row = pick_plant(rows, request.GET.get("ask"))
    context = {
        "rows": rows,
        "counsel_row": counsel_row,
        "chat": advisor_panel(request.user, counsel_row["plant"], counsel_row["status"]) if counsel_row else None,
        "problem_count": sum(1 for r in rows if r["status"].has_problem),
        **waiting_summary(rows),
        "todos": todo_items(request.user, rows),
        "overdue_tasks": task_service.overdue(request.user),
        "today_tasks": task_service.due_today(request.user),
        "upcoming_count": len(upcoming),
        "next_upcoming": upcoming[0] if upcoming else None,
        "task_form": TaskForm(owner=request.user, initial={"due_date": task_service.today(), "notify": True}),
        "alerts": my_alerts(request.user, limit=3),
        "sensor_tiles": sensor_tiles,
        "nav": "home",
    }
    return render(request, "plants/home.html", context)


# 새로 발급한 키를 한 번 보여 주기 위해 세션에 잠깐 담아 두는 이름
NEW_KEY_SESSION = "new_api_key_plant"


@app_view
def plant_list(request):
    rows = plant_rows(request.user)
    crops = list(selectable_crops())
    # 새 식물 추가의 기본 작물: 내 작물(Profile.crop), 없으면 첫 작물
    default_crop = next((c for c in crops if c.pk == request.profile.crop_id), crops[0] if crops else None)
    context = {
        "rows": rows,
        "crops": crops,
        "default_crop_id": default_crop.pk if default_crop else None,
        "default_example": default_crop.name_example if default_crop else "",
        "name_max": PLANT_NAME_MAX,
        "next_slot": next_slot(request.user),
        "open_id": request.GET.get("open", ""),
        "nav": "plants",
    }
    return render(request, "plants/plant_list.html", context)


@app_view
def plant_panel(request, pk):
    """상세 팝업 본문(HTML 조각)."""
    plant = get_object_or_404(Plant.objects.select_related("crop"), pk=pk, owner=request.user)
    status = plant_status(plant)
    latest = latest_reading(plant)
    context = {
        "plant": plant,
        "status": status,
        "latest": latest,
        "gauges": gauges(plant.crop, latest, status),
        "photos": plant.photos.all()[:4],
        "crops": selectable_crops(include=plant.crop_id),
        "name_max": PLANT_NAME_MAX,
        "compare_slots": "A" if plant.slot == "A" else f"A,{plant.slot}",
        "compare_plant": my_plants(request.user).filter(slot="A").exclude(pk=plant.pk).first(),
    }
    return render(request, "plants/_plant_panel.html", context)


@app_view
@require_POST
def plant_edit(request, pk):
    """작물 바꾸기 / 이름 바꾸기 / 설명 고치기."""
    plant = get_object_or_404(Plant, pk=pk, owner=request.user)
    old_crop_id = plant.crop_id
    form = PlantEditForm(request.POST, instance=plant)
    if form.is_valid():
        plant = form.save()
        if plant.crop_id != old_crop_id:
            messages.success(request, f"{plant.short_name}의 작물을 {josa_ro(plant.crop.name)} 바꿨어요. 상태도 {plant.crop.name} 기준으로 판단해요.")
        else:
            messages.success(request, f"{plant.short_name}의 정보를 저장했어요.")
    else:
        messages.error(request, "저장하지 못했어요. " + first_error(form))
    return redirect(reverse("plants:list") + f"?open={plant.pk}")


@app_view
@require_POST
def plant_add(request):
    slot = next_slot(request.user)
    form = PlantAddForm(request.POST)
    if slot is None:
        messages.error(request, "더 이상 화분을 추가할 수 없어요.")
        return redirect("plants:list")
    if not form.is_valid():
        messages.error(request, "새 식물을 추가하지 못했어요. " + first_error(form))
        return redirect("plants:list")
    plant = form.save(commit=False)
    plant.owner = request.user
    plant.slot = slot
    plant.save()
    request.session[NEW_KEY_SESSION] = plant.pk
    messages.success(request, f"{josa(plant.title, '을', '를')} 등록했어요.")
    return redirect("plants:key", pk=plant.pk)


@app_view
@never_cache
def plant_key(request, pk):
    """센서 API 키 화면. 키 원문은 발급 직후 한 번만 보여 준다."""
    plant = get_object_or_404(Plant, pk=pk, owner=request.user)
    show_key = request.session.get(NEW_KEY_SESSION) == plant.pk
    if show_key:
        del request.session[NEW_KEY_SESSION]
    return render(request, "plants/plant_key.html", {"plant": plant, "show_key": show_key, "nav": "plants"})


@app_view
@require_POST
def plant_key_reissue(request, pk):
    plant = get_object_or_404(Plant, pk=pk, owner=request.user)
    plant.reissue_api_key()
    request.session[NEW_KEY_SESSION] = plant.pk
    if plant.readings.exists():
        messages.success(request, f"{plant.title}의 센서 API 키를 새로 발급했어요. 이전 키는 이제 쓸 수 없어요.")
    else:
        messages.success(request, f"{plant.title}의 센서 API 키예요. 센서 설정에 넣어 주세요.")
    return redirect("plants:key", pk=plant.pk)


@app_view
def graph(request):
    plants = list(my_plants(request.user))
    has_readings = SensorReading.objects.filter(plant__owner=request.user).exists()
    waiting = next((p for p in plants if not p.readings.exists()), None)
    context = {
        "plants": plants,
        "has_readings": has_readings,
        "first_waiting": waiting,
        "metrics": METRICS,
        "metric": request.GET.get("metric", "moisture") if request.GET.get("metric") in METRICS else "moisture",
        "nav": "graph",
    }
    return render(request, "plants/graph.html", context)


@app_view
def photos(request):
    slot = request.GET.get("plant", "")
    qs = PlantPhoto.objects.filter(plant__owner=request.user).select_related("plant")
    if slot:
        qs = qs.filter(plant__slot=slot)
    selected = my_plants(request.user).filter(slot=slot).first() if slot else None
    context = {
        "photos": qs[:120],
        "plants": my_plants(request.user),
        "slot": slot,
        "selected_plant_id": selected.pk if selected else None,
        "now_value": now_input_value(),
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "nav": "photos",
    }
    return render(request, "plants/photos.html", context)


@app_view
@require_POST
def photo_upload(request):
    form = PhotoUploadForm(request.POST, request.FILES, owner=request.user)
    back = reverse("plants:photos")
    if not form.is_valid():
        errors = [e for field_errors in form.errors.values() for e in field_errors]
        messages.error(request, "사진을 올리지 못했어요. " + " ".join(errors))
        return redirect(back)
    photo = form.save()
    messages.success(request, f"{photo.plant.title} 사진을 올렸어요.")
    return redirect(back + f"?plant={photo.plant.slot}")


@app_view
@require_POST
def photo_delete(request, pk):
    photo = get_object_or_404(PlantPhoto.objects.select_related("plant"), pk=pk, plant__owner=request.user)
    slot = photo.plant.slot
    photo.image.delete(save=False)
    photo.delete()
    messages.success(request, "사진을 지웠어요.")
    return redirect(reverse("plants:photos") + f"?plant={slot}")


@app_view
def photo_panel(request, pk):
    photo = get_object_or_404(PlantPhoto.objects.select_related("plant"), pk=pk, plant__owner=request.user)
    return render(request, "plants/_photo_panel.html", {"photo": photo, "reading": photo.reading_at_time()})


def root(request):
    if request.user.is_authenticated and getattr(request.user, "profile", None) and request.user.profile.onboarded:
        return redirect("plants:home")
    return redirect("accounts:onboarding")

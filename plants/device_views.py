"""내 기기 화면: 센서 기기 등록·키 발급/재발급·채널 연결·보관.

- 모두 로그인한 사용자 본인의 기기만 다룬다(다른 사람 기기·보관한 기기는 404).
- 기기 키 원문은 DB·세션·메시지에 넣지 않는다. 등록·재발급 POST의 응답 화면에서만 한 번 보여 준다(no-store).
  새로고침으로 같은 POST가 다시 가면 기기가 또 생기거나 키가 또 바뀌므로, 폼마다 한 번만 쓰는 표(nonce)를 넣어 막는다.
"""

import secrets

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.decorators import app_view

from .devices import archive_device, rebuild_device
from .forms import DeviceAddForm, DeviceChannelForm, first_error
from .models import Plant, SensorDevice, generate_device_id
from .text import josa

NONCE_SESSION = "device_form_nonces"
NONCE_KEEP = 10

STATES = {
    "connected": ("연결됨", "ok"),
    "offline": ("연결 끊김", "offline"),
    "waiting": ("아직 수신 없음", "nodata"),
}


def my_devices(user):
    return SensorDevice.objects.filter(owner=user, archived_at__isnull=True)


def get_my_device(request, pk):
    return get_object_or_404(my_devices(request.user), pk=pk)


def new_nonce(request):
    """폼 한 번에 하나. 여러 탭을 위해 최근 몇 개만 기억한다."""
    nonce = secrets.token_urlsafe(16)
    nonces = request.session.get(NONCE_SESSION, [])[-(NONCE_KEEP - 1):]
    request.session[NONCE_SESSION] = nonces + [nonce]
    return nonce


def use_nonce(request):
    """보낸 표가 아직 안 쓴 것이면 쓰고 True."""
    nonce = request.POST.get("nonce", "")
    nonces = request.session.get(NONCE_SESSION, [])
    if not nonce or nonce not in nonces:
        return False
    nonces.remove(nonce)
    request.session[NONCE_SESSION] = nonces
    return True


def send_url(request):
    """기기가 보낼 주소. .env PUBLIC_BASE_URL이 있으면 그것, 없으면 지금 접속한 주소."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL + "/api/readings"
    return request.build_absolute_uri("/api/readings")


def device_row(device):
    label, chip = STATES[device.connection_state()]
    links = [ch for ch in device.channels.all() if ch.plant_id]
    return {"device": device, "state_label": label, "state_chip": chip, "links": links}


def show_key(request, device, raw_key, created):
    context = {"device": device, "raw_key": raw_key, "send_url": send_url(request), "created": created, "nav": "devices"}
    return render(request, "plants/device_key.html", context)


@app_view
@never_cache
def devices(request):
    items = list(my_devices(request.user).prefetch_related("channels__plant"))
    limit = settings.DEVICE_LIMIT_PER_USER
    context = {
        "rows": [device_row(d) for d in items],
        "form": DeviceAddForm(),
        "limit": limit,
        "can_add": len(items) < limit,
        "nonce": new_nonce(request),
        "nav": "devices",
    }
    return render(request, "plants/devices.html", context)


@app_view
@never_cache
@require_POST
def device_add(request):
    if not use_nonce(request):
        messages.info(request, "이미 처리한 요청이에요. 키가 필요하면 기기 설정에서 다시 발급해 주세요.")
        return redirect("plants:devices")
    form = DeviceAddForm(request.POST)
    if not form.is_valid():
        messages.error(request, "기기를 등록하지 못했어요. " + first_error(form))
        return redirect("plants:devices")
    with transaction.atomic():
        if my_devices(request.user).select_for_update().count() >= settings.DEVICE_LIMIT_PER_USER:
            messages.error(request, f"기기는 {settings.DEVICE_LIMIT_PER_USER}대까지 등록할 수 있어요. 쓰지 않는 기기를 보관한 뒤 다시 등록해 주세요.")
            return redirect("plants:devices")
        name = form.cleaned_data["name"]
        device = SensorDevice.objects.create(owner=request.user, name=name, device_id=generate_device_id(name))
        raw_key = device.issue_key()
    return show_key(request, device, raw_key, created=True)


@app_view
@never_cache
def device_detail(request, pk):
    device = get_my_device(request, pk)
    label, chip = STATES[device.connection_state()]
    context = {
        "device": device,
        "state_label": label,
        "state_chip": chip,
        "form": DeviceChannelForm(device=device),
        "has_plants": Plant.objects.filter(owner=request.user).exists(),
        "send_url": send_url(request),
        "nonce": new_nonce(request),
        "nav": "devices",
    }
    return render(request, "plants/device_detail.html", context)


@app_view
@require_POST
def device_channels(request, pk):
    device = get_my_device(request, pk)
    form = DeviceChannelForm(request.POST, device=device)
    if not form.is_valid():
        messages.error(request, "채널 연결을 저장하지 못했어요. " + first_error(form))
        return redirect("plants:device", pk=device.pk)
    with transaction.atomic():
        changed = form.save()
        made = rebuild_device(device) if changed else None
    if changed:
        messages.success(request, f"채널 연결을 저장하고 이 기기에서 받은 값으로 화분 측정값을 다시 계산했어요({made:,}행).")
    else:
        messages.info(request, "바뀐 연결이 없어요.")
    return redirect("plants:device", pk=device.pk)


@app_view
@never_cache
@require_POST
def device_key_reissue(request, pk):
    device = get_my_device(request, pk)
    if not use_nonce(request):
        messages.info(request, "이미 처리한 요청이에요. 키가 필요하면 다시 발급해 주세요.")
        return redirect("plants:device", pk=device.pk)
    raw_key = device.issue_key()
    return show_key(request, device, raw_key, created=False)


@app_view
@require_POST
def device_archive(request, pk):
    device = get_my_device(request, pk)
    archive_device(device)
    messages.success(
        request, f"{josa(device.title, '을', '를')} 보관했어요. 키는 더 이상 쓸 수 없고, 지금까지 받은 값은 그대로 남아 있어요."
    )
    return redirect("plants:devices")

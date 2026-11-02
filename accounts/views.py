from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from alerts.models import UserSetting
from plants.characters import STATE_WORDS, STATES
from plants.forms import PlantNameForm
from plants.models import PLANT_NAME_MAX, Crop, Plant
from plants.text import josa

from .forms import CropChoiceForm, LoginForm, SignupForm
from .models import Profile

User = get_user_model()

# 온보딩: 회원가입(닉네임·비밀번호) → 작물 선택 → 이름 짓기 → A 화분
STEPS = ["회원가입", "작물 선택", "이름 짓기"]
PROGRESS = {1: 33, 2: 67, 3: 100}
# 첫 화면 장식: 선택할 수 있는 작물 7종과 액자 체크무늬 색
INTRO_CROPS = [
    ("strawberry", "pink"),
    ("tomato", "yellow"),
    ("basil", "ok"),
    ("kidney-bean", "lavender"),
    ("sunflower", "sky"),
    ("lettuce", "ok"),
    ("balsam", "pink"),
]


def _profile_for(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    UserSetting.objects.get_or_create(user=user)
    return profile


def _current_step(request):
    """지금 보여 줄 단계. 온보딩을 마쳤으면 None."""
    if not request.user.is_authenticated:
        return 1
    profile = _profile_for(request.user)
    if profile.onboarded:
        return None
    if request.GET.get("step") == "crop" or profile.crop_id is None:
        return 2
    return profile.onboarding_step


def onboarding(request, signup_form=None, login_form=None, name_form=None, tab=None):
    step = _current_step(request)
    if step is None:
        return redirect("plants:home")
    profile = request.user.profile if request.user.is_authenticated else None
    context = {
        "step": step,
        "steps": [{"no": i + 1, "name": name, "done": i + 1 < step} for i, name in enumerate(STEPS)],
        "progress": PROGRESS[step],
        "tab": tab or request.GET.get("tab", "signup"),
        "signup_form": signup_form or SignupForm(),
        "login_form": login_form or LoginForm(),
        "name_form": name_form or PlantNameForm(),
        "name_max": PLANT_NAME_MAX,
        "crops": Crop.objects.filter(is_active=True),
        "crop": profile.crop if profile else None,
        "selected_crop_id": profile.crop_id if profile else None,
        "states": [(s, STATE_WORDS[s]) for s in STATES],
        "intro_crops": INTRO_CROPS,
    }
    return render(request, "accounts/onboarding.html", context)


@require_POST
def signup(request):
    form = SignupForm(request.POST)
    if not form.is_valid():
        return onboarding(request, signup_form=form, tab="signup")
    data = form.cleaned_data
    with transaction.atomic():
        user = User.objects.create_user(username=data["nickname"], password=data["password"])
        Profile.objects.create(user=user)
        UserSetting.objects.create(user=user)
    login(request, user)
    return redirect("accounts:onboarding")


@require_POST
def login_view(request):
    form = LoginForm(request.POST)
    if form.is_valid():
        user = authenticate(request, username=form.cleaned_data["nickname"], password=form.cleaned_data["password"])
        if user is not None:
            login(request, user)
            return redirect("accounts:onboarding")
        form.add_error(None, "닉네임 또는 비밀번호가 맞지 않아요.")
    return onboarding(request, login_form=form, tab="login")


@require_POST
def choose_crop(request):
    if not request.user.is_authenticated:
        return redirect("accounts:onboarding")
    profile = _profile_for(request.user)
    form = CropChoiceForm(request.POST)
    if not form.is_valid():
        messages.error(request, "작물을 골라 주세요.")
        return redirect(reverse("accounts:onboarding") + "?step=crop")
    if profile.onboarded:
        return redirect("plants:home")
    profile.crop = form.cleaned_data["crop"]
    profile.onboarding_step = Profile.STEP_NAME
    profile.save()
    return redirect("accounts:onboarding")


@require_POST
def choose_name(request):
    """3단계 '이름 지어 주세요': 이름을 받아 첫 화분(A)을 만들고 온보딩을 마친다."""
    if not request.user.is_authenticated:
        return redirect("accounts:onboarding")
    profile = _profile_for(request.user)
    if profile.onboarded:
        return redirect("plants:home")
    if profile.crop_id is None:
        return redirect("accounts:onboarding")
    form = PlantNameForm(request.POST)
    if not form.is_valid():
        return onboarding(request, name_form=form)
    name = form.cleaned_data["name"]
    with transaction.atomic():
        if not Plant.objects.filter(owner=request.user).exists():
            Plant.objects.create(owner=request.user, slot="A", crop=profile.crop, name=name)
        profile.onboarding_step = Profile.STEP_DONE
        profile.save()
    messages.success(request, f"반가워요, {profile.nickname}! {josa(name, '과', '와')} 함께 키워 봐요.")
    # 처음 가입한 사람은 홈으로 가기 전에 사용 안내를 본다.
    return redirect("accounts:intro")


@login_required
def intro(request):
    """사용 안내 슬라이드. 처음(온보딩 직후) 또는 설정의 '다시 보기'(?again=1)."""
    profile = _profile_for(request.user)
    if not profile.onboarded:
        return redirect("accounts:onboarding")
    again = request.GET.get("again") == "1"
    return render(request, "accounts/intro.html", {"crop": profile.crop_slug, "again": again})


@login_required
@require_POST
def intro_done(request):
    """건너뛰기·닫기·시작하기 모두 여기로. 한 번 누르면 다시 자동으로 뜨지 않는다."""
    profile = _profile_for(request.user)
    if profile.intro_seen_at is None:
        profile.intro_seen_at = timezone.now()
        profile.save(update_fields=["intro_seen_at"])
    if request.POST.get("again") == "1":
        return redirect("alerts:settings")
    return redirect("plants:home")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:onboarding")

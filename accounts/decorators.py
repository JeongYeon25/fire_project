from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def app_view(view):
    """로그인하고 온보딩(작물 선택·이름 짓기)을 마친 사용자만 들어올 수 있다.

    사용 안내를 아직 보지(건너뛰지) 않았으면 화면(GET) 요청은 안내로 보낸다.
    JSON API(/api/…)와 저장(POST)은 막지 않는다. /admin/과 센서 수신 API는 이 데코레이터를 쓰지 않는다.
    통과하면 request.profile을 붙여 준다. 화면은 모두 request.user의 화분만 다룬다.
    """

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        if profile is None or not profile.onboarded:
            return redirect("accounts:onboarding")
        if profile.intro_seen_at is None and request.method == "GET" and not request.path.startswith("/api/"):
            return redirect("accounts:intro")
        request.profile = profile
        return view(request, *args, **kwargs)

    return wrapper

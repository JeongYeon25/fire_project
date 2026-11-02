def profile(request):
    """사이드 메뉴(로고 얼굴, 내 정보)에서 쓰는 프로필."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"my_profile": None}
    return {"my_profile": getattr(user, "profile", None)}

from django.contrib import admin

from .models import Profile

# 계정(User)을 지울 때 쓰는 관리자 화면. 여기서는 그 계정의 프로필이 함께 지워지는 것을 허용한다.
USER_DELETE_URLS = {"auth_user_delete", "auth_user_changelist"}


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """프로필은 보기·수정만. 프로필만 지우면 그 계정이 온보딩부터 다시 하게 되므로 관리자 화면에서 지울 수 없다.

    - 목록의 '선택한 항목 삭제' 액션은 삭제 권한이 없으면 Django가 자동으로 뺀다.
    - 개별 삭제 화면(/admin/accounts/profile/<id>/delete/)은 권한이 없어 403.
    - 계정(User) 삭제는 지금처럼 되고, 그때 프로필도 함께 지워진다(CASCADE).
    """

    list_display = ["user", "crop", "onboarding_step", "condition_changed_at", "intro_seen_at"]

    def has_delete_permission(self, request, obj=None):
        match = getattr(request, "resolver_match", None)
        if match is not None and match.url_name in USER_DELETE_URLS:
            return super().has_delete_permission(request, obj)
        return False

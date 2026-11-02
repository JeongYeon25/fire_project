from django.conf import settings
from django.db import models


class Profile(models.Model):
    """닉네임은 User.username을 그대로 쓴다."""

    STEP_CROP = 2
    STEP_NAME = 3
    STEP_DONE = 4

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    # 키우는 작물: 사이드 메뉴 표시, 로고 얼굴, 새 식물 추가의 기본 작물
    crop = models.ForeignKey("plants.Crop", on_delete=models.SET_NULL, null=True, blank=True)
    onboarding_step = models.PositiveSmallIntegerField(default=STEP_CROP)
    # 실험 조건을 바꾼 시각(그래프의 "조건 변경" 세로선)
    condition_changed_at = models.DateTimeField("실험 조건 변경 시각", null=True, blank=True)
    # 가입 후 '사용 안내' 슬라이드를 끝까지 봤거나 건너뛴 시각. 비어 있으면 앱 화면을 열 때 안내로 보낸다.
    intro_seen_at = models.DateTimeField("사용 안내 본 시각", null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "프로필"

    def __str__(self):
        return self.user.username

    @property
    def nickname(self):
        return self.user.username

    @property
    def onboarded(self):
        return self.onboarding_step >= self.STEP_DONE

    @property
    def intro_seen(self):
        return self.intro_seen_at is not None

    @property
    def crop_slug(self):
        """로고 얼굴에 쓰는 작물. 아직 고르지 않았으면 토마토."""
        return self.crop.slug if self.crop_id else "tomato"

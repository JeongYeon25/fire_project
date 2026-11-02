from django.conf import settings
from django.db import models
from django.utils import timezone


class DiaryEntry(models.Model):
    """나만 보는 식물 일기. is_auto면 서비스가 남긴 자동 기록."""

    # 계정을 지우면 그 사람의 다이어리도 함께 지워진다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="diary_entries", verbose_name="주인")
    plant = models.ForeignKey("plants.Plant", on_delete=models.SET_NULL, null=True, blank=True, related_name="diary_entries")
    content = models.TextField("내용", max_length=1000)
    is_auto = models.BooleanField("자동 기록", default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = verbose_name_plural = "다이어리"

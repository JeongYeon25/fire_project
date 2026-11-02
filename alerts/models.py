from django.conf import settings
from django.db import models
from django.utils import timezone

CHANNELS = [
    ("telegram", "텔레그램"),
    ("kakao", "카카오톡"),
    ("email", "이메일"),
]


class AlertLog(models.Model):
    KIND_CHOICES = [
        ("water", "물 부족"),
        ("light", "빛 부족"),
        ("sensor", "센서 연결 점검"),
        ("summary", "하루 요약"),
    ]

    plant = models.ForeignKey("plants.Plant", on_delete=models.CASCADE, related_name="alerts")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    message = models.CharField(max_length=200)
    channel = models.CharField(max_length=10, choices=CHANNELS, default="telegram")
    sent_at = models.DateTimeField("알림 시각", default=timezone.now, db_index=True)
    # 상태가 정상으로 돌아온 시각. 비어 있으면 미해결 — 같은 화분·종류의 알림을 새로 만들지 않는다.
    resolved_at = models.DateTimeField("해결 시각", null=True, blank=True)
    is_demo = models.BooleanField(default=False)

    class Meta:
        ordering = ["-sent_at"]
        indexes = [models.Index(fields=["plant", "kind", "resolved_at"])]
        verbose_name = verbose_name_plural = "알림 기록"

    @property
    def is_resolved(self):
        return self.resolved_at is not None

    @property
    def tracks_resolution(self):
        """하루 요약은 해결 개념이 없다."""
        return self.kind != "summary"


class UserSetting(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_setting")
    notify_water = models.BooleanField("물 부족 알림", default=True)
    notify_light = models.BooleanField("빛 부족 알림", default=True)
    notify_sensor = models.BooleanField("센서 연결 점검", default=True)
    notify_summary = models.BooleanField("하루 한 번 요약", default=True)
    channel = models.CharField("알림 받을 곳", max_length=10, choices=CHANNELS, default="telegram")

    class Meta:
        verbose_name = verbose_name_plural = "알림 설정"

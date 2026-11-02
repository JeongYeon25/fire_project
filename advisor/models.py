from django.conf import settings
from django.db import models
from django.utils import timezone


class ChatMessage(models.Model):
    """화분별 상담 대화 한 줄. 사용자가 지울 때까지 보관한다(지우기는 화분별 대화 전체)."""

    USER, ASSISTANT = "user", "assistant"
    ROLES = [(USER, "사용자"), (ASSISTANT, "AI")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages", verbose_name="주인")
    plant = models.ForeignKey("plants.Plant", on_delete=models.CASCADE, related_name="chat_messages", verbose_name="화분")
    role = models.CharField("역할", max_length=10, choices=ROLES)
    content = models.TextField("내용")
    # 답을 받지 못해 대신 넣은 안내 문구. 다음 질문 때 AI에게 보내지 않는다.
    is_error = models.BooleanField("오류 안내", default=False)
    created_at = models.DateTimeField("시각", default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["plant", "created_at"])]
        verbose_name = verbose_name_plural = "상담 대화"

    def __str__(self):
        return f"{self.plant} · {self.get_role_display()} · {timezone.localtime(self.created_at):%m-%d %H:%M}"


class ChatUsage(models.Model):
    """하루(서울 날짜) 질문 수. 대화를 지워도 줄지 않는다(한도용). 한도가 꺼져 있어도 센다."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_usage", verbose_name="주인")
    date = models.DateField("날짜")
    count = models.PositiveIntegerField("질문 수", default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "date"], name="unique_chat_usage_owner_date")]
        verbose_name = verbose_name_plural = "상담 질문 수"

    def __str__(self):
        return f"{self.owner} {self.date} {self.count}회"

import hashlib
import hmac
import re
import secrets
import string
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

# 이름 입력칸에 보여 줄 작물별 예시 (고추·대파는 선택 목록에서 빠졌지만 예전 화분용으로 남겨 둔다)
CROP_NAME_EXAMPLES = {
    "strawberry": "딸랑이",
    "tomato": "토토",
    "basil": "바질이",
    "kidney-bean": "콩콩이",
    "sunflower": "해바",
    "lettuce": "추추",
    "balsam": "봉봉",
    "pepper": "고추장",
    "green-onion": "파송이",
}

# 화분 이름 최대 글자 수(입력 검사). DB 칸은 여유 있게 30자.
PLANT_NAME_MAX = 12

# 화분 구분 색. A~D 이후 슬롯은 순서대로 다시 돌려 쓴다.
SLOT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

def generate_invite_code():
    """예전 마이그레이션(0001_initial)이 참조해서 남겨 둔다. 지금 코드에서는 쓰지 않는다."""
    return secrets.token_hex(3).upper()


def generate_api_key():
    return secrets.token_urlsafe(24)


class Crop(models.Model):
    """작물 기준값. 수업 실험 후 보정 필요."""

    name = models.CharField("이름", max_length=20, unique=True)
    slug = models.SlugField(unique=True)
    difficulty = models.CharField("난이도", max_length=10)
    water = models.CharField("물", max_length=20)
    sun = models.CharField("햇빛", max_length=30)
    water_threshold = models.FloatField("물주기 기준(토양수분 %)")
    moisture_min = models.FloatField("적정 토양수분 최소")
    moisture_max = models.FloatField("적정 토양수분 최대")
    light_threshold = models.FloatField("낮 최고 조도 기준(klux)")
    temp_min = models.FloatField("적정 온도 최소")
    temp_max = models.FloatField("적정 온도 최대")
    humidity_min = models.FloatField("적정 습도 최소", default=40)
    humidity_max = models.FloatField("적정 습도 최대", default=70)
    color = models.CharField("색", max_length=7)
    order = models.PositiveSmallIntegerField(default=0)
    # False면 새로 고르는 목록에서 빠진다. 이미 그 작물로 등록된 화분은 그대로 쓴다(고추·대파).
    is_active = models.BooleanField("선택 가능", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = verbose_name_plural = "작물"

    def __str__(self):
        return self.name

    @property
    def name_example(self):
        return CROP_NAME_EXAMPLES.get(self.slug, "")


def selectable_crops(include=None):
    """새로 고를 수 있는 작물. include(작물 id)를 주면 비활성이어도 함께 넣는다(지금 화분의 작물)."""
    query = models.Q(is_active=True)
    if include:
        query |= models.Q(pk=include)
    return Crop.objects.filter(query)


def next_slot(owner):
    """그 사용자의 화분에서 아직 쓰지 않은 자리(A~Z). 다 찼으면 None."""
    used = set(Plant.objects.filter(owner=owner).values_list("slot", flat=True))
    for letter in string.ascii_uppercase:
        if letter not in used:
            return letter
    return None


class Plant(models.Model):
    # 계정을 지우면 그 사람의 화분과 센서값·사진·알림이 함께 지워진다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plants", verbose_name="주인")
    slot = models.CharField("화분 ID", max_length=2)
    name = models.CharField("이름", max_length=30, blank=True)
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="plants")
    condition = models.CharField("화분 조건", max_length=40, blank=True)
    api_key = models.CharField("센서 API 키", max_length=64, unique=True, default=generate_api_key)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["owner", "slot"]
        constraints = [models.UniqueConstraint(fields=["owner", "slot"], name="unique_plant_owner_slot")]
        verbose_name = verbose_name_plural = "화분"

    def __str__(self):
        return f"{self.owner} · {self.title}"

    @property
    def slot_label(self):
        return f"{self.slot} 화분"

    @property
    def short_name(self):
        """카드·팝업처럼 자리 태그를 따로 붙이는 곳에서 쓰는 이름. 이름이 없으면 "A 화분"."""
        return self.name or self.slot_label

    @cached_property
    def title(self):
        """이름만 보이는 곳(범례, 칩, 알림, 다이어리, 할 일)에서 쓰는 이름.
        내 화분 중에 같은 이름이 있으면 "토토 (B)"처럼 자리를 붙인다."""
        if not self.name:
            return self.slot_label
        duplicated = Plant.objects.filter(owner_id=self.owner_id, name=self.name).exclude(pk=self.pk).exists()
        return f"{self.name} ({self.slot})" if duplicated else self.name

    def reissue_api_key(self):
        """새 키로 바꾼다. 이전 키는 바로 쓸 수 없게 된다."""
        self.api_key = generate_api_key()
        self.save(update_fields=["api_key"])
        return self.api_key

    @property
    def color(self):
        index = ord(self.slot[0]) - ord("A") if self.slot else 0
        return SLOT_COLORS[index % len(SLOT_COLORS)]

    @property
    def day_number(self):
        """키우기 시작한 날을 1일차로 센다."""
        start = timezone.localdate(self.created_at)
        return (timezone.localdate() - start).days + 1


DEVICE_NAME_MAX = 20
DEVICE_KEY_PREFIX_LEN = 6


def hash_device_key(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_device_id(name):
    """이름의 영문·숫자 부분 + "-" + 난수 4자리(영문·숫자가 없으면 "dev-"). 보관한 기기 ID와도 겹치지 않는다."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30].strip("-") or "dev"
    while True:
        device_id = f"{base}-{secrets.token_hex(2)}"
        if not SensorDevice.objects.filter(device_id=device_id).exists():
            return device_id


class SensorDevice(models.Model):
    """하드웨어 센서 기기(라즈베리파이 등).

    기기 키는 원문을 저장하지 않고 SHA-256 해시(key_hash)와 화면 표시용 앞 6글자만 둔다.
    원문은 발급·재발급 직후 화면(또는 setup_device 출력)에 한 번만 나온다.
    보관(archived_at)한 기기는 키가 지워져 수신을 받지 않고 목록에서 숨지만, 원시값·화분 값은 그대로 남는다.
    """

    device_id = models.CharField("기기 ID", max_length=40, unique=True)
    name = models.CharField("이름", max_length=DEVICE_NAME_MAX, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices", verbose_name="주인")
    # 키가 없는 기기(발급 전·보관)는 NULL — 고유 제약이 NULL 여러 개를 허용한다.
    key_hash = models.CharField("키 해시(SHA-256)", max_length=64, unique=True, null=True, blank=True, default=None)
    key_prefix = models.CharField("키 앞 6글자", max_length=DEVICE_KEY_PREFIX_LEN, blank=True)
    key_issued_at = models.DateTimeField("키 발급 시각", null=True, blank=True)
    # 값이 빈 행(no_data)을 포함해 마지막으로 받은 행의 측정 시각
    last_seen = models.DateTimeField("마지막 수신", null=True, blank=True)
    archived_at = models.DateTimeField("보관한 시각", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["device_id"]
        verbose_name = verbose_name_plural = "센서 기기"

    def __str__(self):
        return self.device_id

    @property
    def title(self):
        return self.name or self.device_id

    @property
    def is_archived(self):
        return self.archived_at is not None

    @property
    def has_key(self):
        return bool(self.key_hash)

    def set_key(self, raw):
        self.key_hash = hash_device_key(raw)
        self.key_prefix = raw[:DEVICE_KEY_PREFIX_LEN]
        self.key_issued_at = timezone.now()
        self.save(update_fields=["key_hash", "key_prefix", "key_issued_at"])

    def issue_key(self):
        """새 키를 만들어 해시만 저장하고 원문을 돌려준다. 이전 키는 바로 쓸 수 없게 된다."""
        raw = secrets.token_urlsafe(32)
        self.set_key(raw)
        return raw

    @classmethod
    def for_key(cls, raw):
        """요청 키와 맞는 (보관하지 않은) 기기. 없으면 None."""
        if not raw:
            return None
        digest = hash_device_key(raw)
        device = cls.objects.filter(key_hash=digest, archived_at__isnull=True).first()
        if device is None or not hmac.compare_digest(device.key_hash, digest):
            return None
        return device

    def connection_state(self, now=None):
        """"connected"(1시간 안에 수신) / "offline" / "waiting"(아직 수신 없음)."""
        if self.last_seen is None:
            return "waiting"
        now = now or timezone.now()
        if now - self.last_seen > timedelta(hours=settings.DEVICE_STALE_AFTER_HOURS):
            return "offline"
        return "connected"


class DeviceChannel(models.Model):
    """기기의 토양수분 채널(soil1~4) ↔ 화분. 조도·온도·습도는 기기 하나에 하나라서 연결된 화분 모두에 쓴다."""

    CHANNELS = [(1, "soil1"), (2, "soil2"), (3, "soil3"), (4, "soil4")]

    device = models.ForeignKey(SensorDevice, on_delete=models.CASCADE, related_name="channels", verbose_name="기기")
    channel = models.PositiveSmallIntegerField("채널", choices=CHANNELS)
    # 화분 하나는 채널 하나에만 연결한다. 관리자 화면에서 두 채널의 화분을 한 번에 맞바꿀 수 있도록
    # DB 고유 제약 대신 관리자 폼(plants/admin.py)과 clean()에서 검사한다.
    plant = models.ForeignKey(
        Plant, on_delete=models.SET_NULL, null=True, blank=True, related_name="device_channels", verbose_name="화분"
    )

    class Meta:
        ordering = ["device", "channel"]
        constraints = [models.UniqueConstraint(fields=["device", "channel"], name="unique_device_channel")]
        verbose_name = verbose_name_plural = "기기 채널"

    def __str__(self):
        return f"{self.device} soil{self.channel}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.plant_id and DeviceChannel.objects.filter(plant_id=self.plant_id).exclude(device_id=self.device_id).exists():
            raise ValidationError({"plant": "이 화분은 다른 기기의 채널에 이미 연결돼 있어요."})


class DeviceReading(models.Model):
    """기기가 보낸 원시값 한 행. 값이 빈 행(note=no_data)도 그대로 남긴다."""

    device = models.ForeignKey(SensorDevice, on_delete=models.CASCADE, related_name="readings", verbose_name="기기")
    time = models.DateTimeField("측정 시각")
    soil1 = models.IntegerField(null=True, blank=True)
    soil2 = models.IntegerField(null=True, blank=True)
    soil3 = models.IntegerField(null=True, blank=True)
    soil4 = models.IntegerField(null=True, blank=True)
    light = models.FloatField("조도(원시)", null=True, blank=True)
    temp = models.FloatField("온도(°C)", null=True, blank=True)
    hum = models.FloatField("습도(%)", null=True, blank=True)
    n_samples = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.CharField(max_length=40, blank=True)
    received_at = models.DateTimeField("받은 시각", auto_now=True)

    class Meta:
        ordering = ["-time"]
        constraints = [models.UniqueConstraint(fields=["device", "time"], name="unique_device_reading_time")]
        verbose_name = verbose_name_plural = "기기 원시값"

    def __str__(self):
        return f"{self.device} {timezone.localtime(self.time):%Y-%m-%d %H:%M:%S}"

    def soil(self, channel):
        return getattr(self, f"soil{channel}")


class SensorReading(models.Model):
    """화분의 측정값. 판정·그래프·알림은 모두 이 표를 읽는다.
    기기에서 온 값은 DeviceReading에서 계산해 넣은 것(device_reading)이라 rebuild_device_readings로 다시 만들 수 있다."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name="readings")
    measured_at = models.DateTimeField("측정 시각", default=timezone.now, db_index=True)
    moisture = models.FloatField("토양수분(%)")
    # 조도를 확인하기 전인 기기 값은 비어 있다(빛 판정 안 함).
    light = models.FloatField("조도(klux)", null=True, blank=True)
    temp = models.FloatField("온도(°C)", null=True, blank=True)
    humidity = models.FloatField("습도(%)", null=True, blank=True)
    device_reading = models.ForeignKey(
        DeviceReading, on_delete=models.CASCADE, null=True, blank=True, related_name="plant_readings", verbose_name="기기 원시값"
    )

    class Meta:
        ordering = ["-measured_at"]
        indexes = [models.Index(fields=["plant", "measured_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["plant", "device_reading"],
                condition=models.Q(device_reading__isnull=False),
                name="unique_plant_device_reading",
            )
        ]
        verbose_name = verbose_name_plural = "센서 측정값"


def photo_upload_to(instance, filename):
    return f"photos/{instance.plant.owner_id}/{instance.plant.slot}/{filename}"


class PlantPhoto(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField("사진", upload_to=photo_upload_to)
    taken_at = models.DateTimeField("촬영 시각", default=timezone.now, db_index=True)
    diagnosis = models.TextField("AI 진단", blank=True)
    recommendation = models.TextField("추천 행동", blank=True)

    class Meta:
        ordering = ["-taken_at"]
        verbose_name = verbose_name_plural = "화분 사진"

    @property
    def day_number(self):
        start = timezone.localdate(self.plant.created_at)
        return (timezone.localdate(self.taken_at) - start).days + 1

    def reading_at_time(self):
        """촬영 시각과 가장 가까운(이전) 센서 값."""
        return self.plant.readings.filter(measured_at__lte=self.taken_at).first()


TASK_TITLE_MAX = 60
# 시각을 정하지 않은 할 일의 알림 기본 시각
DEFAULT_NOTIFY_TIME = time(9, 0)


class Task(models.Model):
    """사용자가 직접 넣은 할 일. 날짜 하나에 한 번(행 하나).

    반복(매일·매주 요일)은 아직 없다. 나중에 반복 규칙 모델(TaskSeries)과 이 모델의 series 칸(비어도 됨)을
    추가해서, 규칙이 날짜마다 Task 행을 만들게 하면 된다. 체크(done_at)·알림 기록(notified_at)은 행마다 그대로 쓴다.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks", verbose_name="주인")
    plant = models.ForeignKey(
        "Plant", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks", verbose_name="화분"
    )
    title = models.CharField("할 일", max_length=TASK_TITLE_MAX)
    due_date = models.DateField("날짜")  # 서울 기준 날짜
    due_time = models.TimeField("시각", null=True, blank=True)
    notify = models.BooleanField("알림 받기", default=True)
    done_at = models.DateTimeField("완료한 시각", null=True, blank=True)
    # 챗봇이 이 할 일을 보낸 시각. 비어 있을 때만 보낸다(중복 방지). 날짜·시각을 바꾸면 다시 비운다.
    notified_at = models.DateTimeField("알림 보낸 시각", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", models.F("due_time").asc(nulls_last=True), "created_at"]
        indexes = [
            models.Index(fields=["owner", "due_date"], name="task_owner_date"),
            models.Index(fields=["notify", "notified_at", "due_date"], name="task_notify_queue"),
        ]
        verbose_name = verbose_name_plural = "할 일"

    def __str__(self):
        return f"{self.due_date} {self.title}"

    @property
    def is_done(self):
        return self.done_at is not None

    def notify_at(self):
        """알림 보낼 시각(서울). 시각이 비어 있으면 아침 9시."""
        return timezone.make_aware(datetime.combine(self.due_date, self.due_time or DEFAULT_NOTIFY_TIME))


class TodoCheck(models.Model):
    """자동 할 일(물·빛 부족)의 오늘 체크 상태."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_checks", verbose_name="주인")
    date = models.DateField()
    key = models.CharField(max_length=40)
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "date", "key"], name="unique_todo_check_owner")]
        verbose_name = verbose_name_plural = "할 일 체크"

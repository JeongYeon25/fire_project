"""센서 기기 등록: 기기 + 주인 계정 + 토마토 화분 A~D + 채널 연결(soil1=A … soil4=D).

    python manage.py setup_device pi-01 --owner 8jo

- 주인 계정이 없으면 비밀번호를 터미널에서 두 번 입력받아 만든다(화면에 보이지 않음, 코드·.env에 남기지 않음).
- 이미 등록돼 있으면 빠진 것만 채운다(다시 실행해도 같음).
- 기기 키가 없으면 새로 발급해서 터미널에 한 번만 보여 준다(DB에는 해시만). --reissue-key로 다시 발급.
- 채널 연결은 관리자 화면(센서 기기)에서 바꿀 수 있다. 바꾸면 화분 측정값을 자동으로 다시 계산한다.
"""

from getpass import getpass

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Profile
from alerts.models import UserSetting
from plants.models import DEVICE_NAME_MAX, Crop, DeviceChannel, Plant, SensorDevice

User = get_user_model()

# 채널 → (자리, 실험 조건). 하드웨어 담당자 확인 전 임시 연결.
POTS = [
    (1, "A", "정상"),
    (2, "B", "물 줄임"),
    (3, "C", "빛 줄임"),
    (4, "D", "물+빛 줄임"),
]


class Command(BaseCommand):
    help = "센서 기기를 등록하고 주인 계정의 토마토 화분 A~D를 soil1~4 채널에 연결한다."

    def add_arguments(self, parser):
        parser.add_argument("device_id", help="기기 ID (예: pi-01)")
        parser.add_argument("--owner", required=True, help="화분 주인 닉네임 (없으면 새로 만듦)")
        parser.add_argument("--crop", default="tomato", help="화분 작물 slug (기본 tomato)")
        parser.add_argument("--reissue-key", action="store_true", help="기기 키를 새로 발급(이전 키는 바로 무효)")

    def ask_password(self, username):
        for _ in range(3):
            first = getpass(f"{username} 계정 비밀번호: ")
            second = getpass("한 번 더: ")
            if first != second:
                self.stderr.write("두 비밀번호가 달라요. 다시 입력해 주세요.")
                continue
            try:
                password_validation.validate_password(first, User(username=username))
            except ValidationError as exc:
                self.stderr.write(" ".join(exc.messages))
                continue
            return first
        raise CommandError("비밀번호를 정하지 못해서 멈췄어요.")

    def handle(self, *args, **opts):
        crop = Crop.objects.filter(slug=opts["crop"]).first()
        if crop is None:
            raise CommandError(f"작물 {opts['crop']}이(가) 없어요.")
        username = opts["owner"].strip()
        owner = User.objects.filter(username__iexact=username).first()
        password = None
        if owner is None:
            self.stdout.write(f"{username} 계정이 없어요. 새로 만들게요.")
            password = self.ask_password(username)

        with transaction.atomic():
            if owner is None:
                owner = User.objects.create_user(username=username, password=password)
                self.stdout.write(f"계정 {username}을(를) 만들었어요.")
            profile, _ = Profile.objects.get_or_create(user=owner)
            if profile.onboarding_step != Profile.STEP_DONE or profile.crop_id is None:
                profile.crop = profile.crop or crop
                profile.onboarding_step = Profile.STEP_DONE
                profile.save()
            UserSetting.objects.get_or_create(user=owner)

            device, created = SensorDevice.objects.get_or_create(
                device_id=opts["device_id"], defaults={"owner": owner, "name": opts["device_id"][:DEVICE_NAME_MAX]}
            )
            if not created and device.owner_id != owner.pk:
                raise CommandError(f"기기 {device.device_id}는 이미 {device.owner} 계정에 등록돼 있어요.")
            if device.is_archived:
                raise CommandError(f"기기 {device.device_id}는 보관한 기기예요. 다른 기기 ID를 써 주세요.")
            self.stdout.write(f"기기 {device.device_id}{'를 등록했어요' if created else '는 이미 등록돼 있어요'}.")
            new_key = device.issue_key() if (opts["reissue_key"] or not device.has_key) else None

            for channel, slot, condition in POTS:
                link, _ = DeviceChannel.objects.get_or_create(device=device, channel=channel)
                if link.plant_id:
                    self.stdout.write(f"  soil{channel} → {link.plant.title} (그대로)")
                    continue
                if Plant.objects.filter(owner=owner, slot=slot).exists():
                    raise CommandError(
                        f"{username}에 이미 {slot} 화분이 있어요. 관리자 화면에서 soil{channel} 채널에 직접 연결해 주세요."
                    )
                plant = Plant.objects.create(owner=owner, slot=slot, crop=crop, condition=condition)
                link.plant = plant
                link.save(update_fields=["plant"])
                self.stdout.write(f"  soil{channel} → {plant.title} ({crop.name}, {condition}) 새로 만듦")

        # 키 원문은 DB에 없다. 여기서 한 번만 보여 준다(로그로 남기지 않는다).
        if new_key:
            self.stdout.write("")
            self.stdout.write(f"기기 키(지금 한 번만 보여 드려요): {new_key}")
            self.stdout.write("기기 설정의 X-API-Key에 넣어 주세요. 잃어버리면 --reissue-key나 내 기기 화면에서 다시 발급해요.")
        else:
            self.stdout.write(f"기기 키는 이미 있어요({device.key_prefix}…). 새로 받으려면 --reissue-key")

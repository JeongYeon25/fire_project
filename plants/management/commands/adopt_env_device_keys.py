"""예전 .env 기기 키(settings.SENSOR_DEVICE_KEYS, 예: SENSOR_KEY_PI01)를 DB에 해시로 옮긴다.

    python manage.py adopt_env_device_keys [--dry-run] [--force]

- 옮긴 뒤에는 기기가 설정을 바꾸지 않아도 같은 키로 계속 보낼 수 있고, .env 값은 지워도 된다.
- 여러 번 실행해도 같다: 이미 같은 키가 있으면 그대로 둔다.
- 기기에 다른 키가 이미 있으면(내 기기 화면에서 재발급한 경우) 덮어쓰지 않는다.
  예전 키로 되돌리려면 --force (추측하기 쉬운 키라 권하지 않음).
- 키 원문은 출력하지 않는다(앞 6글자만).
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from plants.models import DEVICE_KEY_PREFIX_LEN, SensorDevice, hash_device_key


class Command(BaseCommand):
    help = ".env의 기기 키를 DB(SensorDevice.key_hash)로 옮긴다. 여러 번 실행해도 안전하다."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 할 일만 보여 준다")
        parser.add_argument("--force", action="store_true", help="기기에 다른 키가 있어도 .env 키로 덮어쓴다")

    @transaction.atomic
    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        moved = 0
        for device_id, raw in settings.SENSOR_DEVICE_KEYS.items():
            raw = (raw or "").strip()
            prefix = raw[:DEVICE_KEY_PREFIX_LEN]
            if not raw:
                self.stdout.write(f"{device_id}: .env에 키가 없어요 — 건너뜀")
                continue
            device = SensorDevice.objects.filter(device_id=device_id).first()
            if device is None:
                self.stdout.write(f"{device_id}: 등록된 기기가 없어요 — 건너뜀")
                continue
            if device.is_archived:
                self.stdout.write(f"{device_id}: 보관한 기기예요 — 건너뜀")
                continue
            digest = hash_device_key(raw)
            if device.key_hash == digest:
                self.stdout.write(f"{device_id}: 이미 옮겼어요({prefix}…)")
                continue
            if device.key_hash and not opts["force"]:
                self.stdout.write(
                    f"{device_id}: 다른 키({device.key_prefix}…)가 이미 있어서 그대로 둬요. .env 키로 바꾸려면 --force"
                )
                continue
            other = SensorDevice.objects.filter(key_hash=digest).exclude(pk=device.pk).first()
            if other is not None:
                self.stdout.write(f"{device_id}: 같은 키를 {other.device_id}가 쓰고 있어요 — 건너뜀")
                continue
            moved += 1
            if dry:
                self.stdout.write(f"{device_id}: 옮길 예정({prefix}…)")
            else:
                device.set_key(raw)
                self.stdout.write(f"{device_id}: 옮겼어요({prefix}…). 이제 .env 값이 없어도 같은 키로 받아요.")
        if dry:
            transaction.set_rollback(True)
            self.stdout.write(f"확인만 했어요(옮길 기기 {moved}대).")
        else:
            self.stdout.write(f"옮긴 기기 {moved}대.")

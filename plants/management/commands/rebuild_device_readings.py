"""기기 원시값으로 화분 측정값을 다시 만든다.

보정값(SOIL_CALIBRATION), 채널 연결, LIGHT_LUX_SINCE를 바꾼 뒤 실행한다. 알림은 만들지 않는다.

    python manage.py rebuild_device_readings --device pi-01
"""

from django.core.management.base import BaseCommand, CommandError

from plants.devices import rebuild_device
from plants.models import DeviceChannel, SensorDevice, SensorReading


class Command(BaseCommand):
    help = "기기 원시값(DeviceReading)으로 화분 측정값(SensorReading)을 다시 계산한다."

    def add_arguments(self, parser):
        parser.add_argument("--device", required=True, help="기기 ID (예: pi-01)")

    def handle(self, *args, **opts):
        device = SensorDevice.objects.filter(device_id=opts["device"]).first()
        if device is None:
            raise CommandError(f"기기 {opts['device']}가 없어요.")
        if device.is_archived:
            raise CommandError(f"기기 {device.device_id}는 보관한 기기라 다시 계산하지 않아요(남겨 둔 화분 값이 지워져요).")
        before = SensorReading.objects.filter(device_reading__device=device).count()
        made = rebuild_device(device)
        self.stdout.write(f"기기 {device.device_id}: 화분 측정값 {before}행 → {made}행")
        for ch in DeviceChannel.objects.filter(device=device).select_related("plant"):
            name = ch.plant.title if ch.plant else "연결 안 됨"
            count = SensorReading.objects.filter(device_reading__device=device, plant=ch.plant).count() if ch.plant else 0
            self.stdout.write(f"  soil{ch.channel} → {name}: {count}행")

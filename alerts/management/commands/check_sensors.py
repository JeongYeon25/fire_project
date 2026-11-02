from django.core.management.base import BaseCommand
from django.utils import timezone

from alerts.services import check_sensor
from plants.models import Plant


class Command(BaseCommand):
    help = "모든 화분의 마지막 측정 시각을 확인해 24시간이 지났으면 센서 연결 점검 알림을 만든다."

    def handle(self, *args, **options):
        now = timezone.now()
        created = []
        plants = Plant.objects.select_related("owner")
        for plant in plants:
            alert = check_sensor(plant, now)
            if alert is not None:
                created.append(alert)
        for alert in created:
            self.stdout.write(f"  {alert.plant}: {alert.message}")
        self.stdout.write(self.style.SUCCESS(f"화분 {plants.count()}개 확인, 센서 점검 알림 {len(created)}개 만듦"))

"""기기 CSV 가져오기.

    python manage.py import_sensor_csv sample_data --device pi-01 [--since 2026-10-12T08:15:00] [--dry-run]

CSV 열: time,soil1,soil2,soil3,soil4,light,temp,hum,n_samples,note (time은 시간대 없는 서울 시각)
- 같은 시각이 이미 있으면 덮어써서, 몇 번을 실행해도 결과가 같다.
- 지난 값이라 알림은 만들지 않는다.
- --dry-run: 끝까지 실행한 뒤 되돌린다(숫자만 확인).
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from plants.devices import RowError, SaveResult, parse_time, save_rows
from plants.models import SensorDevice

COLUMNS = ["time", "soil1", "soil2", "soil3", "soil4", "light", "temp", "hum", "n_samples", "note"]


class DryRun(Exception):
    pass


def csv_files(path):
    path = Path(path)
    if path.is_dir():
        return sorted(path.glob("*.csv"))
    if path.is_file():
        return [path]
    raise CommandError(f"파일이나 폴더가 없어요: {path}")


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CommandError(f"{path.name}: 열이 없어요: {', '.join(missing)}")
        return [(f"{path.name}:{reader.line_num}", row) for row in reader]


def fmt(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else "–"


class Command(BaseCommand):
    help = "기기 CSV(sample_data 형식)를 가져온다. 같은 시각은 덮어쓰고, 알림은 만들지 않는다."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="CSV 파일 또는 폴더")
        parser.add_argument("--device", required=True, help="기기 ID (예: pi-01)")
        parser.add_argument("--since", help="이 시각(서울) 이전 행은 건너뛴다. 예: 2026-10-12T08:15:00")
        parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 숫자만 확인")

    def handle(self, *args, **opts):
        device = SensorDevice.objects.filter(device_id=opts["device"]).first()
        if device is None:
            raise CommandError(f"기기 {opts['device']}가 없어요. 먼저 setup_device로 만들어 주세요.")
        if device.is_archived:
            raise CommandError(f"기기 {device.device_id}는 보관한 기기예요.")
        since = None
        if opts["since"]:
            try:
                since = parse_time(opts["since"])
            except RowError as exc:
                raise CommandError(f"--since: {exc}") from None
        files = [f for p in opts["paths"] for f in csv_files(p)]
        if not files:
            raise CommandError("CSV 파일이 없어요.")

        total = SaveResult()
        try:
            with transaction.atomic():
                for path in files:
                    result = save_rows(device, read_rows(path), since=since)
                    total.merge(result)
                    self.stdout.write(
                        f"{path.name}: {result.received}행 · 새로 {result.created} · 덮어씀 {result.updated}"
                        f" · 값 없음(no_data) {result.no_data} · since 이전 {result.before_since}"
                        f" · 잘못된 행 {len(result.errors)} · 화분 값 {result.plant_rows}"
                    )
                if opts["dry_run"]:
                    raise DryRun
        except DryRun:
            pass

        w = self.stdout.write
        w("")
        w(f"{'[dry-run] 저장하지 않음 — ' if opts['dry_run'] else ''}기기 {device.device_id} · 파일 {len(files)}개")
        w(f"  읽은 행 {total.received}")
        w(f"  저장 {total.saved} (새로 {total.created}, 덮어씀 {total.updated}), 그중 값 없음(no_data) {total.no_data}")
        w(f"  건너뜀: since 이전 {total.before_since}, 잘못된 행 {len(total.errors)}, 같은 시각 중복 {total.duplicates}")
        w(f"  화분 측정값(계산) {total.plant_rows}")
        w(f"  기간 {fmt(total.first)} ~ {fmt(total.last)}")
        for where, reason in total.errors[:20]:
            w(f"  - {where}: {reason}")
        if len(total.errors) > 20:
            w(f"  … 잘못된 행 {len(total.errors) - 20}개 더")

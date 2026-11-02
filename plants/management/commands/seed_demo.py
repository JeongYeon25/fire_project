"""센서 연결 전 개발용 데모 데이터.

데모 계정 demo / demo1234!, 토마토 화분 A~D(토토, 토순, 토리, 토돌).
14일(336시간) 1시간 간격 측정값을 만들고, 8일차 0시부터 B/C/D 실험 조건을 바꾼다.
데모 데이터는 is_demo로 구분한다. 다시 실행하면 demo 계정(과 그 화분·센서값·사진·다이어리·알림)을
지우고 새로 만들어서, 몇 번을 실행해도 같은 결과(개수·이름·값)가 된다.
"""

import math
import random
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog, UserSetting
from alerts.services import process_reading
from diary.models import DiaryEntry
from plants.models import Crop, Plant, SensorReading

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234!"
HOURS = 336
CHANGE_DAY = 8

POTS = [
    # slot, 이름, 조건, 물 줄임, 햇빛 줄임
    ("A", "토토", "정상 관리", False, False),
    ("B", "토순", "물 줄임", True, False),
    ("C", "토리", "햇빛 줄임", False, True),
    ("D", "토돌", "물+햇빛 줄임", True, True),
]

MANUAL_DIARY = [
    # 일차, 시, 화분(None=전체), 내용
    (1, 10, None, "토마토 모종 4개를 심고 토토, 토순, 토리, 토돌이라고 이름을 지었어요. 센서도 모두 연결했어요!"),
    (3, 18, "A", "토토에게 새 잎이 하나 더 나왔어요."),
    (5, 13, None, "네 화분 모두 키가 비슷하게 자라고 있어요."),
    (10, 17, "B", "토순이 흙 위쪽이 바싹 말랐어요. 실험 조건이라 물은 조금만 줬어요."),
    (11, 12, "C", "토리 줄기가 창 쪽으로 기울어졌어요."),
    (13, 16, "D", "토돌이 잎 끝이 노랗게 변하기 시작했어요."),
]


class Command(BaseCommand):
    help = "센서 연결 전 개발용 데모 데이터(화분 4개, 14일치 측정값, 다이어리, 알림)를 만든다."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42, help="난수 시드 (기본 42)")

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        if not Crop.objects.exists():
            call_command("loaddata", "crops", verbosity=0)
        tomato = Crop.objects.get(slug="tomato")

        User = get_user_model()
        # demo 계정을 지우면 화분·센서값·사진·알림·다이어리·할 일 체크가 함께 지워진다(CASCADE).
        User.objects.filter(username=DEMO_USERNAME).delete()

        now = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=HOURS - 1)
        day1 = start.date()
        tz = timezone.get_current_timezone()
        change_at = timezone.make_aware(datetime.combine(day1 + timedelta(days=CHANGE_DAY - 1), time.min), tz)

        user = User.objects.create_user(username=DEMO_USERNAME, password=DEMO_PASSWORD)
        Profile.objects.create(
            user=user, crop=tomato, onboarding_step=Profile.STEP_DONE, condition_changed_at=change_at,
            intro_seen_at=timezone.now(),  # 데모 계정은 사용 안내를 건너뛴다
        )
        UserSetting.objects.create(user=user)

        plants = {}
        for slot, name, condition, _, _ in POTS:
            plants[slot] = Plant.objects.create(
                owner=user, slot=slot, name=name, crop=tomato, condition=condition, is_demo=True
            )
        Plant.objects.filter(owner=user).update(created_at=start)

        # 날씨(구름)는 네 화분이 같다.
        clouds = {d: rng.uniform(0.75, 1.0) for d in range(HOURS // 24 + 2)}

        readings, diary, alerts = [], [], []
        for slot, _, _, water_cut_pot, light_cut_pot in POTS:
            plant = plants[slot]
            moisture = 62.0 + rng.uniform(-2, 2)
            pending_water = 0.0
            for i in range(HOURS):
                t = start + timedelta(hours=i)
                hour = t.hour
                day = (t.date() - day1).days + 1
                after = t >= change_at
                water_cut = water_cut_pot and after
                light_cut = light_cut_pot and after

                sun = math.sin(math.pi * (hour - 6) / 13) if 6 <= hour <= 19 else 0.0
                light = 24.0 * max(sun, 0) * clouds[day - 1] * (0.25 if light_cut else 1.0)
                light = max(0.0, light + (rng.gauss(0, 0.4) if light > 0 else 0))
                daily = math.sin(2 * math.pi * (hour - 9) / 24)
                temp = 22 + 4 * daily + rng.gauss(0, 0.3) - (1.0 if light_cut else 0)
                humidity = min(95, max(25, 58 - 8 * daily + rng.gauss(0, 1.2) + (4 if light_cut else 0)))

                # 증발 + 물주기(아침 9시에 확인)
                moisture -= 0.22 + 0.025 * light + rng.uniform(0, 0.05)
                if pending_water:
                    moisture += pending_water
                    pending_water = 0.0
                if hour == 9:
                    limit, amount = (22, 12) if water_cut else (42, 30)
                    if moisture < limit:
                        before = moisture
                        first = amount * 0.7
                        moisture += first
                        pending_water = amount - first
                        diary.append(
                            DiaryEntry(
                                owner=user, plant=plant, is_auto=True, created_at=t,
                                content=f"{plant.name}에게 물을 줬어요. 토양수분 {before:.0f}% → {min(before + amount, 72):.0f}%",
                            )
                        )
                moisture = max(5.0, min(72.0, moisture))

                readings.append(
                    SensorReading(
                        plant=plant, measured_at=t, moisture=round(moisture, 1), light=round(light, 2),
                        temp=round(temp, 1), humidity=round(humidity, 1),
                    )
                )

        SensorReading.objects.bulk_create(readings, batch_size=500)

        # 알림은 실제 수신 API와 같은 규칙으로, 측정 시각 순서대로 만든다.
        readings.sort(key=lambda r: r.measured_at)
        auto_alerts = 0
        for reading in readings:
            auto_alerts += len(process_reading(reading))

        # 하루 요약 알림(최근 3일 아침 9시)
        for back in range(3):
            t = (now - timedelta(days=back)).replace(hour=9)
            if t > now or t < start:
                continue
            problems = []  # (이름, 문제)
            for plant in plants.values():
                r = next(x for x in reversed(readings) if x.plant is plant and x.measured_at <= t)
                if r.moisture < tomato.water_threshold:
                    problems.append((plant.name, "물 부족"))
            for slot in ("C", "D"):
                if t >= change_at + timedelta(days=1):
                    problems.append((plants[slot].name, "빛 부족"))
            detail = ", ".join(f"{name} {what}" for name, what in problems)
            text = f"오늘의 요약: 돌봐 줄 화분 {len({name for name, _ in problems})}개" + (f" ({detail})" if problems else "")
            alerts.append(AlertLog(plant=plants["A"], kind="summary", sent_at=t, is_demo=True, message=text))

        diary.append(
            DiaryEntry(owner=user, is_auto=True, created_at=change_at + timedelta(hours=9),
                       content="실험 조건을 바꿨어요. 토순(B) 물 줄임, 토리(C) 햇빛 줄임, 토돌(D) 물+햇빛 줄임.")
        )
        for day, hour, slot, content in MANUAL_DIARY:
            t = timezone.make_aware(datetime.combine(day1 + timedelta(days=day - 1), time(hour)), tz)
            if t <= now:
                diary.append(DiaryEntry(owner=user, plant=plants.get(slot), content=content, created_at=t))
        diary = [d for d in diary if d.created_at <= now]
        DiaryEntry.objects.bulk_create(diary)
        AlertLog.objects.bulk_create(alerts)

        if options["verbosity"] < 1:
            return
        from plants.services import plant_status

        summary = ", ".join(f"{s} {plant_status(p).state}" for s, p in plants.items())
        self.stdout.write(self.style.SUCCESS(
            f"데모 데이터를 만들었어요: 측정값 {len(readings)}개, 다이어리 {len(diary)}개, 알림 {auto_alerts + len(alerts)}개\n"
            f"지금 상태: {summary}\n"
            f"로그인: {DEMO_USERNAME} / {DEMO_PASSWORD}"
        ))
        self.stdout.write("데모 화분 센서 API 키 (센서 테스트용, 다시 실행하면 바뀌어요):")
        for slot, plant in plants.items():
            self.stdout.write(f"  {slot}: {plant.api_key}")

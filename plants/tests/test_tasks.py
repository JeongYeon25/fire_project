import json
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from plants import tasks as task_service
from plants.models import Crop, Plant, Task

User = get_user_model()


def seoul(y, m, d, hh=12, mm=0, ss=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm, ss))


def make_user(name="새싹"):
    user = User.objects.create_user(name, password="plant-pass-77")
    Profile.objects.create(
        user=user, crop=Crop.objects.get(slug="tomato"), onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now()
    )
    return user


class TaskDateTests(TestCase):
    """날짜 계산(서울 기준)."""

    fixtures = ["crops"]

    def setUp(self):
        self.user = make_user()

    def add(self, d, title="물 주기", **kw):
        return Task.objects.create(owner=self.user, title=title, due_date=d, **kw)

    def test_today_future_past(self):
        now = seoul(2026, 10, 20, 15)
        past = self.add(date(2026, 10, 19), "어제 할 일")
        today = self.add(date(2026, 10, 20), "오늘 할 일")
        future = self.add(date(2026, 10, 22), "모레 할 일")
        self.assertEqual(list(task_service.overdue(self.user, now)), [past])
        self.assertEqual(list(task_service.due_today(self.user, now)), [today])
        self.assertEqual(list(task_service.upcoming(self.user, now)), [future])

    def test_done_past_task_is_not_overdue(self):
        now = seoul(2026, 10, 20, 15)
        self.add(date(2026, 10, 19), done_at=now - timedelta(hours=20))
        self.assertFalse(task_service.overdue(self.user, now).exists())
        self.assertEqual(task_service.recently_done(self.user, now).count(), 1)

    def test_midnight_boundary_seoul(self):
        self.add(date(2026, 10, 20))
        before = seoul(2026, 10, 20, 23, 59, 59)
        after = seoul(2026, 10, 21, 0, 0, 0)
        self.assertEqual(task_service.today(before), date(2026, 10, 20))
        self.assertEqual(task_service.due_today(self.user, before).count(), 1)
        self.assertEqual(task_service.today(after), date(2026, 10, 21))
        self.assertEqual(task_service.due_today(self.user, after).count(), 0)
        self.assertEqual(task_service.overdue(self.user, after).count(), 1)

    def test_utc_and_seoul_dates_differ(self):
        # UTC 10-19 15:30 = 서울 10-20 00:30 → 오늘은 20일
        now = datetime(2026, 10, 19, 15, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(task_service.today(now), date(2026, 10, 20))
        self.add(date(2026, 10, 20))
        self.assertEqual(task_service.due_today(self.user, now).count(), 1)

    def test_upcoming_grouped_by_date(self):
        now = seoul(2026, 10, 20)
        a = self.add(date(2026, 10, 22), "분갈이")
        b = self.add(date(2026, 10, 22), "물 주기", due_time=time(8))
        c = self.add(date(2026, 10, 25), "비료")
        groups = task_service.group_upcoming_by_date(task_service.upcoming(self.user, now))
        self.assertEqual(groups, [(date(2026, 10, 22), [b, a]), (date(2026, 10, 25), [c])])  # 시각 있는 것 먼저

    def test_other_users_tasks_hidden(self):
        other = make_user("친구")
        Task.objects.create(owner=other, title="남의 할 일", due_date=date(2026, 10, 20))
        self.assertFalse(task_service.due_today(self.user, seoul(2026, 10, 20)).exists())


class TaskNotificationTests(TestCase):
    """챗봇용 조회(챗봇은 아직 없음)."""

    fixtures = ["crops"]

    def setUp(self):
        self.user = make_user()
        self.now = seoul(2026, 10, 20, 7)
        d = date(2026, 10, 20)
        self.at10 = Task.objects.create(owner=self.user, title="10시", due_date=d, due_time=time(10))
        self.no_time = Task.objects.create(owner=self.user, title="시각 없음", due_date=d)  # 09:00으로 친다
        self.at8 = Task.objects.create(owner=self.user, title="8시", due_date=d, due_time=time(8))
        Task.objects.create(owner=self.user, title="알림 끔", due_date=d, notify=False)
        Task.objects.create(owner=self.user, title="끝남", due_date=d, done_at=self.now)
        Task.objects.create(owner=self.user, title="내일", due_date=d + timedelta(days=1))

    def test_order_and_default_nine(self):
        due = task_service.tasks_due_for_notification(self.now)
        self.assertEqual([t.title for t in due], ["8시", "시각 없음", "10시"])
        self.assertEqual(timezone.localtime(self.no_time.notify_at()).time(), time(9, 0))

    def test_mark_notified_once(self):
        self.assertTrue(task_service.mark_notified(self.at8, self.now))
        self.assertFalse(task_service.mark_notified(self.at8, self.now))
        self.assertNotIn(self.at8, task_service.tasks_due_for_notification(self.now))


class TaskViewTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_add_edit_check_delete(self):
        plant = Plant.objects.create(owner=self.user, slot="A", name="토토", crop=Crop.objects.get(slug="tomato"))
        res = self.client.post(
            "/tasks/add/",
            {"title": "  분갈이  ", "due_date": self.today.isoformat(), "due_time": "", "plant": plant.pk, "notify": "on", "next": "home"},
        )
        self.assertRedirects(res, "/home/")
        task = Task.objects.get()
        self.assertEqual((task.title, task.due_date, task.due_time, task.plant, task.notify), ("분갈이", self.today, None, plant, True))
        self.assertContains(self.client.get("/home/"), "분갈이")

        self.client.post(f"/tasks/{task.pk}/edit/", {"title": "분갈이하기", "due_date": self.today.isoformat(), "due_time": "18:30"})
        task.refresh_from_db()
        self.assertEqual((task.title, task.due_time, task.notify, task.plant), ("분갈이하기", time(18, 30), False, None))

        res = self.client.post(f"/api/tasks/{task.pk}/check/", data=json.dumps({"done": True}), content_type="application/json")
        self.assertEqual(res.json(), {"id": task.pk, "done": True})
        task.refresh_from_db()
        self.assertIsNotNone(task.done_at)

        self.client.post(f"/tasks/{task.pk}/delete/")
        self.assertFalse(Task.objects.exists())

    def test_notify_default_on_and_title_required(self):
        form_page = self.client.get("/tasks/").content.decode()
        self.assertIn('name="notify" class="toggle" checked', form_page)
        self.client.post("/tasks/add/", {"title": "   ", "due_date": self.today.isoformat()})
        self.client.post("/tasks/add/", {"title": "가" * 61, "due_date": self.today.isoformat()})
        self.client.post("/tasks/add/", {"title": "물 주기", "due_date": "어제"})
        self.assertFalse(Task.objects.exists())

    def test_changing_date_or_time_clears_notified_at(self):
        sent = timezone.now()
        task = Task.objects.create(owner=self.user, title="물 주기", due_date=self.today, notified_at=sent)
        base = {"title": "물 주기", "notify": "on"}
        # 제목만 바꾸면 그대로
        self.client.post(f"/tasks/{task.pk}/edit/", {**base, "title": "물 듬뿍 주기", "due_date": self.today.isoformat()})
        task.refresh_from_db()
        self.assertEqual(task.notified_at, sent)
        # 시각을 바꾸면 비운다
        self.client.post(f"/tasks/{task.pk}/edit/", {**base, "due_date": self.today.isoformat(), "due_time": "20:00"})
        task.refresh_from_db()
        self.assertIsNone(task.notified_at)
        # 날짜를 바꿔도 비운다
        Task.objects.filter(pk=task.pk).update(notified_at=sent)
        tomorrow = self.today + timedelta(days=1)
        self.client.post(f"/tasks/{task.pk}/edit/", {**base, "due_date": tomorrow.isoformat(), "due_time": "20:00"})
        task.refresh_from_db()
        self.assertEqual(task.due_date, tomorrow)
        self.assertIsNone(task.notified_at)
        # 지난 할 일을 오늘로 옮겨도 비운다
        Task.objects.filter(pk=task.pk).update(due_date=self.today - timedelta(days=2), notified_at=sent)
        self.client.post(f"/tasks/{task.pk}/today/")
        task.refresh_from_db()
        self.assertEqual((task.due_date, task.notified_at), (self.today, None))

    def test_home_shows_today_overdue_not_future(self):
        Task.objects.create(owner=self.user, title="어제 못한 일", due_date=self.today - timedelta(days=1))
        Task.objects.create(owner=self.user, title="오늘 할 일", due_date=self.today)
        Task.objects.create(owner=self.user, title="다음 주 할 일", due_date=self.today + timedelta(days=7))
        home = self.client.get("/home/")
        self.assertContains(home, "어제 못한 일")
        self.assertContains(home, "· 지남")
        self.assertContains(home, "오늘로 옮기기")
        self.assertContains(home, "오늘 할 일")
        self.assertNotContains(home, "다음 주 할 일")
        self.assertContains(home, "예정된 할 일 1개")
        page = self.client.get("/tasks/")
        self.assertContains(page, "다음 주 할 일")
        self.assertContains(page, "지난 할 일 (1)")

    def test_empty_home_todo(self):
        home = self.client.get("/home/")
        self.assertContains(home, "할 일을 추가해 보세요")
        self.assertNotContains(home, "오늘의 사진 확인하기")

    def test_other_users_task_404(self):
        other = make_user("친구")
        task = Task.objects.create(owner=other, title="남의 할 일", due_date=self.today)
        for url in (f"/tasks/{task.pk}/edit/", f"/tasks/{task.pk}/delete/", f"/tasks/{task.pk}/today/"):
            self.assertEqual(self.client.post(url, {"title": "x", "due_date": self.today.isoformat()}).status_code, 404, url)
        self.assertEqual(self.client.get(f"/tasks/{task.pk}/panel/").status_code, 404)
        res = self.client.post(f"/api/tasks/{task.pk}/check/", data=json.dumps({"done": True}), content_type="application/json")
        self.assertEqual(res.status_code, 404)
        self.assertNotContains(self.client.get("/tasks/"), "남의 할 일")

    def test_today_follows_seoul_clock(self):
        """서울 자정이 지나면 홈의 '오늘'도 바뀐다."""
        Task.objects.create(owner=self.user, title="20일 할 일", due_date=date(2026, 10, 20))
        with mock.patch("django.utils.timezone.now", return_value=seoul(2026, 10, 20, 23, 59)):
            self.assertContains(self.client.get("/home/"), "20일 할 일")
            self.assertNotContains(self.client.get("/home/"), "· 지남")
        with mock.patch("django.utils.timezone.now", return_value=seoul(2026, 10, 21, 0, 1)):
            home = self.client.get("/home/")
            self.assertContains(home, "20일 할 일")
            self.assertContains(home, "10월 20일 · 지남")

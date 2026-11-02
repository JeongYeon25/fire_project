import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from alerts.models import AlertLog, UserSetting
from diary.models import DiaryEntry
from plants.models import Crop, Plant, PlantPhoto, SensorReading, TodoCheck

User = get_user_model()

APP_URLS = ["/home/", "/plants/", "/graph/", "/photos/", "/diary/", "/alerts/"]


def make_user(name, crop_slug="tomato"):
    """온보딩을 마친 사용자."""
    user = User.objects.create_user(name, password="plant-pass-77")
    Profile.objects.create(
        user=user, crop=Crop.objects.get(slug=crop_slug), onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now()
    )
    return user


class AccessTests(TestCase):
    def test_root_redirects_to_onboarding(self):
        res = self.client.get("/")
        self.assertRedirects(res, "/start/")

    def test_app_pages_need_login(self):
        for url in APP_URLS:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, url)
            self.assertTrue(res["Location"].startswith("/start/"), url)

    def test_onboarding_page(self):
        res = self.client.get("/start/")
        self.assertContains(res, "반려식물 관리 서비스")
        self.assertContains(res, "시작 준비")
        self.assertNotContains(res, "모임")
        self.assertNotContains(res, "초대 코드")


class OnboardingFlowTests(TestCase):
    fixtures = ["crops"]

    def test_signup_crop_name_creates_plant_a(self):
        res = self.client.post("/start/signup/", {"nickname": "새싹", "password": "plant-pass-77"})
        self.assertRedirects(res, "/start/")
        user = User.objects.get(username="새싹")
        self.assertTrue(UserSetting.objects.filter(user=user, notify_summary=True, channel="telegram").exists())

        # 온보딩 전에는 앱 화면에 못 들어간다.
        self.assertRedirects(self.client.get("/home/"), "/start/")
        self.assertContains(self.client.get("/start/"), "2단계 · 작물 선택")

        basil = Crop.objects.get(slug="basil")
        self.client.post("/start/crop/", {"crop": basil.pk})
        step3 = self.client.get("/start/")
        self.assertContains(step3, "3단계 · 이름 지어 주세요")
        self.assertContains(step3, 'placeholder="예: 바질이"')
        self.assertContains(step3, 'alt="바질 (목마름)"')  # 4칸 미리보기
        self.assertNotContains(step3, "캐릭터")

        res = self.client.post("/start/name/", {"name": "  바질이  "})
        self.assertRedirects(res, "/intro/")  # 처음 가입하면 사용 안내부터
        self.client.post("/intro/done/")
        plant = Plant.objects.get(owner=user)
        self.assertEqual((plant.slot, plant.crop, plant.name), ("A", basil, "바질이"))
        self.assertContains(self.client.get("/home/"), "바질이")

    def test_signup_ignores_old_group_fields(self):
        res = self.client.post(
            "/start/signup/", {"nickname": "새싹", "password": "plant-pass-77", "invite_code": "ABCDEF", "group_name": "우리 반"}
        )
        self.assertRedirects(res, "/start/")
        self.assertFalse(Profile.objects.get(user__username="새싹").onboarded)

    def test_name_step_validation(self):
        self.client.post("/start/signup/", {"nickname": "새싹", "password": "plant-pass-77"})
        self.client.post("/start/crop/", {"crop": Crop.objects.get(slug="tomato").pk})
        res = self.client.post("/start/name/", {"name": "   "})
        self.assertContains(res, "이름을 지어 주세요.")
        res = self.client.post("/start/name/", {"name": "가" * 13})
        self.assertContains(res, "이름은 12자까지 지을 수 있어요.")
        self.assertFalse(Plant.objects.exists())
        self.assertRedirects(self.client.post("/start/name/", {"name": "가" * 12}), "/intro/")
        self.assertEqual(Plant.objects.get().name, "가" * 12)

    def test_name_step_needs_crop_first(self):
        self.client.post("/start/signup/", {"nickname": "새싹", "password": "plant-pass-77"})
        self.client.post("/start/name/", {"name": "토토"})
        self.assertFalse(Plant.objects.exists())
        self.assertContains(self.client.get("/start/"), "2단계 · 작물 선택")

    def test_profileless_account_starts_at_crop(self):
        """관리자처럼 프로필 없이 만들어진 계정은 작물 선택부터."""
        User.objects.create_user("관리자", password="plant-pass-77")
        self.client.login(username="관리자", password="plant-pass-77")
        self.assertContains(self.client.get("/start/"), "2단계 · 작물 선택")

    def test_login_and_logout(self):
        call_command("seed_demo", verbosity=0)
        res = self.client.post("/start/login/", {"nickname": "demo", "password": "demo1234!"})
        self.assertRedirects(res, "/start/", target_status_code=302)
        self.assertEqual(self.client.get("/home/").status_code, 200)
        self.client.post("/logout/")
        self.assertEqual(self.client.get("/home/").status_code, 302)

    def test_wrong_password(self):
        call_command("seed_demo", verbosity=0)
        res = self.client.post("/start/login/", {"nickname": "demo", "password": "nope"})
        self.assertContains(res, "닉네임 또는 비밀번호가 맞지 않아요.")


class DemoScreensTests(TestCase):
    fixtures = ["crops"]

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.user = User.objects.get(username="demo")
        self.client.force_login(self.user)
        self.my_plants = Plant.objects.filter(owner=self.user)

    def test_seed_demo_data(self):
        self.assertEqual(list(self.my_plants.values_list("slot", flat=True)), ["A", "B", "C", "D"])
        self.assertTrue(all(p.is_demo and p.crop.slug == "tomato" for p in self.my_plants))
        self.assertEqual(SensorReading.objects.filter(plant__owner=self.user).count(), 336 * 4)
        self.assertTrue(DiaryEntry.objects.filter(owner=self.user, is_auto=True).exists())
        self.assertTrue(AlertLog.objects.filter(plant__owner=self.user).exists())
        self.assertIsNotNone(self.user.profile.condition_changed_at)

    def test_seed_demo_rerun_same_result(self):
        def snapshot():
            demo = User.objects.get(username="demo")
            return {
                "users": User.objects.filter(username="demo").count(),
                "plants": list(Plant.objects.filter(owner=demo).values_list("slot", "name", "condition", "is_demo")),
                "readings": SensorReading.objects.filter(plant__owner=demo).count(),
                "moisture": sorted(SensorReading.objects.filter(plant__owner=demo).values_list("moisture", flat=True)),
                "diary": sorted(DiaryEntry.objects.filter(owner=demo).values_list("content", flat=True)),
                "alerts": sorted(AlertLog.objects.filter(plant__owner=demo).values_list("kind", "message")),
            }

        first = snapshot()
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)
        self.assertEqual(snapshot(), first)
        self.assertEqual(Plant.objects.filter(is_demo=True).count(), 4)

    def test_seed_demo_keeps_other_users(self):
        other = make_user("새싹")
        plant = Plant.objects.create(owner=other, slot="A", name="방울이", crop=Crop.objects.first())
        call_command("seed_demo", verbosity=0)
        self.assertTrue(Plant.objects.filter(pk=plant.pk, owner=other).exists())

    def test_all_pages(self):
        for url in APP_URLS:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200, url)
        res = self.client.get("/home/")
        self.assertContains(res, "안녕, demo!")
        self.assertContains(res, "토순에 물 주기")
        self.assertContains(res, "토리를 밝은 곳으로 옮기기")

    def test_no_group_or_character_words_on_screens(self):
        plant = self.my_plants.get(slot="A")
        pages = APP_URLS + [f"/plants/{plant.pk}/panel/", f"/plants/{plant.pk}/key/"]
        for url in pages:
            res = self.client.get(url)
            for word in ("캐릭터", "모임", "초대 코드"):
                self.assertNotContains(res, word, msg_prefix=url)

    def test_demo_names_shown_first(self):
        names = list(self.my_plants.values_list("name", flat=True))
        self.assertEqual(names, ["토토", "토순", "토리", "토돌"])
        graph = self.client.get("/api/graph/", {"metric": "moisture", "range": "7d"}).json()
        self.assertEqual([s["label"] for s in graph["series"]], names)
        self.assertContains(self.client.get("/plants/"), "<h2>토돌</h2>", html=False)
        self.assertContains(self.client.get("/diary/"), "토리")

    def test_plant_panel(self):
        plant = self.my_plants.get(slot="D")
        # seed_demo는 실행 시각 기준이라 시간대에 따라 막 물을 준 상태일 수 있어, 마른 측정값을 하나 더 넣는다.
        SensorReading.objects.create(plant=plant, measured_at=timezone.now(), moisture=10, light=0, temp=22, humidity=55)
        res = self.client.get(f"/plants/{plant.pk}/panel/")
        self.assertContains(res, "많이 아파요")
        self.assertContains(res, "그다음 밝은 곳으로 옮겨 주세요")
        self.assertContains(res, 'aria-label="체력 1/5"')

    def test_other_users_data_hidden(self):
        other = make_user("새싹")
        plant = Plant.objects.create(owner=other, slot="A", name="방울이", crop=Crop.objects.first())
        SensorReading.objects.create(plant=plant, moisture=10, light=1, temp=20, humidity=50)
        DiaryEntry.objects.create(owner=other, plant=plant, content="남의 일기")
        AlertLog.objects.create(plant=plant, kind="water", message="남의 알림")
        photo = PlantPhoto.objects.create(plant=plant, image="photos/x.jpg")

        for url in (f"/plants/{plant.pk}/panel/", f"/plants/{plant.pk}/key/", f"/photos/{photo.pk}/panel/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        for url in (f"/plants/{plant.pk}/edit/", f"/plants/{plant.pk}/key/reissue/", f"/photos/{photo.pk}/delete/"):
            self.assertEqual(self.client.post(url, {"crop": plant.crop_id, "name": "x"}).status_code, 404, url)
        self.assertNotContains(self.client.get("/diary/"), "남의 일기")
        self.assertNotContains(self.client.get("/alerts/"), "남의 알림")
        self.assertNotContains(self.client.get("/home/"), "방울이")
        graph = self.client.get("/api/graph/", {"metric": "moisture", "range": "all"}).json()
        self.assertNotIn("방울이", [s["label"] for s in graph["series"]])
        # 다른 사용자도 자기 화분을 A 자리로 가질 수 있다.
        self.assertEqual(plant.slot, "A")

    def test_account_delete_cascades(self):
        user_id = self.user.pk
        plant_ids = list(self.my_plants.values_list("pk", flat=True))
        self.user.delete()
        self.assertFalse(Plant.objects.filter(pk__in=plant_ids).exists())
        self.assertFalse(SensorReading.objects.filter(plant_id__in=plant_ids).exists())
        self.assertFalse(AlertLog.objects.filter(plant_id__in=plant_ids).exists())
        self.assertFalse(DiaryEntry.objects.filter(owner_id=user_id).exists())

    def test_graph_json(self):
        res = self.client.get("/api/graph/", {"metric": "moisture", "range": "all", "plants": "A,B"})
        data = res.json()
        self.assertEqual([s["slot"] for s in data["series"]], ["A", "B"])
        self.assertEqual(len(data["times"]), 336)
        self.assertEqual(len(data["series"][0]["values"]), 336)
        self.assertEqual(data["thresholds"][0]["value"], 30)
        self.assertIsNotNone(data["condition_changed_at"])  # Profile로 옮긴 조건 변경 시각

    def test_graph_ranges(self):
        week = self.client.get("/api/graph/", {"metric": "light", "range": "7d"}).json()
        self.assertLessEqual(len(week["times"]), 7 * 24 + 1)
        today = self.client.get("/api/graph/", {"metric": "temp", "range": "today"}).json()
        self.assertLessEqual(len(today["times"]), timezone.localtime().hour + 1)
        self.assertEqual(self.client.get("/api/graph/", {"metric": "bad"}).status_code, 400)

    def test_todo_check(self):
        res = self.client.post("/api/todo/", data=json.dumps({"key": "water:B", "checked": True}), content_type="application/json")
        self.assertEqual(res.json(), {"key": "water:B", "checked": True})
        self.assertTrue(TodoCheck.objects.filter(owner=self.user, key="water:B").exists())
        self.client.post("/api/todo/", data=json.dumps({"key": "water:B", "checked": True}), content_type="application/json")
        self.assertEqual(TodoCheck.objects.count(), 1)
        self.client.post("/api/todo/", data=json.dumps({"key": "water:B", "checked": False}), content_type="application/json")
        self.assertFalse(TodoCheck.objects.exists())

    def test_settings_save(self):
        res = self.client.post("/api/settings/", data=json.dumps({"field": "notify_light", "value": False}), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(UserSetting.objects.get(user=self.user).notify_light)
        res = self.client.post("/api/settings/", data=json.dumps({"field": "channel", "value": "email"}), content_type="application/json")
        self.assertEqual(UserSetting.objects.get(user=self.user).channel, "email")
        res = self.client.post("/api/settings/", data=json.dumps({"field": "user", "value": 1}), content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_diary_write(self):
        plant = self.my_plants.get(slot="C")
        res = self.client.post("/diary/", {"plant": plant.pk, "content": "잎이 연해졌어요"})
        self.assertRedirects(res, "/diary/?plant=C")
        self.assertTrue(DiaryEntry.objects.filter(owner=self.user, plant=plant, content="잎이 연해졌어요").exists())
        page = self.client.get("/diary/")
        self.assertContains(page, "내 다이어리")
        self.assertContains(page, "자동 기록")

    def test_diary_rejects_other_users_plant(self):
        other_plant = Plant.objects.create(owner=make_user("새싹"), slot="A", crop=Crop.objects.first())
        self.client.post("/diary/", {"plant": other_plant.pk, "content": "몰래 쓰기"})
        self.assertFalse(DiaryEntry.objects.filter(content="몰래 쓰기").exists())

    def test_add_and_edit_plant(self):
        lettuce = Crop.objects.get(slug="lettuce")
        self.client.post("/plants/add/", {"name": "추추", "crop": lettuce.pk, "condition": "베란다"})
        plant = self.my_plants.get(slot="E")
        self.assertEqual((plant.crop, plant.name, plant.owner), (lettuce, "추추", self.user))
        res = self.client.get(f"/plants/{plant.pk}/panel/")
        self.assertContains(res, "센서 연결 전")
        self.assertContains(res, "작물 바꾸기 / 이름 바꾸기")
        self.assertContains(res, 'alt="추추 (건강)"')
        self.client.post(
            f"/plants/{plant.pk}/edit/", {"crop": Crop.objects.get(slug="basil").pk, "name": " 바질이 ", "condition": "창가"}
        )
        plant.refresh_from_db()
        self.assertEqual((plant.crop.slug, plant.name, plant.condition), ("basil", "바질이", "창가"))

    def test_add_requires_name(self):
        tomato = Crop.objects.get(slug="tomato")
        self.client.post("/plants/add/", {"name": "  ", "crop": tomato.pk})
        self.client.post("/plants/add/", {"name": "가" * 13, "crop": tomato.pk})
        self.assertFalse(self.my_plants.filter(slot="E").exists())
        res = self.client.post("/plants/add/", {"name": "가" * 13, "crop": tomato.pk}, follow=True)
        self.assertContains(res, "이름은 12자까지 지을 수 있어요.")

    def test_edit_name_validation_keeps_old(self):
        plant = self.my_plants.get(slot="A")
        res = self.client.post(f"/plants/{plant.pk}/edit/", {"crop": plant.crop_id, "name": " "}, follow=True)
        self.assertContains(res, "이름을 지어 주세요.")
        plant.refresh_from_db()
        self.assertEqual(plant.name, "토토")

    def test_changing_crop_changes_judgement(self):
        """토양수분 25%: 토마토(기준 30%)면 목마름, 해바라기(기준 25%)로 바꾸면 건강."""
        from plants.services import plant_status

        plant = self.my_plants.get(slot="A")
        SensorReading.objects.create(plant=plant, measured_at=timezone.now(), moisture=25, light=20, temp=22, humidity=55)
        self.assertEqual(plant_status(plant).state, "thirsty")
        res = self.client.post(f"/plants/{plant.pk}/edit/", {"crop": Crop.objects.get(slug="sunflower").pk, "name": "토토"}, follow=True)
        self.assertContains(res, "토토의 작물을 해바라기로 바꿨어요.")
        plant.refresh_from_db()
        self.assertEqual(plant_status(plant).state, "ok")
        panel = self.client.get(f"/plants/{plant.pk}/panel/")
        self.assertContains(panel, "35~60%")  # 해바라기 적정 토양수분
        self.assertContains(panel, "data-example=\"해바\"")
        self.assertContains(panel, "/static/characters/sunflower_ok.png")

    def test_duplicate_names_get_slot(self):
        b = self.my_plants.get(slot="B")
        b.name = "토토"
        b.save()
        a = self.my_plants.get(slot="A")
        self.assertEqual(Plant.objects.get(pk=a.pk).title, "토토 (A)")
        self.assertEqual(Plant.objects.get(pk=b.pk).title, "토토 (B)")
        self.assertEqual(Plant.objects.get(pk=b.pk).short_name, "토토")
        self.assertContains(self.client.get("/graph/"), "토토 (B)")

    def test_same_name_other_user_not_duplicate(self):
        Plant.objects.create(owner=make_user("새싹"), slot="A", name="토토", crop=Crop.objects.first())
        self.assertEqual(Plant.objects.get(pk=self.my_plants.get(slot="A").pk).title, "토토")

    def test_register_plant_shows_key_once(self):
        lettuce = Crop.objects.get(slug="lettuce")
        res = self.client.post("/plants/add/", {"name": " 추추 ", "crop": lettuce.pk, "condition": "창가"})
        plant = self.my_plants.get(slot="E")
        self.assertRedirects(res, f"/plants/{plant.pk}/key/", fetch_redirect_response=False)
        self.assertEqual((plant.name, plant.title, plant.condition), ("추추", "추추", "창가"))

        first = self.client.get(f"/plants/{plant.pk}/key/")
        self.assertContains(first, plant.api_key)
        self.assertIn("no-cache", first["Cache-Control"])
        second = self.client.get(f"/plants/{plant.pk}/key/")
        self.assertNotContains(second, plant.api_key)
        self.assertContains(second, "키 다시 발급")
        self.assertNotContains(self.client.get(f"/plants/{plant.pk}/panel/"), plant.api_key)

        body = json.dumps({"moisture": 50, "light": 10, "temp": 20, "humidity": 50})
        res = self.client.post("/api/readings/", data=body, content_type="application/json", HTTP_X_API_KEY=plant.api_key)
        self.assertEqual(res.json()["plant"], "E")

    def test_unnamed_existing_plant_uses_slot(self):
        plant = self.my_plants.get(slot="D")
        plant.name = ""
        plant.save()
        self.assertEqual(plant.title, "D 화분")
        self.assertContains(self.client.get("/plants/"), "<h2>D 화분</h2>", html=False)

    def test_reissue_key(self):
        plant = self.my_plants.get(slot="B")
        old_key = plant.api_key
        res = self.client.post(f"/plants/{plant.pk}/key/reissue/")
        self.assertRedirects(res, f"/plants/{plant.pk}/key/", fetch_redirect_response=False)
        plant.refresh_from_db()
        self.assertNotEqual(plant.api_key, old_key)
        self.assertContains(self.client.get(f"/plants/{plant.pk}/key/"), plant.api_key)

        body = json.dumps({"moisture": 50, "light": 10, "temp": 20, "humidity": 50})
        self.assertEqual(
            self.client.post("/api/readings/", data=body, content_type="application/json", HTTP_X_API_KEY=old_key).status_code, 401
        )
        self.assertEqual(
            self.client.post("/api/readings/", data=body, content_type="application/json", HTTP_X_API_KEY=plant.api_key).status_code, 201
        )

    def test_reissue_needs_post(self):
        plant = self.my_plants.get(slot="A")
        self.assertEqual(self.client.get(f"/plants/{plant.pk}/key/reissue/").status_code, 405)

    def test_key_not_shown_for_other_plant(self):
        a, b = self.my_plants.get(slot="A"), self.my_plants.get(slot="B")
        self.client.post(f"/plants/{a.pk}/key/reissue/")
        a.refresh_from_db()
        res = self.client.get(f"/plants/{b.pk}/key/")
        self.assertNotContains(res, a.api_key)
        self.assertNotContains(res, b.api_key)

    def test_named_plant_todo_text(self):
        plant = self.my_plants.get(slot="C")
        plant.name = "방울이"
        plant.save()
        self.assertContains(self.client.get("/home/"), "방울이를 밝은 곳으로 옮기기")

    def test_onboarded_user_cannot_reenter_onboarding(self):
        self.assertRedirects(self.client.get("/start/", {"step": "crop"}), "/home/")
        self.client.post("/start/crop/", {"crop": Crop.objects.get(slug="strawberry").pk})
        self.assertEqual(Profile.objects.get(user=self.user).crop.slug, "tomato")

    def test_settings_page(self):
        res = self.client.get("/alerts/")
        self.assertContains(res, "내 식물 관리로 가기")
        self.assertContains(res, 'href="/plants/"')
        self.assertContains(res, "키우는 작물")

class CropSelectionTests(TestCase):
    """작물 7종 선택 목록과 선택 목록에서 빠진 고추·대파."""

    fixtures = ["crops"]
    ACTIVE_NAMES = ["딸기", "토마토", "바질", "강낭콩", "해바라기", "상추", "봉선화"]

    def setUp(self):
        self.user = make_user("새싹")
        self.client.force_login(self.user)

    def test_onboarding_lists_seven_crops(self):
        other = User.objects.create_user("새내기", password="plant-pass-77")
        Profile.objects.create(user=other)
        self.client.force_login(other)
        page = self.client.get("/start/").content.decode()
        for name in self.ACTIVE_NAMES:
            self.assertIn(name, page)
        self.assertNotIn("고추", page)
        self.assertNotIn("대파", page)
        order = [page.index(f"{n}</strong>") for n in self.ACTIVE_NAMES]
        self.assertEqual(order, sorted(order))
        # 첫 화면 장식도 7종
        for slug in ("strawberry", "kidney-bean", "sunflower", "balsam"):
            self.assertIn(f"/static/characters/{slug}_ok.png", page)
        res = self.client.post("/start/crop/", {"crop": Crop.objects.get(slug="pepper").pk})
        self.assertEqual(Profile.objects.get(user=other).crop, None)
        self.assertEqual(res.status_code, 302)

    def test_add_plant_lists_seven_crops_only(self):
        page = self.client.get("/plants/").content.decode()
        template = page[page.index('<template id="add-plant-template">'):]
        for name in self.ACTIVE_NAMES:
            self.assertIn(name, template)
        self.assertNotIn("고추", template)
        self.assertNotIn("대파", template)
        self.client.post("/plants/add/", {"name": "고추장", "crop": Crop.objects.get(slug="pepper").pk})
        self.assertFalse(Plant.objects.filter(owner=self.user).exists())
        self.client.post("/plants/add/", {"name": "딸랑이", "crop": Crop.objects.get(slug="strawberry").pk})
        self.assertEqual(Plant.objects.get(owner=self.user).crop.slug, "strawberry")

    def test_retired_crop_plant_still_works(self):
        pepper = Crop.objects.get(slug="pepper")
        plant = Plant.objects.create(owner=self.user, slot="A", name="고추장", crop=pepper)
        SensorReading.objects.create(plant=plant, moisture=20, light=10, temp=22, humidity=55)
        panel = self.client.get(f"/plants/{plant.pk}/panel/")
        self.assertContains(panel, "목이 말라요")  # 고추 기준(30%) 그대로
        self.assertContains(panel, 'aria-label="고추장 (목마름)"')  # 그림 파일 없음 → SVG
        # 작물 선택칸에는 지금 작물(고추)도 들어 있어 이름만 바꿔 저장할 수 있다.
        self.assertContains(panel, f'<option value="{pepper.pk}"')
        self.client.post(f"/plants/{plant.pk}/edit/", {"crop": pepper.pk, "name": "매콤이"})
        plant.refresh_from_db()
        self.assertEqual((plant.name, plant.crop.slug), ("매콤이", "pepper"))
        # 다른 화분에서는 고추를 고를 수 없다.
        other = Plant.objects.create(owner=self.user, slot="B", name="토토", crop=Crop.objects.get(slug="tomato"))
        self.assertNotContains(self.client.get(f"/plants/{other.pk}/panel/"), f'<option value="{pepper.pk}"')
        self.client.post(f"/plants/{other.pk}/edit/", {"crop": pepper.pk, "name": "토토"})
        other.refresh_from_db()
        self.assertEqual(other.crop.slug, "tomato")

    def test_new_crop_judgement(self):
        from plants.services import plant_status

        balsam = Plant.objects.create(owner=self.user, slot="A", name="봉봉", crop=Crop.objects.get(slug="balsam"))
        SensorReading.objects.create(plant=balsam, moisture=34, light=6, temp=22, humidity=55)
        self.assertEqual(plant_status(balsam).state, "thirsty")  # 봉선화 물 기준 35%, 조도 기준 5klux
        self.assertContains(self.client.get("/home/"), "/static/characters/balsam_thirsty.png")

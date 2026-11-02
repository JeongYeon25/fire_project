from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from alerts.models import UserSetting
from plants.models import Crop, Plant

User = get_user_model()


class ProfileAdminDeleteTests(TestCase):
    """관리자 화면: 프로필은 보기·수정만 되고 삭제는 막힌다. 계정(User) 삭제는 그대로 된다."""

    fixtures = ["crops"]

    def setUp(self):
        self.admin = User.objects.create_superuser("관리자", password="plant-pass-77")
        self.client.force_login(self.admin)
        self.user = User.objects.create_user("새싹", password="plant-pass-77")
        self.profile = Profile.objects.create(
            user=self.user, crop=Crop.objects.get(slug="tomato"), onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now()
        )
        UserSetting.objects.create(user=self.user)
        Plant.objects.create(owner=self.user, slot="A", name="토토", crop=Crop.objects.get(slug="tomato"))

    def test_list_has_no_delete_action(self):
        res = self.client.get("/admin/accounts/profile/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'value="delete_selected"')

    def test_bulk_delete_action_does_nothing(self):
        self.client.post(
            "/admin/accounts/profile/", {"action": "delete_selected", "_selected_action": [self.profile.pk], "post": "yes"}
        )
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk).exists())

    def test_single_delete_forbidden(self):
        url = f"/admin/accounts/profile/{self.profile.pk}/delete/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk).exists())

    def test_view_and_edit_still_work(self):
        url = f"/admin/accounts/profile/{self.profile.pk}/change/"
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, f"/admin/accounts/profile/{self.profile.pk}/delete/")  # 삭제 버튼 없음
        basil = Crop.objects.get(slug="basil")
        res = self.client.post(
            url,
            {
                "user": self.user.pk,
                "crop": basil.pk,
                "onboarding_step": Profile.STEP_DONE,
                "condition_changed_at_0": "",
                "condition_changed_at_1": "",
                "intro_seen_at_0": "2026-10-20",
                "intro_seen_at_1": "09:00:00",
            },
        )
        self.assertEqual(res.status_code, 302, getattr(res, "context", None) and res.context["adminform"].form.errors)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.crop, basil)

    def test_user_delete_still_works_and_removes_profile(self):
        url = f"/admin/auth/user/{self.user.pk}/delete/"
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "permission to delete")  # 프로필 권한 때문에 막히지 않는다
        res = self.client.post(url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Profile.objects.filter(pk=self.profile.pk).exists())
        self.assertFalse(Plant.objects.filter(owner_id=self.user.pk).exists())

    def test_user_bulk_delete_still_works(self):
        res = self.client.post(
            "/admin/auth/user/", {"action": "delete_selected", "_selected_action": [self.user.pk], "post": "yes"}
        )
        self.assertEqual(res.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Profile.objects.filter(user_id=self.user.pk).exists())


class SidebarLogoutButtonTests(TestCase):
    """사이드 메뉴 "내 정보" 박스의 닉네임 옆에 로그아웃 버튼이 있다(POST + CSRF)."""

    fixtures = ["crops"]

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.client.login(username="demo", password="demo1234!")

    def test_logout_form_sits_next_to_nickname(self):
        html = self.client.get("/home/").content.decode()
        row = html[html.index('class="side__me-row"'):]
        row = row[: row.index("</form>")]
        self.assertIn("<strong>demo</strong>", row)
        self.assertIn('action="/logout/"', row)
        self.assertIn('method="post"', row)
        self.assertIn("csrfmiddlewaretoken", row)

    def test_clicking_it_logs_out(self):
        res = self.client.post("/logout/")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get("/home/").status_code, 302)

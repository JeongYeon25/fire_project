import io
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from accounts.models import Profile
from plants.models import Crop, Plant, PlantPhoto

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix="fire_media_")


def image_file(size=(800, 600), fmt="JPEG", name="leaf.jpg", mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, (120, 200, 90) if mode == "RGB" else (120, 200, 90, 128)).save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoUploadTests(TestCase):
    fixtures = ["crops"]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        user = User.objects.create_user("새싹", password="plant-pass-77")
        Profile.objects.create(user=user, crop=Crop.objects.first(), onboarding_step=Profile.STEP_DONE, intro_seen_at=timezone.now())
        self.plant = Plant.objects.create(owner=user, slot="A", crop=Crop.objects.first())
        self.client.force_login(user)

    def upload(self, file, plant=None, taken_at=None):
        taken_at = taken_at or timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        return self.client.post(
            "/photos/upload/", {"plant": (plant or self.plant).pk, "image": file, "taken_at": taken_at}
        )

    def test_upload_resizes_long_side(self):
        res = self.upload(image_file(size=(4000, 3000)))
        self.assertRedirects(res, "/photos/?plant=A")
        photo = PlantPhoto.objects.get()
        with Image.open(photo.image.path) as img:
            self.assertEqual(img.size, (1600, 1200))
            self.assertEqual(img.format, "JPEG")
        self.assertTrue(Path(photo.image.path).is_relative_to(MEDIA))

    def test_small_image_keeps_size(self):
        self.upload(image_file(size=(640, 480), fmt="PNG", name="small.png"))
        with Image.open(PlantPhoto.objects.get().image.path) as img:
            self.assertEqual(img.size, (640, 480))

    def test_transparent_png_stays_png(self):
        self.upload(image_file(size=(2000, 1000), fmt="PNG", name="alpha.png", mode="RGBA"))
        photo = PlantPhoto.objects.get()
        self.assertTrue(photo.image.name.endswith(".png"))
        with Image.open(photo.image.path) as img:
            self.assertEqual(img.size, (1600, 800))

    def test_taken_at_saved(self):
        when = timezone.localtime() - timedelta(days=2)
        self.upload(image_file(), taken_at=when.strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(timezone.localtime(PlantPhoto.objects.get().taken_at).strftime("%m%d%H%M"), when.strftime("%m%d%H%M"))

    def test_rejects_future_time(self):
        later = timezone.localtime() + timedelta(days=1)
        self.upload(image_file(), taken_at=later.strftime("%Y-%m-%dT%H:%M"))
        self.assertFalse(PlantPhoto.objects.exists())

    def test_rejects_non_image(self):
        res = self.upload(SimpleUploadedFile("note.jpg", b"not an image", content_type="image/jpeg"))
        self.assertFalse(PlantPhoto.objects.exists())
        self.assertContains(self.client.get(res["Location"]), "사진을 올리지 못했어요")

    def test_rejects_over_5mb(self):
        buf = io.BytesIO()
        Image.new("RGB", (1500, 1200)).save(buf, "BMP")  # 약 5.4MB 실제 이미지
        big = SimpleUploadedFile("big.bmp", buf.getvalue(), content_type="image/bmp")
        self.assertGreater(big.size, 5 * 1024 * 1024)
        res = self.upload(big)
        self.assertFalse(PlantPhoto.objects.exists())
        self.assertContains(self.client.get(res["Location"]), "5MB 이하만")

    def test_rejects_other_format(self):
        buf = io.BytesIO()
        Image.new("RGB", (100, 100)).save(buf, "BMP")
        self.upload(SimpleUploadedFile("x.bmp", buf.getvalue(), content_type="image/bmp"))
        self.assertFalse(PlantPhoto.objects.exists())

    def test_rejects_other_users_plant(self):
        other = Plant.objects.create(owner=User.objects.create_user("친구"), slot="A", crop=Crop.objects.first())
        self.upload(image_file(), plant=other)
        self.assertFalse(PlantPhoto.objects.exists())

    def test_photo_shows_in_album_and_panel(self):
        self.upload(image_file())
        photo = PlantPhoto.objects.get()
        self.assertContains(self.client.get("/photos/"), "A 화분 · 1일차")  # 이름이 없으면 자리 이름
        self.assertContains(self.client.get(f"/photos/{photo.pk}/panel/"), "사진 삭제")

    def test_delete_removes_file(self):
        self.upload(image_file())
        photo = PlantPhoto.objects.get()
        path = Path(photo.image.path)
        self.assertTrue(path.exists())
        res = self.client.post(f"/photos/{photo.pk}/delete/")
        self.assertRedirects(res, "/photos/?plant=A")
        self.assertFalse(PlantPhoto.objects.exists())
        self.assertFalse(path.exists())

    def test_delete_other_users_photo_404(self):
        other = Plant.objects.create(owner=User.objects.create_user("친구"), slot="A", crop=Crop.objects.first())
        photo = PlantPhoto.objects.create(plant=other, image="photos/x.jpg")
        self.assertEqual(self.client.post(f"/photos/{photo.pk}/delete/").status_code, 404)
        self.assertTrue(PlantPhoto.objects.filter(pk=photo.pk).exists())
        self.assertEqual(self.client.get(f"/photos/{photo.pk}/delete/").status_code, 405)

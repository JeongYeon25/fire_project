import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from plants.characters import (
    ACTIVE_CROPS,
    ART,
    CROP_NAMES,
    RETIRED_CROPS,
    SPARE_STATES,
    STATES,
    clear_png_cache,
    pixel_grid,
    render_character,
)
from plants.models import Crop

CHAR_DIR = Path(settings.BASE_DIR) / "static" / "characters"


class CropImageFilesTests(SimpleTestCase):
    """실제 static/characters/ 의 그림 파일."""

    def setUp(self):
        clear_png_cache()

    def test_all_active_crops_have_four_state_pngs(self):
        for slug in ACTIVE_CROPS:
            for state in STATES:
                path = CHAR_DIR / f"{slug}_{state}.png"
                self.assertTrue(path.exists(), path)
                with Image.open(path) as img:
                    self.assertEqual((img.size, img.mode), ((320, 320), "RGBA"), path)

    def test_spare_expressions_exist_but_unused(self):
        for slug in ACTIVE_CROPS:
            for state in SPARE_STATES:
                self.assertTrue((CHAR_DIR / f"{slug}_{state}.png").exists())
        # 예비 표정은 화면 상태로 쓰지 않는다(모르는 상태는 건강 그림).
        self.assertIn("tomato_ok.png", render_character("tomato", "love"))

    def test_active_crops_render_png(self):
        for slug in ACTIVE_CROPS:
            for state in STATES:
                html = render_character(slug, state, 64, label="토토")
                self.assertTrue(html.startswith("<img"), (slug, state))
                self.assertIn(f'src="/static/characters/{slug}_{state}.png"', html)
                self.assertIn('class="crop-img"', html)
                self.assertIn('width="64" height="64"', html)

    def test_alt_text(self):
        self.assertIn('alt="토토 (목마름)"', render_character("tomato", "thirsty", label="토토"))
        self.assertIn('alt="강낭콩 (아픔)"', render_character("kidney-bean", "sick"))
        self.assertIn('alt=""', render_character("balsam", "ok", decorative=True))

    def test_retired_crops_fall_back_to_svg(self):
        for slug in RETIRED_CROPS:
            html = render_character(slug, "dark")
            self.assertTrue(html.startswith("<svg"), slug)
            self.assertIn(f'aria-label="{CROP_NAMES[slug]} (어두움)"', html)

    def test_unknown_values_fall_back(self):
        self.assertEqual(render_character("mango", "angry", decorative=True), render_character("tomato", "ok", decorative=True))


class SvgFallbackTests(SimpleTestCase):
    """PNG가 하나도 없을 때의 대체 SVG."""

    def setUp(self):
        self.empty_static = Path(tempfile.mkdtemp(prefix="fire_static_"))
        clear_png_cache()

    def tearDown(self):
        shutil.rmtree(self.empty_static, ignore_errors=True)
        clear_png_cache()

    def test_svg_when_png_missing(self):
        with override_settings(STATICFILES_DIRS=[self.empty_static]):
            html = render_character("lettuce", "thirsty", 64, label="추추")
            self.assertTrue(html.startswith("<svg"))
            self.assertIn('aria-label="추추 (목마름)"', html)
            # 새 작물(픽셀맵 없음)도 토마토 모양으로 대체하고 이름은 그 작물로 읽어 준다.
            html = render_character("sunflower", "ok")
            self.assertTrue(html.startswith("<svg"))
            self.assertIn('aria-label="해바라기 (건강)"', html)

    def test_pixel_maps_are_16x16(self):
        for slug in ART:
            for state in STATES:
                grid = pixel_grid(slug, state)
                self.assertEqual(len(grid), 16)
                self.assertTrue(all(len(row) == 16 for row in grid))


class PngOverrideTests(SimpleTestCase):
    def setUp(self):
        self.static_dir = Path(tempfile.mkdtemp(prefix="fire_static_"))
        (self.static_dir / "characters").mkdir()
        clear_png_cache()

    def tearDown(self):
        shutil.rmtree(self.static_dir, ignore_errors=True)
        clear_png_cache()

    def test_png_used_only_when_present(self):
        Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(self.static_dir / "characters" / "green-onion_sick.png")
        with override_settings(STATICFILES_DIRS=[self.static_dir]):
            self.assertIn("characters/green-onion_sick.png", render_character("green-onion", "sick"))
            self.assertTrue(render_character("green-onion", "ok").startswith("<svg"))


class CropListTests(TestCase):
    fixtures = ["crops"]

    def test_fixture_matches_lists(self):
        active = list(Crop.objects.filter(is_active=True).values_list("slug", flat=True))
        self.assertEqual(active, list(ACTIVE_CROPS))
        self.assertEqual(
            list(Crop.objects.filter(is_active=True).values_list("name", flat=True)),
            ["딸기", "토마토", "바질", "강낭콩", "해바라기", "상추", "봉선화"],
        )
        self.assertEqual(set(Crop.objects.filter(is_active=False).values_list("slug", flat=True)), set(RETIRED_CROPS))

    def test_existing_crop_thresholds_unchanged(self):
        expected = {  # 물주기 기준, 조도 기준, 적정 수분
            "tomato": (30, 8, 40, 70),
            "basil": (30, 8, 40, 65),
            "lettuce": (35, 5, 45, 75),
            "pepper": (30, 8, 40, 65),
            "green-onion": (20, 4, 30, 60),
        }
        for slug, values in expected.items():
            c = Crop.objects.get(slug=slug)
            self.assertEqual((c.water_threshold, c.light_threshold, c.moisture_min, c.moisture_max), values, slug)

    def test_name_examples(self):
        examples = {c.slug: c.name_example for c in Crop.objects.filter(is_active=True)}
        self.assertEqual(
            examples,
            {"strawberry": "딸랑이", "tomato": "토토", "basil": "바질이", "kidney-bean": "콩콩이",
             "sunflower": "해바", "lettuce": "추추", "balsam": "봉봉"},
        )

    def test_accepts_crop_object(self):
        sunflower = Crop.objects.get(slug="sunflower")
        self.assertEqual(render_character(sunflower, "dark"), render_character("sunflower", "dark"))

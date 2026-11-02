"""작물 그림 규칙 — 이 파일 한 곳에서만 정한다.

화분의 그림은 작물로 정해진다(작물 하나에 그림 하나, 상태 4가지).
static/characters/<작물 slug>_<상태>.png 가 있으면 그 PNG를 쓴다(320x320 원본을 줄여서 표시).
PNG가 없으면 대체 표시로 아래 16x16 픽셀맵 SVG를 그린다(고추·대파처럼 그림 파일이 없는 예전 작물,
또는 파일이 빠졌을 때). 템플릿에서는 {% crop_character %} 태그로 부른다.

    선택 가능: 딸기 strawberry / 토마토 tomato / 바질 basil / 강낭콩 kidney-bean / 해바라기 sunflower / 상추 lettuce / 봉선화 balsam
    선택 목록에서 빠짐(예전 화분용): 고추 pepper / 대파 green-onion
    상태 ok·thirsty·dark·sick만 쓴다. hot·happy·angry·love 파일은 예비(아직 쓰지 않음).
"""

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

STATES = ("ok", "thirsty", "dark", "sick")
STATE_WORDS = {"ok": "건강", "thirsty": "목마름", "dark": "어두움", "sick": "아픔"}

ACTIVE_CROPS = ("strawberry", "tomato", "basil", "kidney-bean", "sunflower", "lettuce", "balsam")
RETIRED_CROPS = ("pepper", "green-onion")
CROP_SLUGS = ACTIVE_CROPS + RETIRED_CROPS
CROP_NAMES = {
    "strawberry": "딸기",
    "tomato": "토마토",
    "basil": "바질",
    "kidney-bean": "강낭콩",
    "sunflower": "해바라기",
    "lettuce": "상추",
    "balsam": "봉선화",
    "pepper": "고추",
    "green-onion": "대파",
}
# 그림 파일에는 있지만 아직 화면에서 쓰지 않는 표정
SPARE_STATES = ("hot", "happy", "angry", "love")
DEFAULT_CROP = "tomato"

OUTLINE = "#3d2f3f"
EYE = "#3a2c33"

# 픽셀맵 글자: o 외곽선, b 몸, h 하이라이트, d 그늘·잎맥, l 잎, s 줄기, w 흰 몸(대파), g 연두(대파), x 뿌리
# eye_row: 얼굴 눈 높이(눈은 5·10열). droop: 목마름·아픔일 때 바꿔 끼우는 줄(잎이 처짐).
ART = {
    "tomato": {
        "grid": [
            "........s.......",
            ".......ss.......",
            ".....llllll.....",
            "....ll.ll.ll....",
            ".....oooooo.....",
            "...oobbbbbboo...",
            "..obhbbbbbbbbo..",
            ".obhbbbbbbbbbbo.",
            ".obbbbbbbbbbbbo.",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            ".obbbbbbbbbbbbo.",
            ".obbbbbbbbbbbdo.",
            "..oobbbbbbddoo..",
            "....oooooooo....",
        ],
        "droop": {
            0: "................",
            1: "........s.......",
            2: ".......ss.......",
            3: "...llllllllll...",
            4: "..l..oooooo..l..",
        },
        "eye_row": 9,
        "colors": {"b": "#ec5a45", "d": "#c23a2a", "l": "#5cbf4a", "s": "#3a8a3a"},
    },
    "lettuce": {
        "grid": [
            "................",
            "................",
            "..oo.oooooo.oo..",
            ".ollobbbbbbollo.",
            ".olldbbbbbbdllo.",
            "olllldbbbbdllllo",
            "obllldbbbbdlllbo",
            "obbllldbbdlllbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            ".obbbbbbbbbbbbo.",
            ".olbbbbbbbbbblo.",
            "..ollbbbbbblloo.",
            "...oooooooooo...",
        ],
        "droop": {
            2: "................",
            3: "..oo.oooooo.oo..",
            4: ".ollobbbbbbollo.",
            5: "olllldbbbbdllllo",
        },
        "eye_row": 9,
        "colors": {"b": "#c4e88a", "d": "#8fbf55", "l": "#7cc24f", "s": "#3a8a3a"},
    },
    "basil": {
        "grid": [
            "................",
            "......ohbo......",
            ".oo..ohbbbo..oo.",
            "ohbo.obbdbo.obbo",
            "obbboobbdbboobbo",
            "obbbbobbdbbobbbo",
            ".obbbbbbdbbbbbo.",
            ".obbbbbbdbbbbbo.",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            "obbbbbbbbbbbbbbo",
            ".obbbbbbbbbbbbo.",
            ".obbbbbbbbbbbbo.",
            "..oobbbbbbbboo..",
            "....oooooooo....",
        ],
        "droop": {
            1: "................",
            2: "................",
            3: "..oo..ohbo..oo..",
            4: ".obboobbdbboobbo",
        },
        "eye_row": 10,
        "colors": {"b": "#4caf66", "d": "#2b6e3f", "l": "#5cbf4a", "s": "#2b6e3f"},
    },
    "pepper": {
        "grid": [
            ".......ss.......",
            "........ss......",
            "....llllllll....",
            "...oolllllloo...",
            "..obhbbbbbbbbo..",
            "..obhbbbbbbbbo..",
            "..obhbbbbbbbbo..",
            "..obbbbbbbbbbo..",
            "..obbbbbbbbbbo..",
            "..obbbbbbbbbbo..",
            "..obbbbbbbbbbo..",
            "...obbbbbbbbdo..",
            "...obbbbbbbddo..",
            "....obbbbbbdo...",
            ".....obbbbdo....",
            "......oooo......",
        ],
        "droop": {
            0: "................",
            1: "........s.......",
            2: ".......ss.......",
            3: "..llolllllloll..",
        },
        "eye_row": 7,
        "colors": {"b": "#d6402f", "d": "#a82a1f", "l": "#5cbf4a", "s": "#3a8a3a"},
    },
    "green-onion": {
        "grid": [
            "....l..ll..l....",
            "....l..ll..l....",
            "....ll.ll.ll....",
            ".....llllll.....",
            ".....llllll.....",
            "....oggggggo....",
            "...owwgggwwwo...",
            "..owhwwwwwwwwo..",
            "..owhwwwwwwwwo..",
            "..owwwwwwwwwwo..",
            "..owwwwwwwwwwo..",
            "..owwwwwwwwwwo..",
            "..owwwwwwwwwwo..",
            "...owwwwwwwwo...",
            "....oooooooo....",
            "....x.x..x.x....",
        ],
        "droop": {
            0: "................",
            1: ".......ll.......",
            2: "..lll..ll..lll..",
            3: "....llllllll....",
        },
        "eye_row": 9,
        "colors": {"w": "#f7f3e8", "g": "#c9e6a5", "l": "#5cbf4a", "x": "#cdb891", "b": "#f7f3e8"},
    },
}

# 상태에 따라 색을 섞는 대상(몸·잎). 외곽선·눈·소품은 그대로.
TINTED_KEYS = ("b", "d", "l", "s", "w", "g", "x")


def _face(state, er):
    """(x, y, 색 키) 목록. er = 눈 높이. 눈은 5·10열."""
    px = []
    if state == "ok":
        px += [(5, er, "e"), (10, er, "e"), (5, er - 1, "e"), (10, er - 1, "e")]
        px += [(6, er + 2, "e"), (9, er + 2, "e"), (7, er + 3, "e"), (8, er + 3, "e")]
        px += [(3, er + 1, "c"), (12, er + 1, "c")]
    elif state == "thirsty":
        px += [(4, er - 1, "e"), (5, er, "e"), (4, er + 1, "e")]
        px += [(11, er - 1, "e"), (10, er, "e"), (11, er + 1, "e")]
        px += [(6, er + 3, "e"), (7, er + 2, "e"), (8, er + 2, "e"), (9, er + 3, "e")]
        px += [(13, er - 4, "q"), (12, er - 3, "q"), (13, er - 3, "q"), (12, er - 2, "q"), (13, er - 2, "q")]
    elif state == "dark":
        px += [(4, er, "e"), (5, er, "e"), (10, er, "e"), (11, er, "e")]
        px += [(7, er + 2, "e"), (8, er + 2, "e")]
        px += [(12, 0, "z"), (13, 0, "z"), (14, 0, "z"), (13, 1, "z"), (12, 2, "z"), (13, 2, "z"), (14, 2, "z")]
    elif state == "sick":
        for cx in (5, 10):
            px += [(cx - 1, er - 1, "e"), (cx + 1, er - 1, "e"), (cx, er, "e"), (cx - 1, er + 1, "e"), (cx + 1, er + 1, "e")]
        px += [(5, er + 3, "e"), (6, er + 2, "e"), (7, er + 3, "e"), (8, er + 2, "e")]
        px += [(9, er + 3, "t"), (10, er + 3, "t"), (11, er + 3, "t"), (12, er + 3, "r"), (13, er + 3, "r")]
    return px


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    ra, rb = _hex(a), _hex(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb))


def _palette(crop, state):
    """상태별 색: 목마름은 탁하게, 어두움은 어둡게, 아픔은 창백한 연두로."""
    base = dict(ART[crop]["colors"])
    tint = {"thirsty": ("#9a8f86", 0.4), "dark": ("#2b2140", 0.45), "sick": ("#e6f2d4", 0.6)}.get(state)
    if tint:
        for key in TINTED_KEYS:
            if key in base:
                base[key] = _mix(base[key], *tint)
    body = base.get("b", "#ffffff")
    return {
        **base,
        "o": OUTLINE,
        "h": _mix(body, "#ffffff", 0.55),
        "e": "#f3ecff" if state == "dark" and crop == "basil" else EYE,
        "c": "#ff8fa3",
        "q": "#5bb8f5",
        "z": "#6a58c8",
        "t": "#ffffff",
        "r": "#e5533d",
    }


def pixel_grid(crop, state):
    """16x16 그리드(색 키 또는 None)."""
    art = ART[crop]
    rows = list(art["grid"])
    if state in ("thirsty", "sick"):
        for index, row in art["droop"].items():
            rows[index] = row
    grid = [[None if ch == "." else ch for ch in row] for row in rows]
    for x, y, key in _face(state, art["eye_row"]):
        if 0 <= x < 16 and 0 <= y < 16:
            grid[y][x] = key
    return grid


def rects_svg(grid, palette, width, height, size, label, extra_class=""):
    """같은 색이 이어지는 가로 칸을 하나의 rect로 묶어 SVG를 만든다."""
    parts = []
    for y, row in enumerate(grid):
        x = 0
        while x < len(row):
            key = row[x]
            if key is None:
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == key:
                x += 1
            parts.append(f'<rect x="{start}" y="{y}" width="{x - start}" height="1" fill="{palette[key]}"/>')
    role = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return (
        f'<svg class="pixel-art {extra_class}" viewBox="0 0 {width} {height}" width="{size}" height="{size}" '
        f'shape-rendering="crispEdges" {role} focusable="false">{"".join(parts)}</svg>'
    )


def png_path(crop, state):
    return f"characters/{crop}_{state}.png"


# PNG 존재 여부. 운영(DEBUG=False)에서만 기억해 두고, PNG를 추가하면 서버를 다시 시작한다.
_png_cache = {}


def clear_png_cache():
    _png_cache.clear()


def _has_png(crop, state):
    key = (crop, state)
    if settings.DEBUG or key not in _png_cache:
        _png_cache[key] = finders.find(png_path(crop, state)) is not None
    return _png_cache[key]


def normalize(crop, state):
    """작물 slug(또는 Crop 객체)와 상태를 그림 규칙에 맞게 고른다. 모르는 값은 토마토·건강."""
    slug = getattr(crop, "slug", crop)
    if slug not in CROP_NAMES:
        slug = DEFAULT_CROP
    if state not in STATES:
        state = "ok"
    return slug, state


def render_character(crop, state="ok", size=64, label=None, decorative=False):
    """작물 그림 HTML. PNG가 있으면 PNG, 없으면 대체 SVG(그 작물 픽셀맵이 없으면 토마토 모양).

    label: 읽어 주는 이름(예: 화분 이름 "토토"). 없으면 작물 이름. 뒤에 상태를 붙인다.
    """
    slug, state = normalize(crop, state)
    text = "" if decorative else f"{label or CROP_NAMES[slug]} ({STATE_WORDS[state]})"
    if _has_png(slug, state):
        return format_html(
            '<img class="crop-img" src="{}" width="{}" height="{}" alt="{}" decoding="async">',
            static(png_path(slug, state)),
            size,
            size,
            text,
        )
    art = slug if slug in ART else DEFAULT_CROP
    svg = rects_svg(pixel_grid(art, state), _palette(art, state), 16, 16, size, "")
    if text:
        svg = svg.replace('aria-hidden="true"', format_html('role="img" aria-label="{}"', text), 1)
    return mark_safe(svg)

"""픽셀 소품(하트, 별, 물방울, 포션, 편지)과 메뉴 아이콘. 모두 SVG rect로 그린다."""

from django.utils.safestring import mark_safe

from .characters import OUTLINE, rects_svg

# 소품: '.' 투명, 나머지는 팔레트 키. outline=True면 1px 외곽선을 자동으로 두른다.
PROPS = {
    "heart": {
        "grid": [
            ".rr...rr.",
            "rhrr.rrrr",
            "rhrrrrrrr",
            "rrrrrrrrr",
            ".rrrrrrd.",
            "..rrrrd..",
            "...rrd...",
            "....d....",
        ],
        "palette": {"r": "#ff4d6d", "h": "#ffffff", "d": "#c9184a"},
        "outline": False,
    },
    "heart_empty": {
        "grid": [
            ".rr...rr.",
            "rhrr.rrrr",
            "rrrrrrrrr",
            "rrrrrrrrr",
            ".rrrrrrd.",
            "..rrrrd..",
            "...rrd...",
            "....d....",
        ],
        "palette": {"r": "#d3c9cc", "h": "#f1ecee", "d": "#a99fa3"},
        "outline": False,
    },
    "star": {
        "grid": [
            "....y....",
            "...yyy...",
            "yyyyhyyyy",
            ".yyyyyyy.",
            "..yyyyy..",
            "..yy.yy..",
            ".yy...yy.",
        ],
        "palette": {"y": "#ffd75e", "h": "#fff6c8"},
        "outline": True,
    },
    "drop": {
        "grid": [
            "...b...",
            "..bbb..",
            ".bbbbb.",
            "bhbbbbb",
            "bhbbbbb",
            "bbbbbbd",
            ".bbbbd.",
            "..ddd..",
        ],
        "palette": {"b": "#5bb8f5", "h": "#ffffff", "d": "#2a78d6"},
        "outline": True,
    },
    "potion_red": {
        "grid": [
            "..ccc..",
            "...g...",
            "..ggg..",
            ".gllrg.",
            "gwrrrrg",
            "grrrrrg",
            "grrrrrg",
            ".ggggg.",
        ],
        "palette": {"c": "#b7835a", "g": "#d6ecff", "l": "#ffb1b1", "r": "#ff5d5d", "w": "#ffffff"},
        "outline": True,
    },
    "potion_blue": {
        "grid": [
            "..ccc..",
            "...g...",
            "..ggg..",
            ".gllrg.",
            "gwrrrrg",
            "grrrrrg",
            "grrrrrg",
            ".ggggg.",
        ],
        "palette": {"c": "#b7835a", "g": "#e8f4ff", "l": "#a8d0ff", "r": "#4a8fdc", "w": "#ffffff"},
        "outline": True,
    },
    "envelope": {
        "grid": [
            "ppppppppp",
            "pdpppppdp",
            "ppdpppdpp",
            "pppdrdppp",
            "pppprpppp",
            "ppppppppp",
            "ppppppppp",
        ],
        "palette": {"p": "#fffdf7", "d": "#bba58a", "r": "#ff4d6d"},
        "outline": True,
    },
}

PROP_LABELS = {
    "star": "조도",
    "drop": "토양수분",
    "potion_red": "온도",
    "potion_blue": "습도",
    "envelope": "알림",
}

# 메뉴 아이콘 8x8, currentColor로 채운다.
MENU_ICONS = {
    "home": [
        "...xx...",
        "..xxxx..",
        ".xxxxxx.",
        "xxxxxxxx",
        ".x....x.",
        ".x.xx.x.",
        ".x.xx.x.",
        ".xxxxxx.",
    ],
    "plants": [
        ".xx..xx.",
        "..x..x..",
        "...xx...",
        "...x....",
        "xxxxxxxx",
        ".xxxxxx.",
        ".xxxxxx.",
        "..xxxx..",
    ],
    "graph": [
        "x.......",
        "x.....x.",
        "x....x.x",
        "x.x.x...",
        "x..x....",
        "x.......",
        "x.......",
        "xxxxxxxx",
    ],
    "photos": [
        "..xxx...",
        "xxxxxxxx",
        "x......x",
        "x..xx..x",
        "x.x..x.x",
        "x..xx..x",
        "x......x",
        "xxxxxxxx",
    ],
    "diary": [
        "xxxxxxx.",
        "x.....xx",
        "x.xxx.xx",
        "x.....xx",
        "x.xxx.xx",
        "x.....xx",
        "xxxxxxxx",
        ".xxxxxxx",
    ],
    "devices": [
        "......x.",
        ".....x..",
        "xxxxxxxx",
        "x......x",
        "x.xx.x.x",
        "x......x",
        "xxxxxxxx",
        ".x....x.",
    ],
    "alerts": [
        "...xx...",
        "..xxxx..",
        ".xxxxxx.",
        ".xxxxxx.",
        ".xxxxxx.",
        "xxxxxxxx",
        "........",
        "...xx...",
    ],
    "check": [
        "........",
        ".......x",
        "......xx",
        "x....xx.",
        "xx..xx..",
        ".xxxx...",
        "..xx....",
        "........",
    ],
}


def _with_outline(rows):
    h, w = len(rows), len(rows[0])
    grid = [[None] * (w + 2) for _ in range(h + 2)]
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                grid[y + 1][x + 1] = ch
    out = [row[:] for row in grid]
    for y in range(h + 2):
        for x in range(w + 2):
            if grid[y][x] is not None:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w + 2 and 0 <= ny < h + 2 and grid[ny][nx] is not None:
                    out[y][x] = "O"
                    break
    return out


def render_prop(name, size=24, label=None):
    spec = PROPS[name]
    rows = spec["grid"]
    palette = dict(spec["palette"], O=OUTLINE)
    if spec["outline"]:
        grid = _with_outline(rows)
    else:
        grid = [[None if ch == "." else ch for ch in row] for row in rows]
    height, width = len(grid), len(grid[0])
    if label is None:
        label = PROP_LABELS.get(name, "")
    svg = rects_svg(grid, palette, width, height, size, label, extra_class="pixel-prop")
    return mark_safe(svg)


def render_menu_icon(name, size=16):
    rows = MENU_ICONS[name]
    grid = [[None if ch == "." else ch for ch in row] for row in rows]
    return mark_safe(rects_svg(grid, {"x": "currentColor"}, 8, 8, size, "", extra_class="pixel-icon"))

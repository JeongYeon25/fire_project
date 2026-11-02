from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from plants.characters import render_character
from plants.pixels import render_menu_icon, render_prop
from plants.services import MAX_HP
from plants.text import josa as _josa

register = template.Library()


@register.simple_tag
def crop_character(crop, state="ok", size=64, label=None, decorative=False):
    """작물 그림. crop은 Crop 객체나 slug. label은 읽어 주는 이름(화분 이름), 없으면 작물 이름."""
    return render_character(crop, state, size, label=label, decorative=decorative)


@register.simple_tag
def pixel(name, size=24, label=None):
    return render_prop(name, size, label)


@register.simple_tag
def menu_icon(name, size=16):
    return render_menu_icon(name, size)


@register.simple_tag
def hp_bar(hp, size=18):
    """HP 글자 + 하트 5칸. hp가 None이면 측정값이 없는 상태."""
    if hp is None:
        return mark_safe('<span class="hp-bar" role="img" aria-label="체력 측정 전"><b class="hp-label">HP</b> <span class="hp-none">–</span></span>')
    hearts = format_html_join(
        "",
        "{}",
        ((render_prop("heart" if i < hp else "heart_empty", size, ""),) for i in range(MAX_HP)),
    )
    return format_html(
        '<span class="hp-bar" role="img" aria-label="체력 {}/{}"><b class="hp-label" aria-hidden="true">HP</b>{}</span>',
        hp,
        MAX_HP,
        hearts,
    )


@register.filter
def josa(word, pair):
    """{{ name|josa:"과,와" }} -> "토토와" / "A 화분과"."""
    with_final, without_final = pair.split(",")
    return _josa(str(word), with_final, without_final)


@register.filter
def lux_num(klux):
    """조도 klux → lux 숫자(쉼표). 값이 없으면 –."""
    if klux is None or klux == "":
        return "–"
    try:
        return f"{float(klux) * 1000:,.0f}"
    except (TypeError, ValueError):
        return "–"


@register.filter
def num(value, digits=0):
    """센서 값 표시. 값이 없으면 –. 천 단위 쉼표(조도 3,421 lux)."""
    if value is None:
        return "–"
    try:
        digits = int(digits)
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return value

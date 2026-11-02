"""센서 항목 정의와 게이지 계산.

조도는 DB·판정·작물 기준값 모두 klux로 두고, 화면에만 lux(× 1000)로 보여 준다.
"""

METRICS = {
    "moisture": {"label": "토양수분", "unit": "%", "icon": "drop", "digits": 0, "factor": 1},
    "light": {"label": "조도", "unit": "lux", "icon": "star", "digits": 0, "factor": 1000},
    "temp": {"label": "온도", "unit": "°C", "icon": "potion_red", "digits": 1, "factor": 1},
    "humidity": {"label": "습도", "unit": "%", "icon": "potion_blue", "digits": 0, "factor": 1},
}
METRIC_KEYS = list(METRICS)


def display_value(metric, value):
    """저장 단위 → 화면 단위(조도 klux → lux)."""
    if value is None:
        return None
    return value * METRICS[metric]["factor"]


def lux(klux):
    """조도 klux → "3,421 lux" 문구."""
    return f"{klux * 1000:,.0f} lux"


def _pct(value, scale):
    if value is None or scale <= 0:
        return 0
    return max(0.0, min(100.0, value / scale * 100))


def gauges(crop, latest, status):
    """상세 팝업의 칸 나뉜 게이지 4개. 조도는 판정과 같게 최근 24시간 최고값을 쓴다."""
    light_value = status.max_light_24h
    light_scale = max(30.0, (light_value or 0) * 1.15)
    if status.light_judged or status.is_waiting:
        light_note = f"낮 최고 {lux(crop.light_threshold)} 이상이면 충분해요"
    else:
        light_note = "조도 센서 단위를 확인하는 중이라 빛은 아직 판정하지 않아요"
    specs = [
        ("moisture", latest.moisture if latest else None, 100.0, crop.moisture_min, crop.moisture_max, "지금", f"적정 {crop.moisture_min:g}~{crop.moisture_max:g}% · {crop.water_threshold:g}% 아래면 물 필요"),
        ("light", light_value, light_scale, crop.light_threshold, light_scale, "최근 24시간 최고", light_note),
        ("temp", latest.temp if latest else None, 40.0, crop.temp_min, crop.temp_max, "지금", f"적정 {crop.temp_min:g}~{crop.temp_max:g}°C"),
        ("humidity", latest.humidity if latest else None, 100.0, crop.humidity_min, crop.humidity_max, "지금", f"적정 {crop.humidity_min:g}~{crop.humidity_max:g}%"),
    ]
    result = []
    for key, value, scale, lo, hi, when, note in specs:
        meta = METRICS[key]
        result.append(
            {
                "key": key,
                "label": meta["label"],
                "unit": meta["unit"],
                "icon": meta["icon"],
                "digits": meta["digits"],
                "value": display_value(key, value),
                "when": when,
                "note": note,
                "fill": round(_pct(value, scale), 1),
                "zone_left": round(_pct(lo, scale), 1),
                "zone_width": round(_pct(hi, scale) - _pct(lo, scale), 1),
                "in_zone": value is not None and lo <= value <= hi,
            }
        )
    return result

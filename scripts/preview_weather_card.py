"""生成天气卡片预览图（真实 Pillow 渲染，即运行时效果）。

用法：uv run python scripts/preview_weather_card.py [scale]
生成：_weather_preview.png（已 gitignore）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pet_ui.weather_popup import _render_card   # noqa: E402

scale = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

current = {
    "北京邮电大学 · 沙河校区": {
        "now": {"text": "阴", "temp": 22, "wind_scale": "3"},
        "tomorrow": {"date": "2026-10-23", "brief": "阴转多云",
                     "day_temp": 22, "night_temp": 14,
                     "day_delta": -3, "night_delta": 1},
        "periods": [{"start": "21:00", "end": "23:00", "text": "小雨"}],
        "strip": [{"start_h": 6, "end_h": 9, "text": "阴"},
                  {"start_h": 9, "end_h": 15, "text": "多云"},
                  {"start_h": 15, "end_h": 21, "text": "晴"},
                  {"start_h": 21, "end_h": 24, "text": "小雨"}],
    },
    "大连理工大学 · 凌水校区": {
        "now": {"text": "晴", "temp": 24, "wind_scale": "2"},
        "tomorrow": {"date": "2026-10-23", "brief": "晴",
                     "day_temp": 25, "night_temp": 17,
                     "day_delta": 1, "night_delta": -2},
        "periods": [],
        "strip": [{"start_h": 6, "end_h": 15, "text": "晴"},
                  {"start_h": 15, "end_h": 24, "text": "多云"}],
    },
}
img, _ = _render_card(current, [], scale)
img.save("_weather_preview.png")
print(f"已生成 _weather_preview.png（scale={scale}，尺寸 {img.size}）")

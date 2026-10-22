"""生成天气卡片预览图（真实 Pillow 渲染，即运行时效果）。

用法：uv run python scripts/preview_weather_card.py
生成：_weather_preview.png（已 gitignore）
"""
import os
import sys

# 允许从项目根目录导入 pet_ui
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pet_ui.weather_popup import _render_card   # noqa: E402

current = {
    "北京邮电大学 · 沙河校区": {"text": "阴转多云", "temp": 22, "wind_scale": "3"},
    "大连理工大学 · 凌水校区": {"text": "晴", "temp": 24, "wind_scale": "2"},
}
img, _ = _render_card(current, [])
img.save("_weather_preview.png")
print("已生成 _weather_preview.png")

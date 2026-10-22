"""天气播报气泡：星夜主题卡片（Pillow 渲染 + 知道了）。

设计（与 popup.py 同套路，离屏渲染成一张图，tkinter 只负责显示）：
- 深蓝夜空底 + 月牙 + 星点
- 每个校区一块玻璃卡片：现在（实况）→ 明天（概览 + 白天/夜间对比 + 时段条）
- 有降雨时额外显示「🌧 14:00–16:00 小雨」
- 底部一个按钮：知道了
- 卡片跟随桌宠移动，且始终置顶不被遮挡
- 按屏幕 DPI 缩放，保证高分屏下字号清晰、大小合适

线程安全：本模块所有方法都必须由主线程调用。
天气线程只能通过 root.after(0, ...) 调度到主线程后再调 show_weather()。
"""
import tkinter as tk
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageTk

from logger import logger

# ---------- 星夜配色 ----------
SKY_TOP = (19, 42, 92)
SKY_BOTTOM = (14, 31, 69)
MOON = (255, 246, 208)
MOON_GLOW = (255, 251, 232)
STAR = (255, 255, 255)
GLASS = (255, 255, 255)
GLASS_BORDER = (143, 176, 224)
TEXT_TITLE = (234, 240, 255)
TEXT_NAME = (169, 196, 236)
TEXT_LABEL = (143, 176, 224)
TEXT_BODY = (234, 240, 255)
TEXT_DAY = (255, 240, 184)    # 白天温度（暖金）
TEXT_NIGHT = (159, 196, 240)  # 夜间温度（浅蓝）
COL_WARMER = (240, 176, 160)  # 变暖（暖橙）
COL_COLDER = (143, 214, 160)  # 变冷（绿）
COL_RAIN = (91, 143, 214)     # 雨（蓝）
COL_RAIN_TEXT = (140, 180, 240)
BTN_GOLD = (255, 217, 138)
BTN_GOLD_TEXT = (61, 42, 0)

# 时段条各天气的底色（按"轻重"映射，纯色，避免渐变）
STRIP_COLORS = [
    (("晴",), (159, 180, 216)),
    (("多云",), (106, 127, 168)),
    (("阴",), (74, 90, 128)),
    (("雨", "雪", "雷"), (91, 143, 214)),
]

BASE_W = 400
BASE_H = 620

_FONT_PATHS = [
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
]


def _load_font(size, bold=False):
    """加载中文字体，失败退回 Pillow 默认字体。"""
    path = _FONT_PATHS[1 if bold else 0]
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(_FONT_PATHS[2], size)
        except Exception:
            return ImageFont.load_default()


def _strip_color(text):
    """按时段文字取底色。"""
    for keys, color in STRIP_COLORS:
        if any(k in text for k in keys):
            return color
    return (120, 135, 170)


def _fmt_delta(delta):
    """把温度差格式化成带箭头/颜色的文案。返回 (text, color)。"""
    if delta is None:
        return ('—', (140, 150, 175))
    if delta > 0:
        return (f'↑ 暖 {delta}°', COL_WARMER)
    if delta < 0:
        return (f'↓ 冷 {abs(delta)}°', COL_COLDER)
    return ('持平', (140, 150, 175))


def _render_card(current, changes, scale=1.0):
    """把天气数据渲染成一张星夜卡片（Pillow）。

    current: {地点名: 地点数据字典（见 weather.fetch_location）}
    changes: 突变描述列表
    scale:   DPI 缩放系数
    返回: (PIL.Image, 按钮命中区域 dict)
    """
    s = lambda v: int(round(v * scale))
    W, H = s(BASE_W), s(BASE_H)
    margin = s(26)

    img = Image.new('RGB', (W, H), SKY_BOTTOM)
    d = ImageDraw.Draw(img, 'RGBA')

    d.rectangle([0, 0, W, s(150)], fill=SKY_TOP + (150,))

    # 月牙 + 光晕
    mx, my = W - s(74), s(74)
    d.ellipse([mx - s(50), my - s(50), mx + s(50), my + s(50)],
              fill=MOON_GLOW + (26,))
    d.ellipse([mx - s(26), my - s(26), mx + s(26), my + s(26)], fill=MOON)
    d.ellipse([mx + s(12) - s(23), my - s(9) - s(23),
               mx + s(12) + s(23), my - s(9) + s(23)], fill=SKY_TOP + (255,))

    stars = [(60, 56, 2), (104, 100, 1), (48, 132, 1), (160, 46, 1),
             (212, 92, 1), (136, 148, 1), (256, 138, 1), (330, 158, 1)]
    for x, y, r in stars:
        x, y, r = s(x), s(y), max(1, s(r))
        d.ellipse([x - r, y - r, x + r, y + r], fill=STAR + (200,))

    # 标题
    f_title = _load_font(s(24), bold=True)
    title = '今 夜 天 气'
    tw = d.textlength(title, font=f_title)
    d.text(((W - tw) / 2, s(38)), title, font=f_title, fill=TEXT_TITLE)
    d.line([W // 2 - s(70), s(76), W // 2 + s(70), s(76)],
           fill=GLASS_BORDER + (90,), width=max(1, s(1)))

    f_name = _load_font(s(16))
    f_label = _load_font(s(14))
    f_body = _load_font(s(16))
    f_temp = _load_font(s(26), bold=True)
    f_delta = _load_font(s(14))
    f_strip = _load_font(s(11))
    f_rain = _load_font(s(14))

    # 每个校区一块卡片
    top = s(96)
    card_h = s(230)
    gap = s(14)
    for name, data in current.items():
        now = data.get('now', {})
        tm = data.get('tomorrow') or {}
        d.rounded_rectangle([margin, top, W - margin, top + card_h],
                            radius=s(16), fill=GLASS + (18,),
                            outline=GLASS_BORDER + (70,), width=max(1, s(1)))

        y = top + s(18)
        d.text((margin + s(20), y), name, font=f_name, fill=TEXT_NAME)
        y += s(30)

        # 现在
        d.text((margin + s(20), y), '现在', font=f_label, fill=TEXT_LABEL)
        d.text((margin + s(74), y),
               f"{now.get('text', '')}　{now.get('temp', '')}°　"
               f"风 {now.get('wind_scale', '')} 级",
               font=f_body, fill=TEXT_BODY)
        y += s(28)

        d.line([margin + s(20), y, W - margin - s(20), y],
               fill=GLASS_BORDER + (60,), width=max(1, s(1)))
        y += s(12)

        # 明天
        d.text((margin + s(20), y), '明天', font=f_label, fill=TEXT_LABEL)
        d.text((margin + s(74), y), tm.get('brief', ''), font=f_body,
               fill=TEXT_BODY)
        y += s(28)

        # 白天 / 夜间 + 对比
        if tm:
            d.text((margin + s(20), y), '白天', font=f_label, fill=TEXT_LABEL)
            d.text((margin + s(74), y - s(3)),
                   f"{tm.get('day_temp', '')}°", font=f_temp, fill=TEXT_DAY)
            dt, dc = _fmt_delta(tm.get('day_delta'))
            d.text((margin + s(120), y), dt, font=f_delta, fill=dc)
            y += s(34)

            d.text((margin + s(20), y), '夜间', font=f_label, fill=TEXT_LABEL)
            d.text((margin + s(74), y - s(3)),
                   f"{tm.get('night_temp', '')}°", font=f_temp,
                   fill=TEXT_NIGHT)
            nt, nc = _fmt_delta(tm.get('night_delta'))
            d.text((margin + s(120), y), nt, font=f_delta, fill=nc)
            y += s(30)

        # 降雨时段
        periods = data.get('periods', [])
        if periods:
            txt = '　'.join(f"{p['start']}–{p['end']} {p['text']}"
                           for p in periods)
            d.text((margin + s(20), y), '雨 ' + txt, font=f_rain,
                   fill=COL_RAIN_TEXT)
            y += s(24)

        # 时段条
        strip = data.get('strip', [])
        if strip:
            bar_y = y + s(2)
            bar_h = s(22)
            x0 = margin + s(20)
            x1 = W - margin - s(20)
            total = 18.0   # 06–24

            def _pos(h):
                """把小时映射到轴上 x 坐标，并夹在 [x0, x1] 内。"""
                t = (h - 6) / total
                t = max(0.0, min(1.0, t))
                return x0 + (x1 - x0) * t

            for r in strip:
                sx = _pos(r['start_h'])
                ex = _pos(r['end_h'])
                if ex <= sx:
                    continue   # 跳过非法/零宽段，避免 Pillow 报错
                d.rectangle([sx, bar_y, ex, bar_y + bar_h],
                            fill=_strip_color(r['text']) + (235,))
            # 刻度 06 / 12 / 18 / 24
            for hh in (6, 12, 18, 24):
                tx = _pos(hh)
                d.text((tx, bar_y + bar_h + s(2)), f"{hh:02d}", font=f_strip,
                       fill=TEXT_LABEL)

        top += card_h + gap

    # 突变提醒
    if changes:
        f_warn = _load_font(s(14))
        d.text((margin, top), '⚠ ' + '；'.join(changes), font=f_warn,
               fill=(255, 180, 120))

    # 按钮
    btn_h = s(58)
    btn_y = H - s(110)
    bx1, bx2 = margin, W - margin
    d.rounded_rectangle([bx1, btn_y, bx2, btn_y + btn_h], radius=btn_h // 2,
                        fill=BTN_GOLD)
    f_btn = _load_font(s(20), bold=True)
    text = '知道了'
    tw = d.textlength(text, font=f_btn)
    d.text(((W - tw) / 2, btn_y + s(16)), text, font=f_btn,
           fill=BTN_GOLD_TEXT)

    f_tip = _load_font(s(13))
    tip = '点「知道了」今夜不再打扰 · 天气突变仍会提醒'
    tw = d.textlength(tip, font=f_tip)
    d.text(((W - tw) / 2, H - s(40)), tip, font=f_tip,
           fill=TEXT_NAME + (217,))

    hits = {'confirm': (bx1, btn_y, bx2, btn_y + btn_h)}
    return img, hits


class WeatherMixin:
    """天气气泡：作为 Mixin 混入 PetApp。"""

    def _dpi_scale(self):
        """取屏幕 DPI 缩放系数（1.0 = 96 DPI）。"""
        try:
            return max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        except Exception:
            return 1.0

    def show_weather(self, current, changes=None):
        """显示天气卡片（必须在主线程调用）。"""
        if not current:
            return
        if getattr(self, '_weather_win', None) is not None:
            try:
                self._weather_win.destroy()
            except Exception:
                pass
            self._weather_win = None

        scale = self._dpi_scale()
        try:
            card, hits = _render_card(current, changes or [], scale)
            photo = ImageTk.PhotoImage(card)
        except Exception:
            logger.exception('天气卡片渲染失败')
            return

        cw, ch = card.size
        self._weather_w, self._weather_h = cw, ch

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.config(bg='#0E1F45')

        canvas = tk.Canvas(win, width=cw, height=ch,
                           highlightthickness=0, bd=0, bg='#0E1F45')
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas._card_img = photo

        for (x1, y1, x2, y2) in hits.values():
            canvas.create_rectangle(x1, y1, x2, y2, fill='', outline='',
                                    tags='btn_confirm')
        canvas.tag_bind('btn_confirm', '<Button-1>',
                        lambda e: self._on_weather_confirm())

        self._weather_win = win
        self._place_weather_win()
        win.deiconify()

    def _place_weather_win(self):
        """把天气卡片摆到桌宠附近，并保证不出屏幕、不被遮挡。"""
        win = getattr(self, '_weather_win', None)
        if win is None:
            return
        try:
            cw = getattr(self, '_weather_w', 0)
            ch = getattr(self, '_weather_h', 0)
            px, py = self.root.winfo_x(), self.root.winfo_y()
            x = px + self._frame_w // 2 - cw // 2
            y_up = py - ch - 10
            y = y_up if y_up >= 0 else py + self._frame_h + 10
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, min(x, sw - cw))
            y = max(0, min(y, sh - ch))
            win.geometry(f'{cw}x{ch}+{x}+{y}')
            win.attributes('-topmost', True)
            win.lift()
        except Exception:
            pass

    def _on_weather_confirm(self):
        """点「知道了」：记录当天已确认，然后关闭卡片。"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            state = getattr(self, '_weather_state', None)
            if state is not None:
                state.confirm(today)
        except Exception:
            logger.exception('确认天气失败')
        self._close_weather()

    def _close_weather(self):
        """关闭天气卡片。"""
        w = getattr(self, '_weather_win', None)
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass
        self._weather_win = None

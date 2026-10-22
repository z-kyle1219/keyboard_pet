"""天气播报气泡：星夜主题卡片（Pillow 渲染 + 知道了）。

设计（与 popup.py 同套路，离屏渲染成一张图，tkinter 只负责显示）：
- 深蓝夜空底 + 月牙 + 星点（纯色叠画，不用渐变，避免渲染差异）
- 两个校区各一块半透明玻璃卡片
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
SKY_TOP = (19, 42, 92)       # 上半天际（略亮）
SKY_BOTTOM = (14, 31, 69)    # 主夜色
MOON = (255, 246, 208)
MOON_GLOW = (255, 251, 232)
STAR = (255, 255, 255)
GLASS = (255, 255, 255)
GLASS_BORDER = (143, 176, 224)
TEXT_TITLE = (234, 240, 255)
TEXT_NAME = (169, 196, 236)
TEXT_BODY = (234, 240, 255)
TEXT_TEMP = (255, 240, 184)   # 暖金
BTN_GOLD = (255, 217, 138)
BTN_GOLD_TEXT = (61, 42, 0)

# 基准尺寸（96 DPI 下的逻辑像素；实际会乘以 DPI 缩放系数）
BASE_W = 400
BASE_H = 530

# 字体（Windows 中文）；取不到时退回默认
_FONT_PATHS = [
    r'C:\Windows\Fonts\msyh.ttc',    # 微软雅黑
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


def _render_card(current, changes, scale=1.0):
    """把天气数据渲染成一张星夜卡片（Pillow）。

    current: {地点名: {"text","temp","wind_scale","wind_dir"}}
    changes: 突变描述列表（非空时在底部加一行提醒）
    scale:   DPI 缩放系数（1.0 = 96 DPI；高分屏传实际倍率）
    返回: (PIL.Image, 按钮命中区域 dict)
    """
    # 所有尺寸按 scale 放大（字体也放大，保证清晰不模糊）
    s = lambda v: int(round(v * scale))
    W, H = s(BASE_W), s(BASE_H)
    margin = s(26)

    img = Image.new('RGB', (W, H), SKY_BOTTOM)
    d = ImageDraw.Draw(img, 'RGBA')

    # 上半天际略亮（模拟夜空层次，用矩形分块代替渐变）
    d.rectangle([0, 0, W, s(180)], fill=SKY_TOP + (150,))

    # 月牙 + 光晕
    mx, my = W - s(74), s(84)
    d.ellipse([mx - s(56), my - s(56), mx + s(56), my + s(56)],
              fill=MOON_GLOW + (26,))
    d.ellipse([mx - s(30), my - s(30), mx + s(30), my + s(30)], fill=MOON)
    d.ellipse([mx + s(14) - s(26), my - s(10) - s(26),
               mx + s(14) + s(26), my - s(10) + s(26)],
              fill=SKY_TOP + (255,))

    # 星点
    stars = [(60, 62, 2), (104, 116, 1), (48, 156, 1), (160, 52, 1),
             (212, 104, 1), (136, 172, 1), (256, 156, 1), (330, 190, 1),
             (78, 216, 1)]
    for x, y, r in stars:
        x, y, r = s(x), s(y), max(1, s(r))
        d.ellipse([x - r, y - r, x + r, y + r], fill=STAR + (200,))

    # 标题
    f_title = _load_font(s(24), bold=True)
    title = '今 夜 天 气'
    tw = d.textlength(title, font=f_title)
    d.text(((W - tw) / 2, s(44)), title, font=f_title, fill=TEXT_TITLE)
    d.line([W // 2 - s(70), s(84), W // 2 + s(70), s(84)],
           fill=GLASS_BORDER + (90,), width=max(1, s(1)))

    # 两个校区的玻璃卡片
    f_name = _load_font(s(17))
    f_body = _load_font(s(17))
    f_temp = _load_font(s(34), bold=True)

    card_h = s(136)
    gap = s(16)
    top = s(104)
    for name, w in current.items():
        d.rounded_rectangle([margin, top, W - margin, top + card_h],
                            radius=s(18), fill=GLASS + (20,),
                            outline=GLASS_BORDER + (77,), width=max(1, s(1)))
        d.text((margin + s(24), top + s(22)), name, font=f_name,
               fill=TEXT_NAME)
        body = f"{w.get('text', '')}　·　风速 {w.get('wind_scale', '')} 级"
        d.text((margin + s(24), top + s(54)), body, font=f_body,
               fill=TEXT_BODY)
        d.text((margin + s(24), top + s(84)), f"{w.get('temp', '')}°",
               font=f_temp, fill=TEXT_TEMP)
        top += card_h + gap

    # 突变提醒（若有）
    if changes:
        f_warn = _load_font(s(15))
        d.text((margin, top - s(2)), '⚠ ' + '；'.join(changes),
               font=f_warn, fill=(255, 180, 120))

    # 单个按钮：知道了（整行宽，居中）
    btn_h = s(60)
    btn_y = H - s(116)
    bx1, bx2 = margin, W - margin
    d.rounded_rectangle([bx1, btn_y, bx2, btn_y + btn_h], radius=btn_h // 2,
                        fill=BTN_GOLD)
    f_btn = _load_font(s(20), bold=True)
    text = '知道了'
    tw = d.textlength(text, font=f_btn)
    d.text(((W - tw) / 2, btn_y + s(17)), text, font=f_btn,
           fill=BTN_GOLD_TEXT)

    # 底部小字
    f_tip = _load_font(s(14))
    tip = '点「知道了」今夜不再打扰 · 天气突变仍会提醒'
    tw = d.textlength(tip, font=f_tip)
    d.text(((W - tw) / 2, H - s(42)), tip, font=f_tip,
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
        """显示天气卡片（必须在主线程调用）。

        天气线程通过 root.after(0, lambda: self.show_weather(...)) 调度过来。
        """
        if not current:
            return
        # 关闭上一个天气卡片
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
        canvas._card_img = photo   # 防 GC

        for (x1, y1, x2, y2) in hits.values():
            tag = 'btn_confirm'
            canvas.create_rectangle(x1, y1, x2, y2, fill='', outline='',
                                    tags=tag)
            canvas.tag_bind(tag, '<Button-1>',
                            lambda e: self._on_weather_confirm())

        self._weather_win = win
        self._place_weather_win()
        win.deiconify()

    # ---------- 定位与跟随 ----------
    def _place_weather_win(self):
        """把天气卡片摆到桌宠附近，并保证不出屏幕、不被遮挡。"""
        win = getattr(self, '_weather_win', None)
        if win is None:
            return
        try:
            cw = getattr(self, '_weather_w', 0)
            ch = getattr(self, '_weather_h', 0)
            px = self.root.winfo_x()
            py = self.root.winfo_y()
            x = px + self._frame_w // 2 - cw // 2
            y_up = py - ch - 10
            y = y_up if y_up >= 0 else py + self._frame_h + 10
            # 夹在屏幕内，避免跑出可视区
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

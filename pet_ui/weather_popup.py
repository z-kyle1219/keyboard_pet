"""天气播报气泡：星夜主题卡片（Pillow 渲染 + 知道了）。

设计（与 popup.py 同套路，离屏渲染成一张图，tkinter 只负责显示）：
- 深蓝夜空底 + 月牙 + 星点
- 多个地点**左右并排**（宽而矮，避免上下堆叠过高遮挡屏幕）
- 每个地点一块玻璃卡片：现在（实况）→ 明天（概览 + 白天/夜间对比 + 时段条）
- 有降雨时额外显示「雨 14:00–16:00 小雨」
- 底部一个按钮：知道了
- 卡片跟随桌宠移动，始终置顶；尺寸自动限制在屏幕内（超屏则整体缩放）

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
COL_RAIN_TEXT = (140, 180, 240)
BTN_GOLD = (255, 217, 138)
BTN_GOLD_TEXT = (61, 42, 0)

# 时段条各天气的底色（拉开区分度：暖黄 / 中蓝 / 深灰 / 亮蓝 / 白 / 紫）
STRIP_SUN = (250, 200, 80)       # 晴（暖黄）
STRIP_CLOUD = (130, 165, 210)    # 多云（中蓝）
STRIP_OVERCAST = (95, 105, 125)  # 阴（深灰）
STRIP_RAIN = (60, 120, 230)      # 雨（亮蓝）
STRIP_SNOW = (225, 238, 250)     # 雪（近白）
STRIP_THUNDER = (150, 90, 200)   # 雷（紫）

# 图例（颜色 → 天气），顺序即展示顺序
STRIP_LEGEND = [
    ('晴', STRIP_SUN),
    ('多云', STRIP_CLOUD),
    ('阴', STRIP_OVERCAST),
    ('雨', STRIP_RAIN),
]

TITLE = '天 气 之 子'

# 单列基准尺寸（96 DPI 逻辑像素）；多列并排时宽度按列数累加
COL_W = 300
COL_H = 344
COL_GAP = 16
MARGIN = 24
HEADER_H = 92      # 标题区高度
FOOTER_H = 106     # 按钮 + 小字区高度
STRIP_BASE = 104   # 时段条专属分区高度（分隔线 + 条 + 刻度 + 图例 + 留白）

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


def _has_precip(text):
    """判断天气文字是否含降水（雨/雪/雷），与 weather._is_rain 保持一致。"""
    return any(k in text for k in ("雨", "雪", "雷"))


def _strip_color(text):
    """按时段文字取底色（雷/雪优先于雨，避免被误判）。"""
    if '雷' in text:
        return STRIP_THUNDER
    if '雪' in text:
        return STRIP_SNOW
    if '雨' in text:
        return STRIP_RAIN
    if '晴' in text:
        return STRIP_SUN
    if '多云' in text:
        return STRIP_CLOUD
    if '阴' in text:
        return STRIP_OVERCAST
    return (120, 135, 170)


def _wrap_text(draw, text, font, max_w, max_lines=3):
    """把文本按像素宽度折行（优先在全角空格处断开），最多 max_lines 行。

    超出行数时截断并在末尾加省略号，保证永不超出给定宽度。
    """
    lines = []
    cur = ''
    for tok in text.split('\u3000'):   # 全角空格是时段之间的分隔符
        cand = tok if not cur else cur + '\u3000' + tok
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
            cur = ''
        # 单个时段本身超宽 → 逐字符硬切
        for ch in tok:
            if cur and draw.textlength(cur + ch, font=font) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1][:-1] + '…'
        while last and draw.textlength(last, font=font) > max_w:
            last = last[:-2] + '…'
        lines[-1] = last
    return lines


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
    """把天气数据渲染成一张星夜卡片（Pillow，地点左右并排）。

    current: {地点名: 地点数据字典（见 weather.fetch_location）}
    changes: 突变描述列表
    scale:   DPI 缩放系数
    返回: (PIL.Image, 按钮命中区域 dict)
    """
    s = lambda v: int(round(v * scale))
    n = max(1, len(current))

    W = s(MARGIN * 2) + n * s(COL_W) + (n - 1) * s(COL_GAP)
    H = s(HEADER_H) + s(COL_H) + s(FOOTER_H)

    img = Image.new('RGB', (W, H), SKY_BOTTOM)
    d = ImageDraw.Draw(img, 'RGBA')

    # 天际略亮
    d.rectangle([0, 0, W, s(HEADER_H + 40)], fill=SKY_TOP + (150,))

    # 月牙 + 光晕
    mx, my = W - s(66), s(58)
    d.ellipse([mx - s(42), my - s(42), mx + s(42), my + s(42)],
              fill=MOON_GLOW + (26,))
    d.ellipse([mx - s(22), my - s(22), mx + s(22), my + s(22)], fill=MOON)
    d.ellipse([mx + s(10) - s(19), my - s(8) - s(19),
               mx + s(10) + s(19), my - s(8) + s(19)], fill=SKY_TOP + (255,))

    # 星点
    stars = [(50, 44, 2), (92, 78, 1), (150, 38, 1), (196, 74, 1),
             (250, 52, 1), (120, 96, 1), (286, 92, 1)]
    for x, y, r in stars:
        x, y, r = s(x), s(y), max(1, s(r))
        if x < W and y < H:
            d.ellipse([x - r, y - r, x + r, y + r], fill=STAR + (200,))

    # 标题
    f_title = _load_font(s(23), bold=True)
    tw = d.textlength(TITLE, font=f_title)
    d.text(((W - tw) / 2, s(30)), TITLE, font=f_title, fill=TEXT_TITLE)
    d.line([W // 2 - s(70), s(66), W // 2 + s(70), s(66)],
           fill=GLASS_BORDER + (90,), width=max(1, s(1)))

    f_name = _load_font(s(15))
    f_label = _load_font(s(13))
    f_body = _load_font(s(15))
    f_temp = _load_font(s(24), bold=True)
    f_delta = _load_font(s(13))
    f_strip = _load_font(s(10))
    f_rain = _load_font(s(13))

    # 各地点一列，左右并排
    col_top = s(HEADER_H)
    for i, (name, data) in enumerate(current.items()):
        col_x = s(MARGIN) + i * (s(COL_W) + s(COL_GAP))
        col_h = s(COL_H)
        d.rounded_rectangle([col_x, col_top, col_x + s(COL_W), col_top + col_h],
                            radius=s(16), fill=GLASS + (18,),
                            outline=GLASS_BORDER + (70,), width=max(1, s(1)))

        pad = s(18)
        x = col_x + pad
        y = col_top + s(16)
        right = col_x + s(COL_W) - pad

        d.text((x, y), name, font=f_name, fill=TEXT_NAME)
        y += s(26)

        now = data.get('now', {})
        d.text((x, y), '现在', font=f_label, fill=TEXT_LABEL)
        d.text((x + s(52), y),
               f"{now.get('text', '')} {now.get('temp', '')}° "
               f"风{now.get('wind_scale', '')}级",
               font=f_body, fill=TEXT_BODY)
        y += s(24)

        d.line([x, y, right, y], fill=GLASS_BORDER + (60,), width=max(1, s(1)))
        y += s(10)

        tm = data.get('tomorrow') or {}
        d.text((x, y), '明天', font=f_label, fill=TEXT_LABEL)
        d.text((x + s(52), y), tm.get('brief', ''), font=f_body,
               fill=TEXT_BODY)
        y += s(26)

        if tm:
            d.text((x, y), '白天', font=f_label, fill=TEXT_LABEL)
            d.text((x + s(52), y - s(3)),
                   f"{tm.get('day_temp', '')}°", font=f_temp, fill=TEXT_DAY)
            dt, dc = _fmt_delta(tm.get('day_delta'))
            d.text((x + s(94), y), dt, font=f_delta, fill=dc)
            y += s(30)

            d.text((x, y), '夜间', font=f_label, fill=TEXT_LABEL)
            d.text((x + s(52), y - s(3)),
                   f"{tm.get('night_temp', '')}°", font=f_temp,
                   fill=TEXT_NIGHT)
            nt, nc = _fmt_delta(tm.get('night_delta'))
            d.text((x + s(94), y), nt, font=f_delta, fill=nc)
            y += s(28)

        # 时段条专属分区（底部固定带，与正文用分隔线隔开）
        band_top = col_top + col_h - s(STRIP_BASE)

        # 降雨时段：**固定在时刻条上方**（不随内容流走，避免被时段条盖住）
        # 按列宽折行（最多 3 行），避免时段太多时一行溢出、盖到相邻列
        periods = data.get('periods', [])
        if periods:
            txt = '　'.join(f"{p['start']}–{p['end']} {p['text']}"
                           for p in periods)
            lines = _wrap_text(d, '雨 ' + txt, f_rain, right - x,
                               max_lines=3)
            line_h = s(18)
            ty = band_top - s(24) - (len(lines) - 1) * line_h
            for ln in lines:
                d.text((x, ty), ln, font=f_rain, fill=COL_RAIN_TEXT)
                ty += line_h
        elif _has_precip((data.get('tomorrow') or {}).get('brief', '')):
            # 兜底：日报预报有雨，但逐小时还没标出具体时段 → 提示"待定"
            ty = band_top - s(24)
            d.text((x, ty), '明天有雨 · 时段待定', font=f_rain,
                   fill=COL_RAIN_TEXT)

        strip = data.get('strip', [])
        if strip:
            # 分隔线
            d.line([x, band_top, right, band_top],
                   fill=GLASS_BORDER + (70,), width=max(1, s(1)))
            bar_y = band_top + s(14)
            bar_h = s(22)
            bx0, bx1 = x, right
            total = 18.0   # 06–24

            def _pos(h):
                t = (h - 6) / total
                t = max(0.0, min(1.0, t))
                return bx0 + (bx1 - bx0) * t

            # 底槽（未着色部分）
            d.rounded_rectangle([bx0, bar_y, bx1, bar_y + bar_h],
                                radius=s(4), fill=(255, 255, 255, 26))
            for r in strip:
                sx, ex = _pos(r['start_h']), _pos(r['end_h'])
                if ex <= sx:
                    continue
                d.rectangle([sx, bar_y, ex, bar_y + bar_h],
                            fill=_strip_color(r['text']) + (240,))
            # 刻度
            for hh in (6, 12, 18, 24):
                tx = _pos(hh)
                d.text((tx, bar_y + bar_h + s(4)), f"{hh:02d}",
                       font=f_strip, fill=TEXT_LABEL)

            # 图例：颜色 → 天气
            ly = bar_y + bar_h + s(20)
            lx = bx0
            for label, color in STRIP_LEGEND:
                d.rectangle([lx, ly, lx + s(9), ly + s(9)],
                            fill=color + (255,))
                d.text((lx + s(13), ly - s(3)), label, font=f_strip,
                       fill=TEXT_LABEL)
                lx += s(13) + d.textlength(label, font=f_strip) + s(12)

    # 突变提醒（在卡片底部与按钮之间，预留了不重叠的间距）
    foot_y = s(HEADER_H) + s(COL_H) + s(4)
    if changes:
        f_warn = _load_font(s(13))
        d.text((s(MARGIN), foot_y), '⚠ ' + '；'.join(changes), font=f_warn,
               fill=(255, 180, 120))

    # 按钮
    btn_h = s(52)
    btn_y = H - s(FOOTER_H) + s(22)
    bx1, bx2 = s(MARGIN), W - s(MARGIN)
    d.rounded_rectangle([bx1, btn_y, bx2, btn_y + btn_h], radius=btn_h // 2,
                        fill=BTN_GOLD)
    f_btn = _load_font(s(19), bold=True)
    text = '知道了'
    tw = d.textlength(text, font=f_btn)
    d.text(((W - tw) / 2, btn_y + s(13)), text, font=f_btn,
           fill=BTN_GOLD_TEXT)

    f_tip = _load_font(s(12))
    tip = '点「知道了」今夜不再打扰 · 天气突变仍会提醒'
    tw = d.textlength(tip, font=f_tip)
    d.text(((W - tw) / 2, H - s(26)), tip, font=f_tip,
           fill=TEXT_NAME + (217,))

    hits = {'confirm': (bx1, btn_y, bx2, btn_y + btn_h)}
    return img, hits


class WeatherMixin:
    """天气气泡：作为 Mixin 混入 PetApp。"""

    def _fit_scale(self, n_cols):
        """计算一个既跟随 DPI、又保证卡片不超出屏幕的缩放系数。"""
        try:
            dpi = max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        except Exception:
            dpi = 1.0
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        # 逻辑尺寸
        base_w = MARGIN * 2 + n_cols * COL_W + max(0, n_cols - 1) * COL_GAP
        base_h = HEADER_H + COL_H + FOOTER_H

        # 最多占屏幕的 92% 宽 / 88% 高
        max_w = sw * 0.92 / base_w
        max_h = sh * 0.88 / base_h
        return max(0.7, min(dpi, max_w, max_h))

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

        scale = self._fit_scale(len(current))
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
        """把天气卡片摆到桌宠附近，保证不出屏幕、不被遮挡。

        优先放在桌宠**上方**；上方空间不足则放下方；左右夹在屏幕内。
        """
        win = getattr(self, '_weather_win', None)
        if win is None:
            return
        try:
            cw = getattr(self, '_weather_w', 0)
            ch = getattr(self, '_weather_h', 0)
            px, py = self.root.winfo_x(), self.root.winfo_y()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()

            x = px + self._frame_w // 2 - cw // 2
            x = max(0, min(x, sw - cw))

            y_up = py - ch - 10
            y_down = py + self._frame_h + 10
            if y_up >= 0:
                y = y_up
            elif y_down + ch <= sh:
                y = y_down
            else:
                # 上下都放不下 → 居中并夹在屏幕内
                y = max(0, min(y_up, sh - ch))

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

"""积分台账窗口：WorkBuddy 积分消耗总览（纯本地，不联网、不调用 AI）。

右键菜单「积分台账」打开。卡片样式跟「各软件分布」一致：
Pillow 按 (DPI × 2) 离屏渲染，再缩到物理像素贴到 Canvas，
所以字和柱子的边缘都是平滑的（tkinter Canvas 手绘没有抗锯齿）。

交互：
  悬停某一天  → 该列浮出淡底 + 深色数值卡片（日期 / 积分 / 会话数）
  移开        → 恢复默认，最高的一根柱子标出数值
  点击卡片    → 重新读一次数据库刷新（不会自动弹，也不会提醒）

悬停为什么重绘整张图：tkinter 的 Canvas 只能贴一张位图，
没有"局部换色"的低成本办法。但一张 1200×700 的图重绘只要十几毫秒，
而且只在"命中的那一列变了"时才重绘，横扫一遍最多 14 次，不会卡。

数据由 credit_stats.load_overview() 提供，本文件只管画。
"""
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import credit_stats
from logger import logger
from pet_ui.app_stats import (
    WHITE, INK, MUTED, FAINT, DIVIDER, TRACK,
    GREEN, GREEN_DARK,
    load_font, measure, draw_text, nice_ceiling, _dpi_scale,
)

# ---------- 逻辑布局（逻辑像素，绘制时乘 k）----------
W = 600
PAD = 24
SS = 2
CHART_H = 150
WIN_H = 366

HEADER_H = 52
METRIC_TOP = 64
METRIC_W = 168
METRIC_GAP = 14
CHART_TOP = 152
CHART_BOTTOM = CHART_TOP + CHART_H
CHART_LEFT = 52
CHART_RIGHT = W - PAD
FOOTER_Y = 334
DAYS = 14

BAR_COLOR = GREEN
BAR_TODAY = GREEN_DARK
BAR_HOVER = (10, 78, 61)        # 悬停：更深的墨绿
COL_HOVER = (246, 249, 247)     # 悬停整列的淡底
TIP_BG = (31, 42, 38)
TIP_TEXT = (255, 255, 255)
BAR_RATIO = 0.46                # 柱宽 / 列宽；越小越透气


def _fmt_credits(v):
    """积分展示：大数收成 k，小数额保留两位。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '0'
    if v >= 10000:
        return f'{v / 1000:.1f}k'
    if v >= 1000:
        return f'{v:,.1f}'
    if v == int(v):
        return f'{int(v)}'
    return f'{v:.2f}'


def _fmt_axis(v):
    """纵轴刻度：0 / 500 / 1k 这种，不用带小数。"""
    if v >= 1000:
        return f'{v / 1000:.1f}k'.replace('.0k', 'k')
    return f'{v:.0f}'


def _short_date(d):
    """'2026-10-31' → '10/31'。"""
    try:
        return f'{int(d[5:7])}/{int(d[8:10])}'
    except (ValueError, IndexError):
        return d


class CreditMixin:
    """提供 _show_credit：右键菜单「积分台账」。"""

    def _show_credit(self):
        win = getattr(self, '_credit_win', None)
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                self._refresh_credit(reload=True)
                return
        except Exception:
            pass

        scale = _dpi_scale(self.root)

        top = tk.Toplevel(self.root)
        top.title('积分台账')
        top.attributes('-topmost', True)
        top.config(bg='white')
        top.resizable(False, False)
        top.withdraw()

        canvas = tk.Canvas(top, bg='white', highlightthickness=0, bd=0,
                           width=int(W * scale), height=int(WIN_H * scale))
        canvas.pack()

        self._credit_win = top
        self._credit_canvas = canvas
        self._credit_scale = scale
        self._credit_holder = {
            'photo': None,   # 防 GC
            'item': None,    # canvas 上的图片 item
            'placed': False, # 是否已定位到桌宠旁边
            'data': None,    # 最近一次取到的数据
            'layout': None,  # 柱子命中区
            'hover': None,   # 当前悬停的列下标
        }

        canvas.bind('<Button-1>', lambda _e: self._refresh_credit(reload=True))
        canvas.bind('<Motion>', self._on_credit_motion)
        canvas.bind('<Leave>', self._on_credit_leave)
        top.protocol('WM_DELETE_WINDOW', self._close_credit)
        self._refresh_credit(reload=True)

    # ---------- 悬停 ----------
    def _on_credit_motion(self, e):
        holder = getattr(self, '_credit_holder', None)
        if not holder or not holder.get('layout'):
            return
        scale = getattr(self, '_credit_scale', 1.0) or 1.0
        x = e.x / scale
        y = e.y / scale
        idx = None
        # 纵向放宽一点：贴着 x 轴标签和柱顶上方也算命中，好点中
        if (CHART_TOP - 10) <= y <= (CHART_BOTTOM + 18):
            for i, x0, x1 in holder['layout'].get('bars', []):
                if x0 <= x < x1:
                    idx = i
                    break
        if idx != holder['hover']:
            holder['hover'] = idx
            self._refresh_credit(reload=False)

    def _on_credit_leave(self, _e):
        holder = getattr(self, '_credit_holder', None)
        if holder and holder.get('hover') is not None:
            holder['hover'] = None
            self._refresh_credit(reload=False)

    # ---------- 渲染 ----------
    def _refresh_credit(self, reload=True):
        top = getattr(self, '_credit_win', None)
        canvas = getattr(self, '_credit_canvas', None)
        holder = getattr(self, '_credit_holder', None)
        if top is None or canvas is None or holder is None:
            return
        try:
            if not top.winfo_exists():
                return
        except Exception:
            return

        scale = getattr(self, '_credit_scale', 1.0) or 1.0

        # 只有"点击刷新"才重新读库；悬停复用上一次的数据，
        # 否则每次移动鼠标都要去拷一遍 WorkBuddy 的 sqlite
        if reload or holder.get('data') is None:
            try:
                holder['data'] = credit_stats.load_overview(DAYS, force=True)
            except Exception:
                logger.exception('读取积分数据失败')
                if holder.get('data') is None:
                    return

        try:
            img, layout = _build_card(holder['data'], scale, hover=holder.get('hover'))
        except Exception:
            logger.exception('绘制积分台账失败')
            return
        holder['layout'] = layout

        target_w = int(W * scale)
        if img.width != target_w:
            img = img.resize(
                (target_w, int(round(img.height * target_w / img.width))),
                Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        if holder['item'] is None:
            holder['item'] = canvas.create_image(0, 0, anchor='nw', image=photo)
        else:
            canvas.itemconfig(holder['item'], image=photo)
        holder['photo'] = photo
        canvas.config(width=img.width, height=img.height)

        if not holder['placed']:
            holder['placed'] = True
            top.update_idletasks()
            self._place_credit_win(img.width, img.height)
        top.deiconify()

    def _place_credit_win(self, w=None, h=None):
        """贴到桌宠右侧，超出屏幕就翻到左边，并夹在屏幕内。"""
        win = getattr(self, '_credit_win', None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            if w is None:
                w = win.winfo_width()
            if h is None:
                h = win.winfo_height()
            px = self.root.winfo_x() + self._frame_w + 8
            py = self.root.winfo_y()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            if px + w > sw:
                px = self.root.winfo_x() - w - 8
            px = max(0, min(px, sw - w))
            py = max(0, min(py, sh - h))
            win.geometry(f'{w}x{h}+{int(px)}+{int(py)}')
        except Exception:
            logger.exception('积分台账窗口定位失败')

    def _close_credit(self):
        win = getattr(self, '_credit_win', None)
        self._credit_win = None
        self._credit_canvas = None
        self._credit_holder = None
        try:
            if win is not None and win.winfo_exists():
                win.destroy()
        except Exception:
            pass


# ============================================================
# 绘制
# ============================================================
def _build_card(data, scale, hover=None):
    """返回 (PIL.Image, layout)。所有坐标在逻辑空间算，绘制时乘 k。"""
    k = scale * SS
    img = Image.new('RGB', (int(W * k), int(WIN_H * k)), WHITE)
    d = ImageDraw.Draw(img)

    # ---------- 标题 ----------
    draw_text(d, (PAD * k, 16 * k), '积分台账',
              load_font(14 * k, bold=True), INK, anchor='lt')
    draw_text(d, ((W - PAD) * k, 20 * k), f'近 {DAYS} 天',
              load_font(10.5 * k), FAINT, anchor='rt')
    d.line([PAD * k, HEADER_H * k, (W - PAD) * k, HEADER_H * k],
           fill=DIVIDER, width=max(1, int(k * 0.5)))

    if not data.get('ok'):
        _draw_metrics(d, k, 0, 0, dim=True)
        draw_text(d, (W / 2 * k, ((CHART_TOP + CHART_BOTTOM) / 2) * k),
                  '还没有积分记录', load_font(11 * k), FAINT, anchor='mm')
        draw_text(d, (PAD * k, FOOTER_Y * k),
                  '没有找到 WorkBuddy 积分记录 · 点击刷新',
                  load_font(9.5 * k), FAINT, anchor='lt')
        return img, {'bars': []}

    # ---------- 两个数 ----------
    _draw_metrics(d, k,
                  data.get('today_credits', 0.0),
                  data.get('total_credits', 0.0))

    # ---------- 柱状图 ----------
    layout = _draw_bars(d, k, data, hover)

    # ---------- 底部说明 ----------
    note = ('数据来自 WorkBuddy 本地库 · 悬停看数值 · 点击刷新'
            if data.get('source') == 'db'
            else '数据来自积分台账 CSV · 悬停看数值 · 点击刷新')
    draw_text(d, (PAD * k, FOOTER_Y * k), note,
              load_font(9.5 * k), FAINT, anchor='lt')

    first = data.get('first_date')
    if first:
        tail = f'{_short_date(first)} 起 · 共 {data.get("total_sessions", 0)} 个会话'
        draw_text(d, ((W - PAD) * k, FOOTER_Y * k), tail,
                  load_font(9.5 * k), FAINT, anchor='rt')
    return img, layout


def _draw_metrics(d, k, today, total, dim=False):
    """今日使用 / 累计使用。"""
    items = [
        ('今日使用积分', _fmt_credits(today)),
        ('累计使用积分', _fmt_credits(total)),
    ]
    value_font = load_font(23 * k, bold=True)
    for i, (label, value) in enumerate(items):
        x = PAD + i * (METRIC_W + METRIC_GAP)
        draw_text(d, (x * k, METRIC_TOP * k), label,
                  load_font(11 * k), MUTED, anchor='lt')
        color = FAINT if dim else INK
        draw_text(d, (x * k, (METRIC_TOP + 20) * k), value,
                  value_font, color, anchor='lt')


def _draw_bars(d, k, data, hover=None):
    """近 N 天柱状图，返回命中区 {'bars': [(i, x0, x1)]}。"""
    series = data.get('series') or []
    day_sessions = data.get('day_sessions') or {}
    if not series:
        draw_text(d, (W / 2 * k, ((CHART_TOP + CHART_BOTTOM) / 2) * k),
                  '还没有积分记录', load_font(11 * k), FAINT, anchor='mm')
        return {'bars': []}

    values = [v for _d, v, _has in series]
    max_v = max(values) if values else 0.0
    # 只留一点点头顶余量：1.15 倍会跳到下一个刻度（478 → 1000），柱子会被压扁
    top_val = nice_ceiling(max_v * 1.02) if max_v > 0 else 1

    span_y = CHART_BOTTOM - CHART_TOP
    span_x = CHART_RIGHT - CHART_LEFT
    n = len(series)
    slot = span_x / n
    bar_w = max(8.0, slot * BAR_RATIO)

    f_tick = load_font(9 * k)

    # 横向网格（0 / 50% / 100%）
    for i in range(3):
        y = CHART_BOTTOM - span_y * i / 2
        d.line([CHART_LEFT * k, y * k, CHART_RIGHT * k, y * k],
               fill=DIVIDER, width=max(1, int(k * 0.5)))
        if max_v > 0:
            draw_text(d, ((CHART_LEFT - 8) * k, y * k),
                      _fmt_axis(top_val * i / 2), f_tick, FAINT, anchor='rm')

    # 悬停整列淡底（在柱子之前画，柱子仍然压在上面）
    hovering = hover is not None and 0 <= hover < n
    if hovering:
        hx0 = CHART_LEFT + slot * hover + 1.5
        hx1 = CHART_LEFT + slot * (hover + 1) - 1.5
        d.rounded_rectangle([hx0 * k, (CHART_TOP - 10) * k,
                             hx1 * k, (CHART_BOTTOM + 2) * k],
                            radius=6 * k, fill=COL_HOVER)

    bars = []
    tops = {}              # i -> 柱顶 y；空记录时落在底座上
    today_idx = n - 1
    max_idx = values.index(max_v) if max_v > 0 else -1

    for i, (date, v, has) in enumerate(series):
        x0 = CHART_LEFT + slot * i + (slot - bar_w) / 2
        x1 = x0 + bar_w
        bars.append((i, CHART_LEFT + slot * i, CHART_LEFT + slot * (i + 1)))

        if not has or v <= 0:
            # 没记录：底座一小截灰条，区别于「真的消耗 0」
            # 注意：x 也必须乘 k。只乘 y 会让柱子留在逻辑坐标上（左侧挤成一团），
            # 而日期标签、网格线都是乘过 k 的，两边就对不齐了。
            d.rounded_rectangle(
                [x0 * k, (CHART_BOTTOM - 3) * k, x1 * k, CHART_BOTTOM * k],
                radius=1.5 * k, fill=TRACK)
            tops[i] = CHART_BOTTOM - 3
        else:
            h = max(3.0, (v / top_val) * span_y)
            if i == hover:
                color = BAR_HOVER
            elif i == today_idx:
                color = BAR_TODAY
            else:
                color = BAR_COLOR
            d.rounded_rectangle(
                [x0 * k, (CHART_BOTTOM - h) * k, x1 * k, CHART_BOTTOM * k],
                radius=3.5 * k, fill=color)
            tops[i] = CHART_BOTTOM - h

        is_today = (i == today_idx)
        draw_text(d, ((x0 + x1) / 2 * k, (CHART_BOTTOM + 9) * k),
                  _short_date(date),
                  load_font(9 * k, bold=(is_today or i == hover)),
                  INK if (is_today or i == hover) else FAINT, anchor='mt')

    # 悬停时跟着悬停那根（空记录也给「无记录」），平时标最高那根
    if hovering:
        _draw_tooltip(d, k, hover, series[hover], day_sessions,
                      tops.get(hover, CHART_BOTTOM - 3), n)
    elif max_idx >= 0:
        _draw_value_tag(d, k, max_idx, series[max_idx][1],
                        tops.get(max_idx, CHART_BOTTOM - 3), n)

    return {'bars': bars}


def _bar_center(idx, n):
    slot = (CHART_RIGHT - CHART_LEFT) / n
    return CHART_LEFT + slot * idx + slot / 2


def _draw_value_tag(d, k, idx, v, bar_top_y, n):
    """默认态：在最高那根柱子上方标数值。"""
    cx = _bar_center(idx, n)
    draw_text(d, (cx * k, (bar_top_y - 5) * k),
              _fmt_credits(v), load_font(9 * k), BAR_TODAY, anchor='mb')


def _draw_tooltip(d, k, idx, item, day_sessions, bar_top_y, n):
    """悬停态：深色小卡片，显示日期 / 积分 / 会话数。"""
    date, v, has = item
    if not has:
        text = f'{_short_date(date)} · 无记录'
    elif v <= 0:
        text = f'{_short_date(date)} · 0 积分'
    else:
        cnt = int(day_sessions.get(date, 0))
        text = f'{_short_date(date)} · {_fmt_credits(v)} 积分'
        if cnt:
            text += f' · {cnt} 个会话'

    font = load_font(10 * k)
    tw = measure(d, text, font) / k
    bw = tw + 20
    bh = 26
    cx = _bar_center(idx, n)

    x0 = min(max(cx - bw / 2, PAD), W - PAD - bw)
    y0 = bar_top_y - bh - 8
    if y0 < 6:                 # 顶到标题区就翻到柱子下方
        y0 = CHART_BOTTOM + 22
        bar_bottom = True
    else:
        bar_bottom = False

    # 小尖角，指向对应的柱子
    tip_x = min(max(cx, x0 + 10), x0 + bw - 10)
    d.rounded_rectangle([x0 * k, y0 * k, (x0 + bw) * k, (y0 + bh) * k],
                        radius=7 * k, fill=TIP_BG)
    if bar_bottom:
        d.polygon([((tip_x - 5) * k, y0 * k), ((tip_x + 5) * k, y0 * k),
                   (tip_x * k, (y0 - 6) * k)], fill=TIP_BG)
    else:
        d.polygon([((tip_x - 5) * k, (y0 + bh) * k),
                   ((tip_x + 5) * k, (y0 + bh) * k),
                   (tip_x * k, (y0 + bh + 6) * k)], fill=TIP_BG)
    draw_text(d, ((x0 + bw / 2) * k, (y0 + bh / 2) * k), text, font,
              TIP_TEXT, anchor='mm')

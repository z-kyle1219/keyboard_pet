"""各软件分布窗口：今天看条形，近 7 天看折线。

为什么整窗用 Pillow 渲染而不是直接 Canvas 手绘：
- tkinter Canvas **没有抗锯齿**。折线的斜线段、圆点和圆角在非整数坐标上
  一定会出现锯齿毛边，这是引擎限制，调参数救不回来。
- Pillow 的 ImageDraw 可以先按 2 倍尺寸绘制，再 LANCZOS 缩回目标尺寸，
  等效 2x 超采样，线条和文字都是平滑的。
- 同时按屏幕 DPI 放大渲染，保证在高分屏上既清晰、尺寸又合适。

所以流程是：逻辑坐标 → 按 (DPI × 2) 绘制 → 缩到物理像素贴到 Canvas。
点击命中仍用逻辑坐标，和视觉一一对应。
"""
import math
import os
import tkinter as tk
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont, ImageTk

import db
from logger import logger

# ---------- 配色（白底极简 + 绿色数据）----------
GREEN = (29, 158, 117)
GREEN_DARK = (15, 110, 86)
GREEN_MID = (44, 175, 132)
GREEN_LIGHT = (93, 202, 165)
TRACK = (242, 245, 244)
DIVIDER = (236, 239, 238)
INK = (24, 28, 27)
MUTED = (107, 114, 128)
FAINT = (156, 163, 175)
WHITE = (255, 255, 255)

LINE_COLORS = (GREEN_DARK, GREEN, GREEN_LIGHT)

# ---------- 逻辑布局（单位：逻辑像素，绘制时再乘缩放）----------
W = 520
PAD = 20
SS = 2                      # 超采样倍数

HEADER_H = 52
TITLE_Y = 17

# 条形
BAR_LABEL_X = PAD
BAR_X0 = 136
BAR_X1 = W - PAD
BAR_H = 16
ROW_H = 44
EXPAND_H = 24
TODAY_TOP = 92

# 折线
CHART_TOP = 112
CHART_BOTTOM = 286
CHART_LEFT = 52
CHART_RIGHT = W - PAD
WEEK_LEGEND_Y = 320

TOP_N_BARS = 5
TOP_N_LINES = 3
WEEK_DAYS = 7

_FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
_FONT_CACHE = {}

# 中文字体候选（按优先级）。msyh 是 Win 默认，雅黑最贴合项目其它窗口。
_FONTS_REGULAR = ('msyh.ttc', 'msyhl.ttc', 'Deng.ttf', 'simhei.ttf')
_FONTS_BOLD = ('msyhbd.ttc', 'Dengb.ttf', 'msyh.ttc', 'simhei.ttf')


# ============================================================
# 基础工具
# ============================================================
def _rgb(color):
    """'#rrggbb' 或 (r,g,b) 统一转 RGB 元组。"""
    if isinstance(color, tuple):
        return color
    c = color.lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def load_font(size, bold=False):
    """按像素字号加载中文字体（带缓存，避免每次重绘都读文件）。"""
    size = max(1, int(round(size)))
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    for name in (_FONTS_BOLD if bold else _FONTS_REGULAR):
        path = os.path.join(_FONT_DIR, name)
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def measure(draw, text, font):
    """文本宽度（兼容新旧 Pillow）。"""
    try:
        return draw.textlength(text, font=font)
    except Exception:
        try:
            return draw.textsize(text, font=font)[0]
        except Exception:
            return len(text) * 8


def draw_text(draw, xy, text, font, fill, anchor='lt'):
    """带 anchor 的文字绘制；旧版 Pillow 不支持 anchor 时降级。"""
    try:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
    except Exception:
        draw.text(xy, text, font=font, fill=fill)


def monotone_path(points, per_seg=16):
    """单调三次 Hermite 插值（Fritsch–Carlson），用于折线平滑。

    为什么不用 Catmull-Rom：后者在数据突变处会「过冲」——
    前面几天是 0、最后一天突然很高时，曲线会被甩到 0 线以下（看上去
    就是负值，还会压住日期标签）。单调插值保证曲线始终落在相邻两点
    之间，不会凭空造出负值。
    """
    n = len(points)
    if n < 3:
        return list(points)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    slopes = [(ys[i + 1] - ys[i]) / dx[i] if dx[i] else 0.0
              for i in range(n - 1)]

    # 每个点的切线：极值点归零，其余用加权调和平均，避免过冲
    m = [0.0] * n
    m[0] = slopes[0]
    m[-1] = slopes[-1]
    for i in range(1, n - 1):
        s0, s1 = slopes[i - 1], slopes[i]
        if s0 * s1 <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * dx[i] + dx[i - 1]
            w2 = dx[i] + 2 * dx[i - 1]
            m[i] = (w1 + w2) / (w1 / s0 + w2 / s1)

    out = []
    for i in range(n - 1):
        h = dx[i]
        for k in range(per_seg):
            t = k / float(per_seg)
            t2 = t * t
            t3 = t2 * t
            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2
            x = h00 * xs[i] + h10 * h + h01 * xs[i + 1] + h11 * h
            y = (h00 * ys[i] + h10 * h * m[i]
                 + h01 * ys[i + 1] + h11 * h * m[i + 1])
            out.append((x, y))
    out.append(points[-1])
    return out


def fmt_count(n):
    return f'{int(n):,}'


def fmt_duration(seconds):
    """秒 → 人读时长，按量级选单位，不足 1 小时精确到分秒。

    之前的实现一律换算成 1 位小数的小时，导致「刚用 2 分钟」显示成
    「0.0 小时」——信息直接丢了。现在分级：
      < 1 分钟    →  45 秒
      < 1 小时    →  12 分 30 秒
      >= 1 小时   →  1 小时 12 分
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f'{seconds} 秒'
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f'{m} 分 {s} 秒' if s else f'{m} 分'
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f'{h} 小时 {m} 分' if m else f'{h} 小时'


def fmt_axis(value, metric):
    if metric == 'seconds':
        hours = value / 3600
        if hours >= 10:
            return f'{hours:.0f}h'
        if hours >= 1:
            return f'{hours:.1f}h'
        return f'{hours * 60:.0f}m'
    if value >= 1000:
        return f'{value / 1000:.1f}k'
    # 刻度落在小数上时保留一位，避免 0/1 都被取整成 "0"
    if value != int(value):
        return f'{value:.1f}'
    return f'{int(value)}'


def nice_ceiling(value):
    """把最大值抬到一个「好看」的刻度上限。"""
    if value <= 0:
        return 1
    mag = 10 ** int(math.log10(value))
    for m in (1, 2, 2.5, 5, 10):
        if value <= mag * m:
            return mag * m
    return mag * 10


def date_range(end_str, days):
    end = datetime.strptime(end_str, '%Y-%m-%d')
    return [(end - timedelta(days=days - 1 - i)).strftime('%Y-%m-%d')
            for i in range(days)]


def _cn_date(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return f'{d.month} 月 {d.day} 日'
    except Exception:
        return date_str


def _ellipsis(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _category_label(category):
    try:
        from app_aliases import CATEGORY_LABELS
        return CATEGORY_LABELS.get(category, category)
    except Exception:
        return category


def _dpi_scale(root):
    """屏幕缩放系数（96 DPI = 1.0）。取不到就按 1.0。"""
    try:
        return max(1.0, root.winfo_fpixels('1i') / 96.0)
    except Exception:
        return 1.0


# ============================================================
# Mixin
# ============================================================
class AppStatsMixin:
    """提供 _show_app_stats：右键菜单「各软件分布」。"""

    def _show_app_stats(self):
        # 先把内存统计落库，保证窗口读到的与内存一致
        try:
            if getattr(self, 'app_tracker', None) is not None:
                self.app_tracker.persist()
        except Exception:
            logger.exception('打开分布窗口前落库失败')

        scale = _dpi_scale(self.root)
        state = {'mode': 'today', 'metric': 'count', 'expanded': None,
                 'scale': scale}

        top = tk.Toplevel(self.root)
        top.title('各软件分布')
        top.attributes('-topmost', True)
        top.config(bg='white')
        top.resizable(False, False)
        top.withdraw()

        canvas = tk.Canvas(top, bg='white', highlightthickness=0, bd=0,
                           width=int(W * scale), height=int(340 * scale))
        canvas.pack()

        holder = {'photo': None, 'item': None, 'layout': None, 'placed': False}

        def refresh():
            """重建整张图并贴到 Canvas。"""
            try:
                img, layout = _build(state)
            except Exception:
                logger.exception('绘制分布图失败')
                return
            holder['layout'] = layout

            # 2x 超采样图 → 缩到物理像素尺寸（LANCZOS 抗锯齿）
            target_w = int(W * scale)
            if img.width != target_w:
                img = img.resize(
                    (target_w, int(round(img.height * target_w / img.width))),
                    Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            if holder['item'] is None:
                holder['item'] = canvas.create_image(0, 0, anchor='nw',
                                                     image=photo)
            else:
                canvas.itemconfig(holder['item'], image=photo)
            holder['photo'] = photo        # 防 GC
            canvas.config(width=img.width, height=img.height)

            if not holder['placed']:
                holder['placed'] = True
                top.update_idletasks()
                _place(top, self, img.width, img.height)
            else:
                top.geometry(f'{img.width}x{img.height}')
            top.deiconify()

        def on_click(e):
            layout = holder.get('layout') or {}
            x = e.x / scale
            y = e.y / scale
            for name, (x1, y1, x2, y2) in layout.get('pills', {}).items():
                if x1 <= x <= x2 and y1 <= y <= y2:
                    if name in ('today', 'week'):
                        state['mode'] = name
                        state['expanded'] = None
                    else:
                        state['metric'] = name
                    refresh()
                    return
            for exe, y1, y2 in layout.get('rows', []):
                if y1 <= y <= y2:
                    state['expanded'] = None if state['expanded'] == exe else exe
                    refresh()
                    return

        canvas.bind('<Button-1>', on_click)

        def _build(st):
            """返回 (PIL.Image, layout)。所有坐标在逻辑空间算，绘制时乘 k。"""
            s = st['scale']
            k = s * SS            # 逻辑 → 绘制像素
            today = datetime.now().strftime('%Y-%m-%d')

            if st['mode'] == 'today':
                return _build_today(st, today, k)
            return _build_week(st, today, k)

        # ---------- 今天：横向条形 ----------
        def _build_today(st, today, k):
            data = self._app_today_map(today)
            metric = st['metric']
            rows_all = [(exe, v['count'], v['seconds'])
                        for exe, v in data.items()]
            # 排序与条长都跟随当前指标：看次数就按次数排，看时长就按时长排
            if metric == 'seconds':
                rows = sorted(rows_all, key=lambda r: (r[2], r[1]),
                              reverse=True)[:TOP_N_BARS]
            else:
                rows = sorted(rows_all, key=lambda r: (r[1], r[2]),
                              reverse=True)[:TOP_N_BARS]
            total_count = sum(v['count'] for v in data.values())
            total_seconds = sum(v['seconds'] for v in data.values())

            expanded = st['expanded']
            n = len(rows)
            extra = EXPAND_H if any(r[0] == expanded for r in rows) else 0
            if n:
                height = TODAY_TOP + n * ROW_H + extra + 30
            else:
                height = TODAY_TOP + 40 + 30

            img = Image.new('RGB', (int(W * k), int(height * k)), WHITE)
            d = ImageDraw.Draw(img)
            layout = {'rows': [], 'pills': {}}

            _draw_header(d, st, k, layout)

            # 副标题 + 指标切换（次数 / 时长），与近 7 天保持一致
            # 只展示当前指标的总量：两个维度已经分开切了，不必再挤在一起
            if metric == 'seconds':
                subtitle = f'{_cn_date(today)} · 前台 {fmt_duration(total_seconds)}'
            else:
                subtitle = f'{_cn_date(today)} · 共 {fmt_count(total_count)} 次'
            draw_text(d, (PAD * k, 64 * k), subtitle,
                      load_font(11 * k), MUTED, anchor='lt')
            _draw_pills(d, k, layout, [
                ('count', '次数', metric == 'count'),
                ('seconds', '时长', metric == 'seconds'),
            ], right=W - PAD, y=58, font_size=10.5, height=24, small=True)

            if not rows:
                draw_text(d, (PAD * k, (TODAY_TOP + 6) * k),
                          '今天还没有记录，敲几下键盘再看看',
                          load_font(11 * k), FAINT, anchor='lt')
                return img, layout

            # 条长基准：跟随当前指标，避免用次数尺度画时长
            val_idx = 2 if metric == 'seconds' else 1
            max_val = max(r[val_idx] for r in rows) or 1
            f_name = load_font(12.5 * k, bold=True)
            f_cat = load_font(10.5 * k)
            f_num = load_font(10.5 * k)

            y = TODAY_TOP
            for exe, count, seconds in rows:
                info = self._resolve_exe(exe)
                is_open = (expanded == exe)

                draw_text(d, (BAR_LABEL_X * k, (y + 1) * k),
                          _ellipsis(info['name'], 8), f_name, INK, anchor='lt')
                draw_text(d, (BAR_LABEL_X * k, (y + 20) * k),
                          _category_label(info['category']), f_cat, FAINT,
                          anchor='lt')

                x0 = BAR_X0 * k
                x1 = BAR_X1 * k
                top_y = y * k
                bot_y = (y + BAR_H) * k
                d.rounded_rectangle([x0, top_y, x1, bot_y],
                                    radius=BAR_H * k / 2, fill=TRACK)
                w_ratio = (seconds if metric == 'seconds' else count) / max_val
                bx1 = x0 + max(BAR_H * k, (x1 - x0) * w_ratio)
                d.rounded_rectangle([x0, top_y, bx1, bot_y],
                                    radius=BAR_H * k / 2, fill=GREEN)

                row_bottom = y + ROW_H + (EXPAND_H if is_open else 0)
                layout['rows'].append((exe, y, row_bottom))

                if is_open:
                    # 展开只显示当前指标的值，不再两个维度并列
                    value_text = (fmt_duration(seconds) if metric == 'seconds'
                                  else f'{fmt_count(count)} 次')
                    draw_text(d, (BAR_X0 * k, (y + BAR_H + 7) * k),
                              value_text, f_num, GREEN_DARK, anchor='lt')
                    y += ROW_H + EXPAND_H
                else:
                    y += ROW_H

            draw_text(d, (PAD * k, (y + 6) * k),
                      '点击条目查看具体数值',
                      load_font(10 * k), FAINT, anchor='lt')
            return img, layout

        # ---------- 近 7 天：折线 ----------
        def _build_week(st, today, k):
            dates = date_range(today, WEEK_DAYS)
            daily = self._app_week_map(dates)
            metric = st['metric']
            idx = 0 if metric == 'count' else 1

            height = WEEK_LEGEND_Y + 26
            img = Image.new('RGB', (int(W * k), int(height * k)), WHITE)
            d = ImageDraw.Draw(img)
            layout = {'rows': [], 'pills': {}}

            _draw_header(d, st, k, layout)

            # 日期范围 + 指标切换
            draw_text(d, (PAD * k, 66 * k),
                      f'{_cn_date(dates[0])} — {_cn_date(dates[-1])}',
                      load_font(11 * k), MUTED, anchor='lt')
            _draw_pills(d, k, layout, [
                ('count', '次数', metric == 'count'),
                ('seconds', '时长', metric == 'seconds'),
            ], right=W - PAD, y=58, font_size=10.5, height=24, small=True)

            totals = {}
            for (app, _date), pair in daily.items():
                totals[app] = totals.get(app, 0) + pair[idx]
            series = []
            for app, _t in sorted(totals.items(),
                                  key=lambda kv: kv[1], reverse=True)[:TOP_N_LINES]:
                # 该应用当天没有记录 → None（缺数据、断开），不虚构 0
                vals = []
                for dd in dates:
                    pair = daily.get((app, dd))
                    vals.append(pair[idx] if pair else None)
                series.append((app, vals))

            if not series:
                empty_hint = True
            else:
                empty_hint = False

            all_vals = [v for _a, vals in series for v in vals
                        if v is not None]
            max_val = max(all_vals) if all_vals else 0
            top_val = nice_ceiling(max_val * 1.1) if max_val else 1
            span_x = CHART_RIGHT - CHART_LEFT
            span_y = CHART_BOTTOM - CHART_TOP
            n = len(dates)
            step = span_x / (n - 1) if n > 1 else span_x
            f_tick = load_font(9.5 * k)

            # 横向网格（极淡）；完全无数据时不标 Y 轴数字，避免出现
            # 0/0.3/0.5/0.8/1 这种没意义的刻度
            for i in range(5):
                y = CHART_BOTTOM - span_y * i / 4
                d.line([CHART_LEFT * k, y * k, CHART_RIGHT * k, y * k],
                       fill=DIVIDER, width=max(1, int(k * 0.5)))
                if max_val > 0:
                    draw_text(d, ((CHART_LEFT - 10) * k, y * k),
                              fmt_axis(top_val * i / 4, metric), f_tick,
                              FAINT, anchor='rm')

            # X 轴日期：同月只写日号（避免“10-26”“10-27”连着读成区间），
            # 跨月才写 M/D；今天加粗描黑。
            same_month = dates[0][:7] == dates[-1][:7]
            for i, dd in enumerate(dates):
                x = CHART_LEFT + step * i
                if same_month:
                    label = dd[8:].lstrip('0') or '0'
                else:
                    label = f'{int(dd[5:7])}/{int(dd[8:10])}'
                is_today = (i == n - 1)
                draw_text(d, (x * k, (CHART_BOTTOM + 10) * k), label,
                          load_font(9.5 * k, bold=is_today),
                          INK if is_today else FAINT, anchor='mt')

            # 没有记录的位置在基线上画一个空心灰点：
            # 七天都能看到「落点」，不再空一大块；空心也区别于有值的实心点，
            # 不会让人误以为那天真的敲了 0 下。
            covered = set()
            for _app, vals in series:
                for i, v in enumerate(vals):
                    if v is not None:
                        covered.add(i)
            dot_r = 3.0 * k
            dot_w = max(1, int(round(1.2 * k)))
            for i in range(n):
                if i in covered:
                    continue
                x = (CHART_LEFT + step * i) * k
                y = CHART_BOTTOM * k
                d.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r],
                          fill=WHITE, outline=FAINT, width=dot_w)

            # 折线（单调三次插值：不会过冲到负值，缺数据处断开）
            for si, (_app, values) in enumerate(series):
                color = LINE_COLORS[si % len(LINE_COLORS)]
                pts = []          # [(x, y)] 与 values 对齐，None 位置跳过
                for i, v in enumerate(values):
                    if v is None:
                        continue
                    x = CHART_LEFT + step * i
                    y = CHART_BOTTOM - (v / top_val) * span_y
                    pts.append((x * k, y * k))

                # 连续点才连线；缺失日期自然断开，不跨空档拉一条直线
                segments = []
                cur = []
                for i, v in enumerate(values):
                    if v is None:
                        if len(cur) >= 2:
                            segments.append(cur)
                        cur = []
                        continue
                    x = CHART_LEFT + step * i
                    y = CHART_BOTTOM - (v / top_val) * span_y
                    cur.append((x * k, y * k))
                if len(cur) >= 2:
                    segments.append(cur)

                line_w = max(1, int(round(2 * k)))
                for seg in segments:
                    path = monotone_path(seg, per_seg=16)
                    d.line(path, fill=color, width=line_w, joint='curve')

                r = 3.2 * k
                for (px, py) in pts:
                    d.ellipse([px - r, py - r, px + r, py + r],
                              fill=WHITE, outline=color,
                              width=max(1, int(round(1.6 * k))))

            # 图例；完全没有记录时在图例位置给一句提示（图表本体照常画）
            x = PAD
            f_leg = load_font(10 * k)
            if empty_hint:
                draw_text(d, (PAD * k, (WEEK_LEGEND_Y - 1) * k),
                          '最近 7 天还没有记录', f_leg, FAINT, anchor='lt')
                return img, layout
            for si, (app, values) in enumerate(series):
                color = LINE_COLORS[si % len(LINE_COLORS)]
                info = self._resolve_exe(app)
                d.rounded_rectangle([x * k, (WEEK_LEGEND_Y + 2) * k,
                                     (x + 9) * k, (WEEK_LEGEND_Y + 11) * k],
                                    radius=2 * k, fill=color)
                total = sum(v for v in values if v is not None)
                label = (f'{_ellipsis(info["name"], 7)} '
                         + (fmt_count(total) if metric == 'count'
                            else fmt_duration(total)))
                draw_text(d, ((x + 14) * k, (WEEK_LEGEND_Y - 1) * k),
                          label, f_leg, MUTED, anchor='lt')
                x += 14 + measure(d, label, f_leg) / k + 16
                if x > W - PAD - 40:
                    break          # 图例排不下就截断，不画出窗口边界
            return img, layout

        # ---------- 公共绘制 ----------
        def _draw_header(d, st, k, layout):
            draw_text(d, (PAD * k, TITLE_Y * k), '各软件敲键分布',
                      load_font(14 * k, bold=True), INK, anchor='lt')
            _draw_pills(d, k, layout, [
                ('today', '今天', st['mode'] == 'today'),
                ('week', '近 7 天', st['mode'] == 'week'),
            ], right=W - PAD, y=14, font_size=10.5, height=26)
            d.line([PAD * k, HEADER_H * k, (W - PAD) * k, HEADER_H * k],
                   fill=DIVIDER, width=max(1, int(k * 0.5)))

        def _draw_pills(d, k, layout, items, right, y, font_size,
                        height, small=False):
            """从右往左排一组胶囊按钮，并把命中区域写进 layout。"""
            font = load_font(font_size * k)
            pad_x = (10 if small else 12) * k
            gap = 6 * k
            widths = []
            for _key, label, _active in items:
                widths.append(measure(d, label, font) + pad_x * 2)

            x = right * k - sum(widths) - gap * (len(items) - 1)
            for i, (key, label, active) in enumerate(items):
                w = widths[i]
                box = [x, y * k, x + w, (y + height) * k]
                radius = height * k / 2
                if active:
                    d.rounded_rectangle(box, radius=radius, fill=GREEN)
                    fill = WHITE
                else:
                    d.rounded_rectangle(box, radius=radius, fill=TRACK)
                    fill = MUTED
                draw_text(d, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
                          label, font, fill, anchor='mm')
                # 命中区域换算回逻辑坐标
                layout['pills'][key] = (box[0] / k, box[1] / k,
                                        box[2] / k, box[3] / k)
                x += w + gap

        # ---------- 数据读取 ----------
        def _place(win, app, w, h):
            """把窗口贴到桌宠旁边，并夹紧在屏幕内。"""
            try:
                px = app.root.winfo_x() + app._frame_w + 8
                py = app.root.winfo_y()
                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                if px + w > sw:
                    px = app.root.winfo_x() - w - 8
                px = max(0, min(px, sw - w))
                py = max(0, min(py, sh - h))
                win.geometry(f'{w}x{h}+{int(px)}+{int(py)}')
            except Exception:
                logger.exception('分布窗口定位失败')

        refresh()

    # ---------- 数据辅助 ----------
    def _app_today_map(self, today):
        tracker = getattr(self, 'app_tracker', None)
        if tracker is not None:
            try:
                data = tracker.today()
                if data:
                    return data
            except Exception:
                logger.exception('读取今日应用统计失败')
        try:
            return db.get_app_stats(today)
        except Exception:
            logger.exception('读取今日应用统计（数据库）失败')
            return {}

    def _app_week_map(self, dates):
        try:
            daily = db.get_app_daily(dates[0], dates[-1])
        except Exception:
            logger.exception('读取近 7 天应用统计失败')
            daily = {}
        today = dates[-1]
        tracker = getattr(self, 'app_tracker', None)
        if tracker is not None:
            try:
                for exe, v in tracker.today().items():
                    daily[(exe, today)] = (v['count'], v['seconds'])
            except Exception:
                logger.exception('合并今日内存统计失败')
        return daily

    @staticmethod
    def _resolve_exe(exe):
        try:
            from app_aliases import resolve
            return resolve(exe)
        except Exception:
            return {'exe': exe, 'name': exe, 'category': 'other'}

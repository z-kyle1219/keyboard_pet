"""气泡系统：鎏金国潮卡片（玄黑底 + 描金 + 朱红）、MVP 徽章、冠军登场特效。

2026-10-20 改版（方案 2 · 鎏金国潮 gold）：
- 卡片由白底浅灰描边改为玄黑底 + 双层描金外框，配顶部烫金标题。
- 冠军徽章改直角金/朱红块（与国潮风一致，不用圆角）。
- 冠军登场特效的光环与放射闪光由品牌粉改为描金，避免与黑金卡打架。
- 全套色值集中在 theme.py 的 BUBBLE_* 常量，便于整体换肤。

作为 Mixin 混入 PetApp，self 语义保持不变。
"""
import math
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

import db
from logger import logger
from pet_ui.theme import (
    BUBBLE_BG,
    BUBBLE_BORDER,
    BUBBLE_EDGE,
    BUBBLE_GOLD,
    BUBBLE_GOLD_DARK,
    BUBBLE_GOLD_LIGHT,
    BUBBLE_INNER,
    BUBBLE_RED,
    BUBBLE_TEXT,
    TIP_BG,
    TIP_BTN,
    TIP_BTN_HOVER,
    TIP_BTN_TEXT,
    TIP_GRAD_FROM,
    TIP_GRAD_TO,
    TIP_RADIUS,
    TIP_TEXT,
    TRANSPARENT,
)

# 顶部烫金标题（字间距用空格拉开，营造国潮排版）
BUBBLE_TITLE = '◆  今 日 战 报  ◆'

# 关机提醒气泡文案与按钮
SHUTDOWN_TIP = '宝宝记得电脑关机哦~'
SHUTDOWN_BTN = '知道啦'


def _hex_to_rgb(color):
    """'#rrggbb' → (r, g, b) 整数三元组。"""
    c = color.lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class PopupMixin:
    """提供 _mvp_info / _show_bubble / _wrap_text / _render_card /
    _close_popup / _popup / _draw_mvp_badge / _badge_enter_animation / _toast。
    """

    def _mvp_info(self):
        """返回今天与昨天的冠军键信息，用于气泡展示。

        盲盒体验：今天的冠军在当天结束前不揭晓，显示「?」悬念；
        昨天已封存，才能展示真正的冠军键（揭晓谜底 + 上场动画）。
        """
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        today_mvp = '?'   # 今日盲盒：当天结束前不揭晓
        y_mvp = None      # 昨天冠军文案（无数据时保持 None）
        y_name = None
        tops = db.get_top_keys(yesterday)
        if tops:
            label = tops[0][0]
            if len(tops) > 1:
                label += f' 等{len(tops)}键'
            y_mvp = f'{label} {tops[0][1]}'
            y_name = label
        return today_mvp, y_mvp, y_name

    def _show_bubble(self):
        """左键单击：显示/关闭气泡（toggle）。

        再次点击桌宠可关闭正在显示的气泡；点击气泡本身也可关闭。
        气泡内展示：今天的总次数 + 今天MVP（盲盒「?」）+ 昨天MVP（揭晓）。
        """
        # toggle：若气泡已在显示，再点一下则关闭
        if self._active_popup is not None and self._active_popup.winfo_exists():
            self._close_popup()
            return
        count = self.manager.current_count()
        today_mvp, y_mvp, y_name = self._mvp_info()
        mvp_items = [
            {'label': '今天', 'display': f'今天MVP {today_mvp}', 'animate': False},
        ]
        if y_name is not None:
            mvp_items.append({'label': '昨天',
                              'display': f'昨天MVP ★ {y_mvp}',
                              'animate': True})
        body = (f'宝宝今天点击键盘的次数是 {count}\n'
                f'快去休息吧~')
        self._popup(body=body, duration=4000, mvps=mvp_items)

    def _wrap_text(self, text, font, wrap):
        """把文本按宽度 wrap 成多行，用于估算气泡尺寸。"""
        result = []
        for para in text.split('\n'):
            words = para.split(' ')
            cur = ''
            for w in words:
                trial = (cur + ' ' + w).strip() if cur else w
                if font.measure(trial) <= wrap:
                    cur = trial
                else:
                    if cur:
                        result.append(cur)
                    cur = w
            if cur:
                result.append(cur)
        return result

    def _render_card(self, w, h, radius=10):
        """绘制玄黑圆角卡片 + 双层描金外框（鎏金国潮）。

        - 外框：主金线（BUBBLE_BORDER）
        - 内框：暗金细线（BUBBLE_INNER）内缩 3px，形成"双线画框"质感
        """
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=radius,
            fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2,
        )
        d.rounded_rectangle(
            [3, 3, w - 4, h - 4], radius=max(0, radius - 2),
            outline=BUBBLE_INNER, width=1,
        )
        return img

    def _close_popup(self):
        """关闭当前气泡并清理状态（取消延迟回调）。

        注意：Python 3.13+ 的 tkinter 在 after_cancel 时会 deletecommand，
        而气泡的延迟回调又经 canvas 注册；随后递归 destroy 会对已删除的
        命令再次 deletecommand，抛出 TclError 令销毁半途中断——画布已毁、
        窗口本体仍映射在屏幕上，留下一个空框（且 _active_popup 已被
        置 None，后续点击永远无法真正关掉它）。因此 destroy 抛 TclError
        时兜底：在 Tcl 层直接销毁窗口本体，确保它从屏幕上消失。
        """
        b = self._active_popup
        self._active_popup = None
        self._active_popup_canvas = None
        if b is None:
            return
        for aid in list(self._popup_after_ids):
            try:
                b.after_cancel(aid)
            except Exception:
                pass
        self._popup_after_ids = []
        try:
            b.destroy()
        except tk.TclError:
            # destroy 半途中断的兜底：先藏起窗口，再于 Tcl 层销毁整个子树
            try:
                b.withdraw()
            except Exception:
                pass
            try:
                b.tk.call('destroy', b._w)
            except Exception:
                pass

    def _popup(self, body, wrap=240, duration=3000, mvps=None):
        """弹出一个自动适配内容的鎏金国潮卡片。

        结构自上而下：烫金标题 → 冠军徽章区 → 描金分隔线 → 正文。
        点击卡片本身即可关闭。mvps 为冠军徽章列表，每项形如
        {'label': '昨天', 'display': 'e 612', 'animate': True}。
        带 animate 的徽章（已揭晓）播放「冠军登场」动画；
        盲盒（今天）不播动画，显示「?」。
        """
        if self._active_popup is not None and self._active_popup.winfo_exists():
            self._close_popup()

        font = tkfont.Font(family='Microsoft YaHei UI', size=11)
        lines = self._wrap_text(body, font, wrap)
        line_h = font.metrics('linespace')
        pad_x, pad_y = 18, 16

        # 版式高度：标题 + 徽章区 + 分隔线
        title_h = 22
        title_gap = 6
        badge_h = 30
        badge_gap = 8
        badge_len = len(mvps) if mvps else 0
        badges_h = badge_len * (badge_h + badge_gap)
        divider_h = 21

        max_w = max((font.measure(l) for l in lines), default=wrap)
        badge_font = tkfont.Font(family='Microsoft YaHei UI', size=12,
                                 weight='bold')
        badges_req = max(
            (badge_font.measure(m['display']) for m in (mvps or [])),
            default=0) + 48
        title_font = tkfont.Font(family='Microsoft YaHei UI', size=11,
                                 weight='bold')
        title_w = title_font.measure(BUBBLE_TITLE)
        w = max(max_w + pad_x * 2, badges_req + 40, title_w + pad_x * 2, 200)
        h = (pad_y + title_h + title_gap + badges_h + divider_h
             + len(lines) * line_h + pad_y)
        h = max(h, 60)
        wrap_final = w - pad_x * 2

        x = self.root.winfo_x() + self._frame_w // 2 - w // 2
        y = self.root.winfo_y() - h - 8
        if y < 0:
            y = self.root.winfo_y() + self._frame_h + 8

        bubble = tk.Toplevel(self.root)
        # 先藏后显：先 withdraw，设好底色/无边框/位置，最后才 deiconify。
        # 否则 overrideredirect 会让窗口在底色还没设好时就先映射，
        # 闪出一下默认浅色底。
        bubble.withdraw()
        bubble.overrideredirect(True)
        bubble.attributes('-topmost', True)
        bubble.attributes('-alpha', 1.0)
        bubble.config(bg=BUBBLE_BG)
        bubble.geometry(f'{w}x{h}+{x}+{y}')

        card = self._render_card(w, h)
        card_tk = ImageTk.PhotoImage(card)

        canvas = tk.Canvas(bubble, width=w, height=h, bg=BUBBLE_BG,
                           highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_image(0, 0, image=card_tk, anchor='nw')

        y_cursor = pad_y
        # 顶部烫金标题
        canvas.create_text(
            w // 2, y_cursor + title_h // 2, text=BUBBLE_TITLE,
            fill=BUBBLE_GOLD, font=('Microsoft YaHei UI', 11, 'bold'),
            anchor='c',
        )
        y_cursor += title_h + title_gap

        # 冠军徽章区
        banner_meta = []
        for m in (mvps or []):
            cx, cy, geoms = self._draw_mvp_badge(
                canvas, m['display'], w, y_cursor, animate=m['animate'])
            banner_meta.append({
                'animate': m['animate'], 'cx': cx, 'cy': cy,
                'geoms': geoms,
            })
            y_cursor += badge_h + badge_gap

        # 描金分隔线（中间短横，两端留白）
        line_y = y_cursor + divider_h // 2
        canvas.create_line(
            pad_x + 20, line_y, w - pad_x - 20, line_y,
            fill=BUBBLE_BORDER, width=1,
        )
        canvas.create_text(
            w // 2, line_y, text='◆', fill=BUBBLE_GOLD,
            font=('Microsoft YaHei UI', 7), anchor='c',
        )
        y_cursor += divider_h

        # 正文
        canvas.create_text(
            pad_x, y_cursor, text=body, fill=BUBBLE_TEXT,
            font=('Microsoft YaHei UI', 11), justify='center',
            width=wrap_final, anchor='nw',
        )
        canvas._card_img = card_tk
        canvas.bind('<Button-1>', lambda e: self._close_popup())

        self._active_popup = bubble
        self._active_popup_canvas = canvas
        self._popup_offset = (x - self.root.winfo_x(),
                              y - self.root.winfo_y())
        self._popup_after_ids = []

        def _fade_out():
            try:
                for i in range(5, 0, -1):
                    aid = bubble.after(
                        int((5 - i) * 20),
                        lambda v=i / 5: bubble.attributes('-alpha', v))
                    self._popup_after_ids.append(aid)
                aid = bubble.after(110, self._close_popup)
                self._popup_after_ids.append(aid)
            except Exception:
                pass

        self._popup_after_ids.append(bubble.after(duration, _fade_out))

        # 卡片内容全部画好，再一次性显示（避免闪现浅色空窗）
        bubble.deiconify()

        # 对已揭晓的冠军徽章播放「冠军登场」动画（含摇摆 + 光环 + 闪光）
        for bm in banner_meta:
            if bm['animate']:
                self._badge_enter_animation(
                    canvas, bm['cx'], bm['cy'], bm['geoms'])

    def _draw_mvp_badge(self, canvas, badge_text, w, y_top, animate=False):
        """在 y_top 处绘制一个冠军徽章，返回 (cx, cy, geoms)。

        国潮风用直角块（不用圆角）：
        - animate=True（已揭晓）：朱红底 + 亮金字 + 描金边；
        - animate=False（盲盒）：描金底 + 深褐字 + 稍深金边。
        geoms 供「摇摆登场」绝对定位使用。
        """
        badge_h = 30
        cx = w // 2
        cy = y_top + badge_h // 2
        badge_font = tkfont.Font(family='Microsoft YaHei UI', size=12,
                                 weight='bold')
        text_w = badge_font.measure(badge_text)
        badge_w = min(max(80, text_w + 48), w - 40)
        x1 = cx - badge_w / 2
        x2 = cx + badge_w / 2
        y1 = y_top
        y2 = y_top + badge_h

        if animate:
            fill, text_color, outline = BUBBLE_RED, BUBBLE_GOLD_LIGHT, BUBBLE_GOLD
        else:
            fill, text_color, outline = BUBBLE_GOLD, BUBBLE_GOLD_DARK, BUBBLE_EDGE

        box = canvas.create_rectangle(x1, y1, x2, y2, fill=fill,
                                      outline=outline, width=1)
        txt = canvas.create_text(cx, cy, text=badge_text, fill=text_color,
                                 font=('Microsoft YaHei UI', 12, 'bold'))
        geoms = {'box': box, 'txt': txt, 'x1': x1, 'y1': y1,
                 'x2': x2, 'y2': y2, 'cx': cx, 'cy': cy, 'bw': badge_w}
        return cx, cy, geoms

    def _badge_enter_animation(self, canvas, cx, cy, geoms):
        """冠军登场：徽章摇摆登场（绝对定位、振幅衰减归位）+ 单圈扩散光环 + 放射闪光。

        光环与闪光统一改用描金色（国潮金），避免黑金卡上出现粉色光晕。
        特效元素打 'fx' 标签；每画一个特效就把徽章重新提到最顶层，
        保证动画全程文字清晰；动画结束后统一删除特效。
        """
        def _raise_badge():
            canvas.tag_raise(geoms['box'])
            canvas.tag_raise(geoms['txt'])

        try:
            # 1) 双圈光环先后向外扩散：新圈出现时删除上一圈，只保留单圈
            last_ring = {'a': None, 'b': None}

            def _ring(series, r, color, width):
                if last_ring[series] is not None:
                    canvas.delete(last_ring[series])
                oid = canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline=color, width=width, tags='fx')
                last_ring[series] = oid
                _raise_badge()

            for step in range(1, 8):
                aid = canvas.after(int(step * 40), (
                    lambda r=8 + step * 7: _ring('a', r, BUBBLE_GOLD, 2)))
                self._popup_after_ids.append(aid)
            for step in range(1, 8):
                aid = canvas.after(int(step * 40 + 160), (
                    lambda r=6 + step * 6: _ring('b', r, BUBBLE_GOLD_LIGHT, 1)))
                self._popup_after_ids.append(aid)

            # 2) 放射闪光：8 条线从中心向外，逐帧变长 + 微转
            prev_lines = []

            def _flash(rr, st):
                for lid in prev_lines:
                    canvas.delete(lid)
                prev_lines.clear()
                for a in range(8):
                    ang = a * math.pi / 4 + st * 0.15
                    x1 = cx + math.cos(ang) * 5
                    y1 = cy + math.sin(ang) * 5
                    x2 = cx + math.cos(ang) * rr
                    y2 = cy + math.sin(ang) * rr
                    lid = canvas.create_line(x1, y1, x2, y2,
                                             fill=BUBBLE_GOLD, width=1,
                                             tags='fx')
                    prev_lines.append(lid)
                _raise_badge()

            for step in range(1, 6):
                reach = 6 + step * 7
                aid = canvas.after(int(step * 45),
                                   lambda rr=reach, st=step: _flash(rr, st))
                self._popup_after_ids.append(aid)

            # 3) 徽章摇摆登场：水平绝对位移，振幅衰减后归位
            moves = []
            for step in range(0, 11):
                off = math.sin(step * 0.9) * 7 * (1 - step / 10.0)
                moves.append(off)
            moves.append(0)
            for i, off in enumerate(moves):
                def _sw(off=off):
                    canvas.coords(geoms['box'],
                                  geoms['x1'] + off, geoms['y1'],
                                  geoms['x2'] + off, geoms['y2'])
                    canvas.coords(geoms['txt'],
                                  geoms['cx'] + off, geoms['cy'])
                aid = canvas.after(int(i * 45), _sw)
                self._popup_after_ids.append(aid)

            # 4) 动画结束后清除所有光环与闪光
            def _cleanup_fx():
                canvas.delete('fx')
                _raise_badge()

            aid = canvas.after(800, _cleanup_fx)
            self._popup_after_ids.append(aid)
        except Exception:
            logger.exception('冠军登场动画失败')

    def _render_tip_card(self, w, h, radius=TIP_RADIUS):
        """关机提醒专用：粉→浅紫对角渐变圆角卡片（柔和精致）。

        用 PIL 画一条左上到右下的线性渐变，再用圆角遮罩把四角抠掉，
        避免依赖 Tk 不支持渐变。渐变失败时回退为纯色底，不影响使用。
        """
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        try:
            grad = Image.new('RGB', (w, h))
            px = grad.load()
            f = _hex_to_rgb(TIP_GRAD_FROM)
            t = _hex_to_rgb(TIP_GRAD_TO)
            denom = max(1, (w - 1) + (h - 1))
            for yy in range(h):
                for xx in range(w):
                    r = (xx + yy) / denom
                    px[xx, yy] = (
                        int(f[0] + (t[0] - f[0]) * r),
                        int(f[1] + (t[1] - f[1]) * r),
                        int(f[2] + (t[2] - f[2]) * r),
                    )
            mask = Image.new('L', (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, w - 1, h - 1], radius=radius, fill=255,
            )
            img.paste(grad, (0, 0), mask)
        except Exception:
            logger.exception('渐变卡片绘制失败，回退纯色底')
            ImageDraw.Draw(img).rounded_rectangle(
                [0, 0, w - 1, h - 1], radius=radius, fill=TIP_BG,
            )
        return img

    def _shutdown_prompt(self):
        """右键「退出」时的关机提醒气泡：不自动关闭，点「知道啦」才退出。

        与普通气泡不同：
        - 不注册到 self._active_popup，因此点击桌宠不会把它误关掉，
          必须由用户点按钮确认；
        - 不设 duration，永不自动消失，避免提醒一闪而过；
        - 记录到 self._shutdown_win，便于状态判断与防重复弹出。
        """
        # 已有一个在显示就不重复弹
        if self._shutdown_win is not None and self._shutdown_win.winfo_exists():
            return

        font = tkfont.Font(family='Microsoft YaHei UI', size=11)
        btn_font = tkfont.Font(family='Microsoft YaHei UI', size=11,
                               weight='bold')
        line_h = font.metrics('linespace')
        pad_x, pad_y = 22, 18
        gap = 14
        btn_w = btn_font.measure(SHUTDOWN_BTN) + 40
        btn_h = 30

        w = max(font.measure(SHUTDOWN_TIP) + pad_x * 2,
                btn_w + pad_x * 2, 210)
        h = pad_y + line_h + gap + btn_h + pad_y

        x = self.root.winfo_x() + self._frame_w // 2 - w // 2
        y = self.root.winfo_y() - h - 8
        if y < 0:
            y = self.root.winfo_y() + self._frame_h + 8

        bubble = tk.Toplevel(self.root)
        bubble.withdraw()
        bubble.overrideredirect(True)
        bubble.attributes('-topmost', True)
        # 用抠底色实现圆角镂空：圆角外透出桌面而非粉底
        bubble.config(bg=TRANSPARENT)
        bubble.wm_attributes('-transparentcolor', TRANSPARENT)
        bubble.geometry(f'{w}x{h}+{x}+{y}')

        card = self._render_tip_card(w, h)
        card_tk = ImageTk.PhotoImage(card)
        canvas = tk.Canvas(bubble, width=w, height=h, bg=TRANSPARENT,
                           highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_image(0, 0, image=card_tk, anchor='nw')
        canvas._card_img = card_tk

        # 正文
        canvas.create_text(
            w // 2, pad_y + line_h // 2, text=SHUTDOWN_TIP,
            fill=TIP_TEXT, font=('Microsoft YaHei UI', 11), anchor='c',
        )

        # 「知道啦」按钮（白底深粉字）
        by1 = pad_y + line_h + gap
        by2 = by1 + btn_h
        bx1 = w // 2 - btn_w // 2
        bx2 = w // 2 + btn_w // 2
        btn_box = canvas.create_rectangle(
            bx1, by1, bx2, by2, fill=TIP_BTN,
            outline=TIP_BTN, width=1,
        )
        btn_txt = canvas.create_text(
            w // 2, (by1 + by2) // 2, text=SHUTDOWN_BTN,
            fill=TIP_BTN_TEXT, font=('Microsoft YaHei UI', 11, 'bold'),
        )

        def _confirm(_e=None):
            # 关键：不能在本回调里直接 destroy 自己所属的 canvas 窗口，
            # 否则 Tk 会中止绑定脚本，后面的 root.destroy() 根本执行不到
            # （气泡消失了、程序却还活着，变成幽灵进程）。
            # 用 after(0) 把退出推迟到当前事件回调返回之后再执行。
            self._shutdown_win = None
            self.root.after(0, self.root.destroy)

        def _hover(_e):
            canvas.itemconfig(btn_box, fill=TIP_BTN_HOVER,
                              outline=TIP_BTN_HOVER)

        def _unhover(_e):
            canvas.itemconfig(btn_box, fill=TIP_BTN, outline=TIP_BTN)

        for item in (btn_box, btn_txt):
            canvas.tag_bind(item, '<Enter>', _hover)
            canvas.tag_bind(item, '<Leave>', _unhover)
            canvas.tag_bind(item, '<Button-1>', _confirm)

        self._shutdown_win = bubble
        bubble.deiconify()

    def _toast(self, msg):
        """在桌宠上方短暂显示一条提示。"""
        self._popup(body=msg, duration=2200)

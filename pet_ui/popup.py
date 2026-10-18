"""气泡系统：自适应圆角卡片、MVP 徽章、冠军登场特效。

从原 pet_ui.py 原样迁移。作为 Mixin 混入 PetApp，
self 语义保持不变，UI 表现与拆分前一致。
"""
import math
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

import db
from logger import logger
from pet_ui.theme import PRIMARY, TEXT_DARK


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

    def _render_card(self, w, h, radius=16):
        """绘制圆角白色卡片（浅灰描边，取代此前的粉色描边）。"""
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=radius,
            fill='white', outline=(229, 231, 235), width=1,
        )
        return img

    def _close_popup(self):
        """关闭当前气泡并清理状态（取消延迟回调）。

        注意：Python 3.13+ 的 tkinter 在 after_cancel 时会 deletecommand，
        而气泡的延迟回调又经 canvas 注册；随后递归 destroy 会对已删除的
        命令再次 deletecommand，抛出 TclError 令销毁半途中断——画布已毁、
        窗口本体仍映射在屏幕上，留下一个白色空框（且 _active_popup 已被
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
        """弹出一个自动适配内容的圆角气泡卡片。

        设计要点：
        - 依据文本测量结果自动计算宽高，保证内容装得下
        - 去掉此前的粉色描边，改用极浅灰色勾勒，简洁干净
        - 即时显示（无渐入延迟），点击气泡本身即可关闭
        mvps 为冠军徽章列表，每项形如
        {'label': '昨天', 'text': '...', 'display': 'e 612', 'animate': True}。
        带 animate 的徽章（已揭晓）会播放「冠军登场」动画；
        盲盒（今天）不播动画，显示「?」。
        """
        # 若已有气泡在显示，先关掉，避免叠在一起
        if self._active_popup is not None and self._active_popup.winfo_exists():
            self._close_popup()

        font = tkfont.Font(family='Microsoft YaHei UI', size=11)
        lines = self._wrap_text(body, font, wrap)
        line_h = font.metrics('linespace')
        pad_x, pad_y = 18, 14

        # 每个冠军徽章占用高度 + 间距
        badge_h = 30
        badge_gap = 8
        badge_len = len(mvps) if mvps else 0
        badges_h = badge_len * (badge_h + badge_gap)

        max_w = max((font.measure(l) for l in lines), default=wrap)
        # 徽章文字用 tkfont 实测宽度（随 DPI 缩放），据此撑大气泡，
        # 避免徽章椭圆被 w-40 截断后白字溢出到白色背景上"隐身"
        badge_font = tkfont.Font(family='Microsoft YaHei UI', size=12,
                                 weight='bold')
        badges_req = max(
            (badge_font.measure(m['display']) for m in (mvps or [])),
            default=0) + 48  # 椭圆左右各留 24px 内边距
        w = max(max_w + pad_x * 2, badges_req + 40, 200)
        h = len(lines) * line_h + pad_y * 2 + badges_h
        h = max(h, 46)
        wrap_final = w - pad_x * 2

        x = self.root.winfo_x() + self._frame_w // 2 - w // 2
        y = self.root.winfo_y() - h - 8
        if y < 0:
            y = self.root.winfo_y() + self._frame_h + 8

        bubble = tk.Toplevel(self.root)
        bubble.overrideredirect(True)
        bubble.attributes('-topmost', True)
        bubble.attributes('-alpha', 1.0)
        bubble.config(bg='white')
        bubble.geometry(f'{w}x{h}+{x}+{y}')

        card = self._render_card(w, h)
        card_tk = ImageTk.PhotoImage(card)

        canvas = tk.Canvas(bubble, width=w, height=h, bg='white',
                           highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_image(0, 0, image=card_tk, anchor='nw')

        # 顶部冠军徽章区（每个占一行，存下坐标与句柄供动画使用）
        y_cursor = pad_y
        banner_meta = []
        for m in (mvps or []):
            cx, cy, geoms = self._draw_mvp_badge(
                canvas, m['display'], w, y_cursor, animate=m['animate'])
            banner_meta.append({
                'animate': m['animate'], 'cx': cx, 'cy': cy,
                'geoms': geoms,
            })
            y_cursor += badge_h + badge_gap

        text_y = y_cursor
        canvas.create_text(
            pad_x, text_y, text=body, fill=TEXT_DARK,
            font=('Microsoft YaHei UI', 11), justify='center',
            width=wrap_final, anchor='nw',
        )
        canvas._card_img = card_tk
        # 点击气泡本体可关闭
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

        # 对已揭晓的冠军徽章播放「冠军登场」动画（含摇摆 + 光环 + 闪光）
        for bm in banner_meta:
            if bm['animate']:
                self._badge_enter_animation(
                    canvas, bm['cx'], bm['cy'], bm['geoms'])

    def _draw_mvp_badge(self, canvas, badge_text, w, y_top, animate=False):
        """在 y_top 处绘制一个冠军徽章，返回 (cx, cy, geoms)。

        animate=True 表示已揭晓（粉色实心 + 白色文字）；
        animate=False 表示盲盒（金色实心 + 深琥珀文字）。
        geoms 形如 {'box': bid, 'txt': tid, 'x1':.., 'y1':.., 'x2':..,
        'y2':.., 'cx':.., 'cy':.., 'bw':..}，供「摇摆登场」绝对定位。
        """
        badge_h = 30
        cx = w // 2
        cy = y_top + badge_h // 2
        # 用 tkfont 实测文字宽度（随系统 DPI 缩放），再加左右内边距，
        # 替代原先 16*len+48 的粗略估算——高 DPI 下估算偏小，
        # 会导致白色文字超出粉色底、与白色背景混在一起"隐身"
        badge_font = tkfont.Font(family='Microsoft YaHei UI', size=12,
                                 weight='bold')
        text_w = badge_font.measure(badge_text)
        badge_w = min(max(80, text_w + 48), w - 40)
        x1 = cx - badge_w / 2
        x2 = cx + badge_w / 2
        y1 = y_top
        y2 = y_top + badge_h
        color = PRIMARY if animate else '#f0a92e'
        text_color = 'white' if animate else '#5a3d00'
        box = canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
        txt = canvas.create_text(cx, cy, text=badge_text, fill=text_color,
                                 font=('Microsoft YaHei UI', 12, 'bold'))
        geoms = {'box': box, 'txt': txt, 'x1': x1, 'y1': y1,
                 'x2': x2, 'y2': y2, 'cx': cx, 'cy': cy, 'bw': badge_w}
        return cx, cy, geoms

    def _badge_enter_animation(self, canvas, cx, cy, geoms):
        """冠军登场：徽章摇摆登场（绝对定位、振幅衰减归位）+ 单圈扩散光环 + 放射闪光。

        Canvas 逐帧重绘缩放文本易模糊，故「摇摆」用水平绝对位移模拟，
        叠加向外扩散的光环与放射线，营造「冠军登场」的聚光效果。
        特效元素统一打 'fx' 标签；且每画一个特效就把徽章（底条+文字）
        重新提到最顶层，保证动画全程文字清晰可见；
        动画结束后统一删除特效，只留干净的徽章。
        """
        def _raise_badge():
            # Canvas 中后创建的元素在上层，特效会盖住先画的徽章文字，
            # 故每次画完特效后把徽章底条和文字重新提到最顶
            canvas.tag_raise(geoms['box'])
            canvas.tag_raise(geoms['txt'])

        try:
            # 1) 双圈光环先后向外扩散：新圈出现时删除上一圈，只保留单圈扩散
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
                    lambda r=8 + step * 7: _ring('a', r, PRIMARY, 2)))
                self._popup_after_ids.append(aid)
            for step in range(1, 8):
                aid = canvas.after(int(step * 40 + 160), (
                    lambda r=6 + step * 6: _ring('b', r, '#ffb3c9', 1)))
                self._popup_after_ids.append(aid)

            # 2) 放射闪光：8 条线从中心向外（逐帧变长 + 微转），
            #    每帧先清除上一帧的线条，避免线条层层堆积
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
                                             fill=PRIMARY, width=1,
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
            # 末尾确保回到原位
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

            # 4) 动画全部结束后清除所有光环与闪光，露出干净的徽章文字
            def _cleanup_fx():
                canvas.delete('fx')
                _raise_badge()

            aid = canvas.after(800, _cleanup_fx)
            self._popup_after_ids.append(aid)
        except Exception:
            logger.exception('冠军登场动画失败')

    def _toast(self, msg):
        """在桌宠上方短暂显示一条提示。"""
        self._popup(body=msg, duration=2200)

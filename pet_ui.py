"""桌宠界面：透明漂浮窗 + 左键气泡 + 右键菜单。

技术要点：
- overrideredirect + transparentcolor：可漂浮、透明抠底、无标题栏
- 通过 e.x_root / e.y_root 计算位移实现拖拽
- 左键单击（未拖动）弹气泡；右键弹菜单

UI 优化（2026-10-12）：
- 气泡按内容自动适配宽高，解决文字装不下问题
- 去掉粉色描边，改用极浅灰色勾勒，简洁干净
- 改为 toggle：左键点一下显示、再点一下关闭；点气泡本体也可关闭
"""
import os
import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from tkinter import filedialog
from PIL import Image, ImageDraw, ImageTk, ImageFilter

import autostart
import config
import db
from logger import logger

# 用这种不常见颜色做"抠底"透明色
TRANSPARENT = '#ff00ff'

# 时尚配色：主色（水母粉）、深色文字、浅色底
PRIMARY = '#ff7aa2'
PRIMARY_DARK = '#ff4d80'
TEXT_DARK = '#2b2b2b'
TEXT_MUTED = '#8a8a8a'


def make_pet_image(img, size):
    """把任意图片处理成圆角、柔化边缘的浮动桌宠图标。

    对 JPG 等无透明通道的图片：居中裁切为正方形、加圆角矩形遮罩、
    边缘羽化，避免出现生硬的矩形图片块。
    """
    # 居中裁切成正方形
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)

    # 圆角遮罩（RGBA），半径取约 1/4 尺寸
    radius = max(8, int(size * 0.28))
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size, size], radius=radius, fill=255)

    # 边缘羽化：在遮罩上再叠加一圈渐变，让边没那么“硬”
    mask = mask.filter(ImageFilter.GaussianBlur(size * 0.03))

    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _placeholder_icon():
    """生成一个简单的占位水母图标（RGBA），用于图片加载失败时兜底。"""
    size = config.PET_SIZE
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 身体
    d.ellipse([18, 12, 102, 78], fill=(255, 170, 190, 210))
    d.ellipse([36, 26, 86, 66], fill=(255, 214, 224, 160))
    # 触须
    for t in range(5):
        base_x = 30 + t * 14
        pts = []
        for step in range(0, 40):
            y = 72 + step * 1.1
            x = base_x + math.sin(step / 4.0 + t) * 6
            pts.append((x, y))
        d.line(pts, fill=(255, 170, 190, 180), width=2)
    return img


class PetApp:
    def __init__(self, root, manager):
        self.root = root
        self.manager = manager
        self.config = config.load_config()
        self._press_origin = None
        self._moved = False
        self._icon = None
        # 当前显示的浮动气泡（拖拽时跟随）
        self._active_popup = None
        self._active_popup_canvas = None
        self._popup_offset = (0, 0)
        self._popup_after_ids = []
        # 开机自启动当前状态
        self._autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        self._setup_window()
        self._load_icon()

    # ---------- 窗口基础 ----------
    def _setup_window(self):
        self.root.overrideredirect(True)               # 去掉标题栏/边框
        self.root.attributes('-topmost', True)         # 始终置顶
        self.root.config(bg=TRANSPARENT)               # 背景设为透明色
        self.root.wm_attributes('-transparentcolor', TRANSPARENT)  # 抠掉该颜色
        self.root.geometry(f'{config.PET_SIZE}x{config.PET_SIZE}+120+120')

    # ---------- 图标 ----------
    def _load_icon(self):
        # 直接使用用户手动上传到 assets/ 的图标
        icon_path = self.config.get('icon_path')
        if not icon_path or not os.path.exists(icon_path):
            icon_path = config.PET_ICON
        try:
            img = Image.open(icon_path).convert('RGBA')
        except Exception:
            # 图片损坏/路径错误：记录日志并回退到内置占位图标，不崩溃
            logger.exception('图标加载失败，回退到占位图：%s', icon_path)
            img = _placeholder_icon()

        img = make_pet_image(img, config.PET_SIZE)
        self._photo = ImageTk.PhotoImage(img)

        if self._icon is not None:
            self._icon.destroy()
        self._icon = tk.Label(self.root, image=self._photo, bg=TRANSPARENT, bd=0)
        self._icon.pack(fill='both', expand=True)

        # 事件挂在图标上
        self._icon.bind('<ButtonPress-1>', self._on_press)
        self._icon.bind('<B1-Motion>', self._on_motion)
        self._icon.bind('<ButtonRelease-1>', self._on_release)
        self._icon.bind('<Button-3>', self._show_menu)

    # ---------- 拖拽 ----------
    def _on_press(self, e):
        self._press_origin = (e.x_root, e.y_root)
        self._win_origin = (self.root.winfo_x(), self.root.winfo_y())
        self._moved = False

    def _on_motion(self, e):
        if self._press_origin is None:
            return
        dx = e.x_root - self._press_origin[0]
        dy = e.y_root - self._press_origin[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        self.root.geometry(
            f'+{self._win_origin[0] + dx}+{self._win_origin[1] + dy}')
        # 让悬浮气泡跟随图标一起移动
        if self._active_popup is not None and self._active_popup.winfo_exists():
            try:
                nx = self.root.winfo_x() + self._popup_offset[0]
                ny = self.root.winfo_y() + self._popup_offset[1]
                self._active_popup.geometry(
                    f'+{nx}+{max(0, ny)}')
            except Exception:
                pass

    def _on_release(self, e):
        # 按住未拖动视为"单击" → 显示/关闭气泡
        if not self._moved:
            self._show_bubble()
        self._press_origin = None

    # ---------- 交互 ----------
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
        """关闭当前气泡并清理状态（取消延迟回调）。"""
        b = self._active_popup
        self._active_popup = None
        self._active_popup_canvas = None
        if b is None:
            return
        try:
            for aid in self._popup_after_ids:
                try:
                    b.after_cancel(aid)
                except Exception:
                    pass
            b.destroy()
        except Exception:
            pass
        self._popup_after_ids = []

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
        w = max(max_w + pad_x * 2, 200)
        h = len(lines) * line_h + pad_y * 2 + badges_h
        h = max(h, 46)
        wrap_final = w - pad_x * 2

        x = self.root.winfo_x() + config.PET_SIZE // 2 - w // 2
        y = self.root.winfo_y() - h - 8
        if y < 0:
            y = self.root.winfo_y() + config.PET_SIZE + 8

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
        geoms 形如 {'oval': oid, 'txt': tid, 'x1':.., 'y1':.., 'x2':..,
        'y2':.., 'cx':.., 'cy':.., 'bw':..}，供「摇摆登场」绝对定位。
        """
        badge_h = 30
        cx = w // 2
        cy = y_top + badge_h // 2
        badge_w = min(max(80, 16 * len(badge_text) + 48), w - 40)
        x1 = cx - badge_w / 2
        x2 = cx + badge_w / 2
        y1 = y_top
        y2 = y_top + badge_h
        color = PRIMARY if animate else '#f0a92e'
        text_color = 'white' if animate else '#5a3d00'
        oval = canvas.create_oval(x1, y1, x2, y2, fill=color, outline='')
        txt = canvas.create_text(cx, cy, text=badge_text, fill=text_color,
                                 font=('Microsoft YaHei UI', 12, 'bold'))
        geoms = {'oval': oval, 'txt': txt, 'x1': x1, 'y1': y1,
                 'x2': x2, 'y2': y2, 'cx': cx, 'cy': cy, 'bw': badge_w}
        return cx, cy, geoms

    def _badge_enter_animation(self, canvas, cx, cy, geoms):
        """冠军登场：徽章摇摆登场（绝对定位、振幅衰减归位）+ 双圈光环 + 放射闪光。

        Canvas 逐帧重绘缩放文本易模糊，故「摇摆」用水平绝对位移模拟，
        叠加向外扩散的光环与放射线，营造「冠军登场」的聚光效果。
        """
        import math
        try:
            # 1) 双圈光环先后向外扩散
            for step in range(1, 8):
                r = 8 + step * 7
                aid = canvas.after(int(step * 40), (
                    lambda r=r: canvas.create_oval(
                        cx - r, cy - r, cx + r, cy + r,
                        outline=PRIMARY, width=2)))
                self._popup_after_ids.append(aid)
            for step in range(1, 8):
                r = 6 + step * 6
                aid = canvas.after(int(step * 40 + 160), (
                    lambda r=r: canvas.create_oval(
                        cx - r, cy - r, cx + r, cy + r,
                        outline='#ffb3c9', width=1)))
                self._popup_after_ids.append(aid)

            # 2) 放射闪光：8 条线从中心向外（逐帧变长 + 微转）
            for step in range(1, 6):
                reach = 6 + step * 7

                def _flash(rr=reach, st=step):
                    for a in range(8):
                        ang = a * math.pi / 4 + st * 0.15
                        x1 = cx + math.cos(ang) * 5
                        y1 = cy + math.sin(ang) * 5
                        x2 = cx + math.cos(ang) * rr
                        y2 = cy + math.sin(ang) * rr
                        canvas.create_line(x1, y1, x2, y2,
                                           fill=PRIMARY, width=1)

                aid = canvas.after(int(step * 45), _flash)
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
                    canvas.coords(geoms['oval'],
                                  geoms['x1'] + off, geoms['y1'],
                                  geoms['x2'] + off, geoms['y2'])
                    canvas.coords(geoms['txt'],
                                  geoms['cx'] + off, geoms['cy'])
                aid = canvas.after(int(i * 45), _sw)
                self._popup_after_ids.append(aid)
        except Exception:
            logger.exception('冠军登场动画失败')

    def _show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0,
                       font=('Microsoft YaHei UI', 10),
                       bg='white', fg=TEXT_DARK,
                       activebackground='#1f1f1f', activeforeground='white')
        menu.add_command(label='最近 7 天', command=lambda: self._show_table(7))
        menu.add_command(label='历史所有', command=lambda: self._show_table(None))
        menu.add_separator()
        menu.add_command(label='更换图标', command=self._change_icon)
        # 开机自启动开关（勾选表示已开启）
        menu.add_checkbutton(
            label='开机自启动',
            onvalue=True, offvalue=False,
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        menu.add_separator()
        menu.add_command(label='退出', command=self.root.destroy)
        menu.tk_popup(e.x_root, e.y_root)

    def _toggle_autostart(self):
        """切换开机自启动状态。"""
        enabled = autostart.toggle()
        # 让 checkbutton 状态与真实结果保持一致
        self._autostart_var.set(enabled)
        msg = '开机自启动已开启' if enabled else '开机自启动已关闭'
        self._toast(msg)

    def _toast(self, msg):
        """在桌宠上方短暂显示一条提示。"""
        self._popup(body=msg, duration=2200)

    def _show_table(self, days):
        """以表格形式展示历史点击次数。

        days: 7 表示近 7 天，None 表示全部历史。
        使用 ttk.Treeview 渲染「日期 | 次数」两列表格。
        """
        # 打开表格前，先用同一个原子快照完成「写库 + 取值」，
        # 保证表头「今天」与表格里「今天」那一行是同一个数字，
        # 彻底消除实时值与快照之间的竞态偏差（含 60s 落库滞后）。
        today_count = self.manager.snapshot()

        if days is None:
            rows = db.get_daily_mvp()
            title = '历史所有'
        else:
            rows = db.get_daily_mvp(days)
            title = f'最近 {days} 天'

        top = tk.Toplevel(self.root)
        top.title(f'点击次数历史 — {title}')
        top.attributes('-topmost', True)
        top.config(bg='white')
        top.resizable(False, False)

        # 顶部：今天次数 + 标题（黑白头部，不再用粉色）
        # 注意：不再用 pack_propagate(False)+固定高度，避免文字被裁切
        header = tk.Frame(top, bg='#1f1f1f')
        header.pack(fill='x')
        tk.Label(
            header, text='今天的点击',
            font=('Microsoft YaHei UI', 12, 'bold'),
            bg='#1f1f1f', fg='white',
        ).pack(side='left', padx=(18, 10), pady=16)
        tk.Label(
            header, text=f'{today_count} 次',
            font=('Segoe UI', 20, 'bold'),
            bg='#1f1f1f', fg='white',
        ).pack(side='left', padx=(0, 18), pady=10)

        # 副标题：展示的区间
        tk.Label(
            top, text=title, bg='white', fg=TEXT_MUTED,
            font=('Microsoft YaHei UI', 10),
        ).pack(pady=(10, 2))

        # 表格容器（固定大小，让三列完整展示）
        frame = tk.Frame(top, bg='white')
        frame.pack(padx=14, pady=(0, 14))
        frame.config(width=500, height=420)
        frame.pack_propagate(False)

        # Treeview 表格（清晰大字体 + 隔行配色）；风格失败不阻断窗口
        try:
            style = ttk.Style(top)
            style.theme_use('clam')
            style.configure(
                'Pet.Treeview',
                font=('Microsoft YaHei UI', 11),
                rowheight=32, background='#fafafa', fieldbackground='#fafafa',
                foreground=TEXT_DARK,
            )
            style.configure(
                'Pet.Treeview.Heading',
                font=('Microsoft YaHei UI', 11, 'bold'),
                background='#1f1f1f', foreground='white',
            )
            style.map('Pet.Treeview.Heading',
                      background=[('active', '#3a3a3a')])
        except Exception:
            logger.exception('表格样式设置失败，使用默认样式')

        columns = ('date', 'count', 'mvp')
        tree = ttk.Treeview(frame, columns=columns, show='headings',
                            height=14, style='Pet.Treeview')
        tree.heading('date', text='日期')
        tree.heading('count', text='次数')
        tree.heading('mvp', text='MVP 键')
        tree.column('date', width=180, anchor='center')
        tree.column('count', width=110, anchor='center')
        tree.column('mvp', width=200, anchor='center')

        # 隔行变色
        tree.tag_configure('odd', background='#ffffff')
        tree.tag_configure('even', background='#f3f3f3')
        tree.tag_configure('mvp', foreground=PRIMARY_DARK)
        tree.tag_configure('blind', foreground='#b5790b')  # 盲盒「?」用金色

        # 滚动条（纵向 + 横向，防止长键名/MVP文案被截断）
        vsb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.pack_propagate(False)

        if rows:
            for i, (dt, cnt, mvp) in enumerate(rows):
                has_mvp = mvp != '-'
                is_blind = mvp == '?'
                tags = ('odd',) if i % 2 else ('even',)
                if is_blind:
                    tags += ('blind',)
                elif has_mvp:
                    tags += ('mvp',)
                tree.insert('', 'end', values=(dt, cnt, mvp), tags=tags)
        else:
            tree.insert('', 'end', values=('暂无记录', '-', '-'))

        # 把窗口贴在桌宠右侧（放不下则放左侧），并夹紧到屏幕内，
        # 避免默认摆位跑到很远或部分移出屏幕导致文字被裁。
        top.update_idletasks()
        win_w = top.winfo_reqwidth()
        win_h = top.winfo_reqheight()
        px = self.root.winfo_x() + config.PET_SIZE + 8
        py = self.root.winfo_y()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        if px + win_w > sw:
            px = self.root.winfo_x() - win_w - 8
        px = max(0, min(px, sw - win_w))
        py = max(0, min(py, sh - win_h))
        top.geometry(f'+{int(px)}+{int(py)}')

    def _change_icon(self):
        path = filedialog.askopenfilename(
            title='选择桌宠图标',
            filetypes=[('图片文件', '*.png *.gif *.jpg *.jpeg *.bmp'),
                       ('所有文件', '*.*')],
        )
        if not path:
            return
        self.config['icon_path'] = path
        config.save_config(self.config)
        self._load_icon()

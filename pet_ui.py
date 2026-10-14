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
    def _show_bubble(self):
        """左键单击：显示/关闭气泡（toggle）。

        再次点击桌宠可关闭正在显示的气泡；点击气泡本身也可关闭。
        """
        # toggle：若气泡已在显示，再点一下则关闭
        if self._active_popup is not None and self._active_popup.winfo_exists():
            self._close_popup()
            return
        count = self.manager.current_count()
        text = f'宝宝今天点击键盘的次数是 {count}\n快去休息吧~'
        self._popup(text=text, duration=4000)

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

    def _popup(self, text, wrap=240, duration=3000):
        """弹出一个自动适配内容的圆角气泡卡片。

        设计要点：
        - 依据文本测量结果自动计算宽高，保证内容装得下
        - 去掉此前的粉色描边，改用极浅灰色勾勒，简洁干净
        - 即时显示（无渐入延迟），点击气泡本身即可关闭
        """
        # 若已有气泡在显示，先关掉，避免叠在一起
        if self._active_popup is not None and self._active_popup.winfo_exists():
            self._close_popup()

        font = tkfont.Font(family='Microsoft YaHei UI', size=11)
        lines = self._wrap_text(text, font, wrap)
        line_h = font.metrics('linespace')
        pad_x, pad_y = 18, 14

        max_w = max((font.measure(l) for l in lines), default=wrap)
        w = max(max_w + pad_x * 2, 180)
        h = len(lines) * line_h + pad_y * 2
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
        canvas.create_text(
            pad_x, pad_y, text=text, fill=TEXT_DARK,
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
        self._popup(text=msg, duration=2200)

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
            rows = db.get_all_days()
            title = '历史所有'
        else:
            rows = db.get_recent_days(days)
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

        # 表格容器
        frame = tk.Frame(top, bg='white')
        frame.pack(padx=14, pady=(0, 14), fill='both', expand=True)

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

        columns = ('date', 'count')
        tree = ttk.Treeview(frame, columns=columns, show='headings',
                            height=10, style='Pet.Treeview')
        tree.heading('date', text='日期')
        tree.heading('count', text='次数')
        tree.column('date', width=160, anchor='center')
        tree.column('count', width=90, anchor='center')

        # 隔行变色
        tree.tag_configure('odd', background='#ffffff')
        tree.tag_configure('even', background='#f3f3f3')

        # 滚动条
        vsb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        if rows:
            for i, (dt, cnt) in enumerate(rows):
                tree.insert('', 'end', values=(dt, cnt),
                            tags=('odd' if i % 2 else 'even'))
        else:
            tree.insert('', 'end', values=('暂无记录', '-'))

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

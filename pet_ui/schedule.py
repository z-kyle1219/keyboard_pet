"""日程表：独立日程窗口（卡片式、可勾选、带进度条）+ 桌宠头顶角标。

按用户定稿实现（方案 A 分离式）：
- 点击桌宠 → 日程窗口（下方）+ 统计气泡（上方）分离展示。
- 日程窗口为独立 Toplevel，卡片式排列，可勾选，带完成进度与进度条。
- 角标常驻桌宠头顶：显示「N 待办」；存在临近截止（<=12 小时）的
  未完成待办时，角标由常规色变红。

UI 主题（2026-10-20 改版）：
- 勾选框从原生 tk.Checkbutton 换成自绘 RoundCheckbox（26px 圆形，
  hover 加深，勾选填充该行状态色）——解决"框太小、颜色总是粉的"。
- 每行按紧急度为勾选框与日期胶囊上色：
  已过期=红 / 今天=青 / 3 天内=黄绿 / 更远=紫。
- 进度条改为青→紫渐变；整体深空底霓虹风。
- 全套色值集中在 theme.py，改 UI_THEME 可整体切回清新明亮。

作为 Mixin 混入 PetApp，self 语义与 popup.py / table.py 一致。
"""
import tkinter as tk
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageTk

import db_todo
from logger import logger
from pet_ui.checkbox import RoundCheckbox
from pet_ui.theme import (
    ACC_FUTURE,
    ACC_OVERDUE,
    ACC_SOON,
    ACC_TODAY,
    BAR_FROM,
    BAR_TO,
    CHECKBOX_SIZE,
    TRANSPARENT,
    UI_BG,
    UI_BORDER,
    UI_FAINT,
    UI_MUTED,
    UI_TEXT,
    tint,
)


class ScheduleMixin:
    """提供日程展示与角标能力。

    新增到 PetApp 的职责：
    - _refresh_badge()          刷新头顶角标（数量 + 颜色）
    - _render_badge_image()     绘制「N 待办」角标图片
    - _show_schedule()          打开独立日程窗口
    - _on_task_toggle()         勾选/取消勾选后的回调
    """

    # ---------- 角标 ----------
    def _refresh_badge(self):
        """重算待办数量与临期状态，重绘头顶角标。

        每次数据变化（新增/勾选/启动）后调用。角标图片叠加在图标
        Label 之外的独立 Label 上，保持与图标分离便于重绘。
        """
        if not hasattr(self, '_badge_label'):
            return
        count = db_todo.get_pending_count()
        urgent = db_todo.has_urgent_pending()
        img = self._render_badge_image(count, urgent)
        self._badge_image = img
        try:
            self._badge_label.configure(image=img)
        except Exception:
            logger.exception('角标刷新失败')
            return
        # 角标位置：图标右上角。若窗口未就绪，先跳过定位。
        try:
            self._place_badge()
        except Exception:
            pass

    def _render_badge_image(self, count, urgent):
        """绘制角标图片：圆角胶囊，底色随 urgent 在常规/警示间切换。

        角标要「小而清晰」：固定高度约 22px，宽度随文字自适应。
        文字用 PIL 的 ImageFont 绘制（不能用 tkinter 的 tkfont.Font，
        后者不能传给 Pillow 的 ImageDraw.text）。
        """
        text = f'{count} 待办'
        try:
            font = ImageFont.truetype('msyh.ttc', 11)
        except Exception:
            font = None
        # 用 PIL 取文字宽度
        if font is not None:
            text_w = int(ImageDraw.Draw(Image.new('RGBA', (1, 1))).textlength(
                text, font=font))
        else:
            text_w = len(text) * 12
        h = 22
        pad_x = 8
        w = text_w + pad_x * 2
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = ACC_OVERDUE if urgent else ACC_TODAY
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                            fill=color, outline=None)
        ink = self._ink_on(color)
        if font is not None:
            d.text((pad_x, h // 2), text, fill=ink, font=font, anchor='lm')
        else:
            d.text((pad_x, h // 2), text, fill=ink, anchor='lm')
        return ImageTk.PhotoImage(img)

    @staticmethod
    def _ink_on(color):
        """按底色亮度选文字色：亮底压深色，暗底用白。"""
        try:
            c = color.lstrip('#')
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            return '#06121a' if lum > 150 else '#ffffff'
        except Exception:
            return '#ffffff'

    def _place_badge(self):
        """把角标 Label 定位到图标右上角（相对桌宠窗口）。"""
        if not hasattr(self, '_badge_label') or self._badge_label is None:
            return
        bw = self._badge_label.winfo_reqwidth()
        x = self._frame_w - bw
        y = 0
        if x < 0:
            x = 0
        self._badge_label.place(x=x, y=y)

    def _setup_badge(self):
        """在图标上叠加一个角标 Label（调用时机：图标加载完成后）。

        角标与图标是两个独立控件：Tk 的事件只发给指针下那个控件，
        不会冒泡到父控件。若角标不绑定事件，点击落在它覆盖的区域
        （宠物右上角）时会被它吞掉，表现为「有时左键点桌宠没反应」。
        因此这里把与图标相同的拖拽/单击/右键处理函数也绑到角标上。
        """
        old = getattr(self, '_badge_label', None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
        # 底色必须是抠色 TRANSPARENT：桌宠窗口是透明窗，
        # 角标若用不透明底色会在宠物右上角露出一个方块
        self._badge_label = tk.Label(
            self.root, text='', bg=TRANSPARENT, bd=0, image=None,
        )
        self._badge_label.configure(highlightthickness=0, takefocus=0)
        self._bind_pet_events(self._badge_label)
        self._refresh_badge()

    # ---------- 行配色 ----------
    @staticmethod
    def _row_accent(due_at, done):
        """按紧急度返回该行的状态色（勾选框 / 日期胶囊共用）。

        已过期=红，今天=青，3 天内=黄绿，更远=紫。
        """
        try:
            due = datetime.strptime(due_at, '%Y-%m-%d %H:%M')
        except Exception:
            return ACC_FUTURE
        now = datetime.now()
        if due < now:
            return ACC_OVERDUE
        if due.date() == now.date():
            return ACC_TODAY
        if (due - now).days <= 3:
            return ACC_SOON
        return ACC_FUTURE

    # ---------- 日程窗口 ----------
    def _show_schedule(self):
        """打开独立日程窗口（卡片式 + 可勾选 + 渐变进度条）。

        窗口位于桌宠下方。包含：标题栏（日期）、进度 + 渐变条、
        待办列表（圆形勾选框 + 时间胶囊 + 标题 + 删除）、底部新增区。
        """
        if hasattr(self, '_schedule_win') and self._schedule_win is not None:
            try:
                if self._schedule_win.winfo_exists():
                    self._schedule_win.lift()
                    self._refresh_schedule_list()
                    return
            except Exception:
                pass

        top = tk.Toplevel(self.root)
        self._schedule_win = top
        top.title('日程表')
        top.attributes('-topmost', True)
        top.config(bg=UI_BG)
        top.resizable(False, False)
        top.protocol('WM_DELETE_WINDOW', self._on_schedule_close)

        today = datetime.now()
        weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekdays[today.weekday()]

        # 标题栏
        header = tk.Frame(top, bg=UI_BG)
        header.pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(
            header, text='今日日程',
            font=('Microsoft YaHei UI', 14, 'bold'),
            bg=UI_BG, fg=UI_TEXT,
        ).pack(side='left')
        tk.Label(
            header, text=f"{today.month}月{today.day}日 · {weekday}",
            font=('Microsoft YaHei UI', 10),
            bg=UI_BG, fg=UI_MUTED,
        ).pack(side='right')

        # 进度区：数字 + 渐变进度条
        prog = tk.Frame(top, bg=UI_BG)
        prog.pack(fill='x', padx=16, pady=(10, 4))
        self._prog_ring = tk.Label(
            prog, text='0/0',
            font=('Microsoft YaHei UI', 13, 'bold'),
            bg=UI_BG, fg=ACC_TODAY,
        )
        self._prog_ring.pack(side='left')
        bar_frame = tk.Frame(prog, bg=UI_BG)
        bar_frame.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self._prog_bar = tk.Canvas(
            bar_frame, height=8, bg=UI_BG, highlightthickness=0, bd=0)
        self._prog_bar.pack(fill='x')
        self._prog_cap = tk.Label(
            bar_frame, text='', font=('Microsoft YaHei UI', 9),
            bg=UI_BG, fg=UI_MUTED, anchor='w',
        )
        self._prog_cap.pack(fill='x', pady=(3, 0))

        # 待办列表容器
        list_frame = tk.Frame(top, bg=UI_BG)
        list_frame.pack(fill='both', expand=True, padx=8, pady=(4, 0))
        self._task_list_frame = list_frame

        # 新增输入区
        add_frame = tk.Frame(top, bg=UI_BG)
        add_frame.pack(fill='x', padx=16, pady=(8, 14))
        self._task_title_var = tk.StringVar()
        entry = tk.Entry(
            add_frame, textvariable=self._task_title_var,
            font=('Microsoft YaHei UI', 11),
            bg=UI_BG, fg=UI_TEXT,
            insertbackground=ACC_TODAY, relief='flat',
            highlightthickness=1, highlightbackground=UI_BORDER,
            highlightcolor=ACC_TODAY,
        )
        entry.pack(fill='x', ipady=6)
        entry.bind('<Return>', lambda e: self._on_task_add())

        # 日期时间行：年 月 日 时 分
        dt_frame = tk.Frame(add_frame, bg=UI_BG)
        dt_frame.pack(fill='x', pady=(6, 0))
        self._due_vars = {}
        dt_specs = [
            ('y', str(today.year), 6, '年'),
            ('mo', str(today.month), 3, '月'),
            ('d', str(today.day), 3, '日'),
            ('h', '12', 3, '时'),
            ('mi', '00', 3, '分'),
        ]
        for key, default, width, suffix in dt_specs:
            var = tk.StringVar(value=default)
            self._due_vars[key] = var
            e = tk.Entry(
                dt_frame, textvariable=var, width=width,
                font=('Microsoft YaHei UI', 11),
                bg=UI_BG, fg=UI_TEXT, justify='center',
                insertbackground=ACC_TODAY, relief='flat',
                highlightthickness=1, highlightbackground=UI_BORDER,
                highlightcolor=ACC_TODAY,
            )
            e.pack(side='left')
            tk.Label(dt_frame, text=suffix,
                     font=('Microsoft YaHei UI', 11),
                     bg=UI_BG, fg=UI_MUTED).pack(side='left', padx=(2, 6))

        add_btn = tk.Button(
            add_frame, text='添加', command=self._on_task_add,
            font=('Microsoft YaHei UI', 11),
            bg=ACC_TODAY, fg=self._ink_on(ACC_TODAY), relief='flat', bd=0,
            activebackground=ACC_FUTURE, activeforeground=UI_TEXT,
            padx=16,
        )
        add_btn.pack(anchor='e', pady=(8, 0))

        # 窗口定位：贴在桌宠下方
        top.update_idletasks()
        win_w = top.winfo_reqwidth()
        win_h = top.winfo_reqheight()
        px = self.root.winfo_x() + self._frame_w // 2 - win_w // 2
        py = self.root.winfo_y() + self._frame_h + 8
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        px = max(0, min(px, sw - win_w))
        py = max(0, min(py, sh - win_h))
        top.geometry(f'+{int(px)}+{int(py)}')

        self._refresh_schedule_list()
        entry.focus_set()

    def _on_schedule_close(self):
        """关闭日程窗口时清理引用，避免残留后再点无法重建。"""
        try:
            if self._schedule_win is not None:
                self._schedule_win.destroy()
        except Exception:
            pass
        self._schedule_win = None

    def _refresh_schedule_list(self):
        """重绘日程列表与进度，并从数据库读取最新数据。"""
        if not (hasattr(self, '_schedule_win')
                and self._schedule_win is not None
                and self._schedule_win.winfo_exists()):
            return
        rows = db_todo.get_all_todos()
        for w in self._task_list_frame.winfo_children():
            w.destroy()

        today = datetime.now().strftime('%Y-%m-%d')
        visible = [r for r in rows if not r[3] or (r[4] and r[4][:10] == today)]
        total = len(visible)
        done = sum(1 for r in visible if r[3])
        self._prog_ring.config(text=f'{done}/{total}')
        self._draw_progress(done, total)
        self._prog_cap.config(text=f'已完成 {done} 项，还剩 {total - done} 项')

        if not visible:
            tk.Label(
                self._task_list_frame, text='今天没有待办，记一件吧~',
                font=('Microsoft YaHei UI', 11),
                bg=UI_BG, fg=UI_MUTED,
            ).pack(pady=18)
            self._refresh_badge()
            return

        for r in visible:
            self._make_task_row(r)

        self._refresh_badge()

    def _draw_progress(self, done, total):
        """绘制青→紫渐变进度条（用竖线逐列插值实现渐变）。"""
        self._prog_bar.delete('all')
        w = self._prog_bar.winfo_width()
        h = 8
        if w <= 1:
            w = 240
        # 轨道
        self._prog_bar.create_rectangle(0, 0, w, h, fill=UI_BORDER, outline='')
        if not total:
            return
        fill_w = max(6, int(w * done / total))
        r0, g0, b0 = BAR_FROM
        r1, g1, b1 = BAR_TO
        for x in range(fill_w):
            t = x / max(1, fill_w - 1)
            col = '#%02x%02x%02x' % (
                int(r0 + (r1 - r0) * t),
                int(g0 + (g1 - g0) * t),
                int(b0 + (b1 - b0) * t),
            )
            self._prog_bar.create_line(x, 0, x, h, fill=col)

    def _make_task_row(self, row):
        """渲染单行待办：圆形勾选框 + 标题 + 日期胶囊。

        row = (id, title, due_at, done, done_at)。
        该行状态色由 _row_accent 按紧急度决定，勾选框与日期胶囊同色。
        """
        task_id, title, due_at, done, done_at = row
        acc = self._row_accent(due_at, done)

        rowf = tk.Frame(self._task_list_frame, bg=UI_BG)
        rowf.pack(fill='x', padx=8, pady=3)

        # 自绘圆形勾选框（26px，替代原生小方框）
        done_var = tk.BooleanVar(value=bool(done))
        cb = RoundCheckbox(
            rowf, size=CHECKBOX_SIZE, acc=acc, bg=UI_BG,
            variable=done_var,
            command=lambda i=task_id, v=done_var: self._on_task_toggle(i, v.get()),
        )
        cb.pack(side='left', padx=(0, 10))

        # 标题（完成时划线变淡）
        title_label = tk.Label(
            rowf, text=title,
            font=('Microsoft YaHei UI', 11),
            bg=UI_BG,
            fg=UI_FAINT if done else UI_TEXT,
            anchor='w',
        )
        title_label.pack(side='left', fill='x', expand=True)
        if done:
            title_label.config(font=('Microsoft YaHei UI', 11, 'overstrike'))

        # 日期胶囊：同一行状态色的淡底 + 该色文字
        pill_bg = tint(acc, UI_BG, 0.16)
        tk.Label(
            rowf, text=db_todo.format_due(due_at),
            font=('Microsoft YaHei UI', 9),
            bg=pill_bg, fg=acc, padx=8, pady=2,
        ).pack(side='right', padx=(8, 6))

        # 删除
        del_btn = tk.Label(
            rowf, text='×', font=('Microsoft YaHei UI', 12),
            bg=UI_BG, fg=UI_MUTED, cursor='hand2',
        )
        del_btn.pack(side='right', padx=(2, 2))
        del_btn.bind('<Button-1>', lambda e, i=task_id: self._on_task_delete(i))

    def _on_task_toggle(self, task_id, done):
        """勾选/取消勾选回调。"""
        try:
            db_todo.set_done(task_id, done)
        except Exception:
            logger.exception('勾选待办失败')
        self._refresh_schedule_list()

    def _on_task_delete(self, task_id):
        """删除一条待办。"""
        try:
            db_todo.delete_todo(task_id)
        except Exception:
            logger.exception('删除待办失败')
        self._refresh_schedule_list()

    def _on_task_add(self):
        """新增待办：从年月日时分数字框组装 due_at。"""
        title = self._task_title_var.get().strip()
        if not title:
            return
        due_at = self._compose_due()
        if due_at is None:
            self._toast('截止时间格式有误')
            return
        try:
            db_todo.add_todo(title, due_at)
        except Exception:
            logger.exception('新增待办失败')
            return
        self._task_title_var.set('')
        self._refresh_schedule_list()
        self._refresh_badge()

    def _compose_due(self):
        """把年月日时分数字框拼成 'YYYY-MM-DD HH:MM'，非法返回 None。"""
        try:
            v = self._due_vars
            y = int(v['y'].get().strip() or 0)
            mo = int(v['mo'].get().strip() or 0)
            d = int(v['d'].get().strip() or 0)
            h = int(v['h'].get().strip() or 0)
            mi = int(v['mi'].get().strip() or 0)
            datetime(y, mo, d, h, mi)   # 非法会抛 ValueError
            return f'{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}'
        except Exception:
            return None

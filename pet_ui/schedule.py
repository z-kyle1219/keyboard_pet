"""日程表：独立日程窗口（卡片式、可勾选、带进度条）+ 桌宠头顶角标。

按用户定稿实现（方案 A 分离式）：
- 点击桌宠 → 日程窗口（下方）+ 统计气泡（上方）分离展示。
- 日程窗口为独立 Toplevel，卡片式排列，可勾选，带完成进度环与进度条。
- 角标常驻桌宠头顶：显示「N 待办」；存在临近截止（<=12 小时）的
  未完成待办时，角标由粉色变红。

作为 Mixin 混入 PetApp，self 语义与 popup.py / table.py 一致。
"""
import tkinter as tk
from datetime import datetime

from PIL import Image, ImageDraw, ImageTk

import db_todo
from logger import logger
from pet_ui.theme import PRIMARY, PRIMARY_DARK, TEXT_DARK, TEXT_MUTED, TRANSPARENT


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
        """绘制角标图片：圆角胶囊，底色随 urgent 在粉/红间切换。

        角标要「小而清晰」：固定高度约 22px，宽度随文字自适应。
        文字用 PIL 的 ImageFont 绘制（不能用 tkinter 的 tkfont.Font，
        后者不能传给 Pillow 的 ImageDraw.text）。
        """
        text = f'{count} 待办'
        try:
            from PIL import ImageFont
            font = ImageFont.truetype('msyh.ttc', 11)
        except Exception:
            font = None
        # 用 PIL 取文字宽度，避免笨拙
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
        color = '#e24b4a' if urgent else PRIMARY
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                            fill=color, outline=None)
        if font is not None:
            d.text((pad_x, h // 2), text, fill='white', font=font,
                   anchor='lm')
        else:
            # 兜底：无字体时居中近似绘制（偏粗略，但不会崩）
            d.text((pad_x, h // 2), text, fill='white', anchor='lm')
        return ImageTk.PhotoImage(img)

    def _place_badge(self):
        """把角标 Label 定位到图标右上角（相对桌宠窗口）。"""
        if not hasattr(self, '_badge_label') or self._badge_label is None:
            return
        bw = self._badge_label.winfo_reqwidth()
        bh = self._badge_label.winfo_reqheight()
        x = self._frame_w - bw
        y = 0
        # 横向夹紧到窗口内
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
        # 更换图标时会再次调用本方法，先清掉旧角标，
        # 避免残留的旧 Label（未绑事件）继续遮住宠物右上角
        old = getattr(self, '_badge_label', None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
        self._badge_label = tk.Label(
            self.root, text='', bg=TRANSPARENT, bd=0,
            image=None,
        )
        self._badge_label.configure(highlightthickness=0, takefocus=0)
        # 复用主窗口的事件处理函数，让角标区域同样可拖拽/单击/右键
        self._bind_pet_events(self._badge_label)
        self._refresh_badge()

    # ---------- 日程窗口 ----------
    def _show_schedule(self):
        """打开独立日程窗口（卡片式 + 可勾选 + 进度条）。

        窗口位于桌宠下方。包含：标题栏（日期）、进度环 + 进度条、
        待办列表（勾选框 + 时间 + 标题 + 删除）、底部新增输入框。
        按截止时间升序排列；勾掉的留一天，没做的轮换到下一天。
        """
        # 若日程窗口已打开，直接置前并刷新，避免叠出多个
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
        top.config(bg='white')
        top.resizable(False, False)
        top.protocol('WM_DELETE_WINDOW', self._on_schedule_close)

        today = datetime.now()
        # 星期中文
        weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekdays[today.weekday()]

        # 标题栏
        header = tk.Frame(top, bg='white')
        header.pack(fill='x', padx=16, pady=(12, 2))
        tk.Label(
            header, text='今日日程',
            font=('Microsoft YaHei UI', 14, 'bold'),
            bg='white', fg=TEXT_DARK,
        ).pack(side='left')
        tk.Label(
            header, text=f"{today.month}月{today.day}日 · {weekday}",
            font=('Microsoft YaHei UI', 10),
            bg='white', fg=TEXT_MUTED,
        ).pack(side='right')

        # 进度区：圆环 + 进度条
        prog = tk.Frame(top, bg='white')
        prog.pack(fill='x', padx=16, pady=(8, 4))
        self._prog_ring = tk.Label(
            prog, text='0/0',
            font=('Microsoft YaHei UI', 12, 'bold'),
            bg='white', fg=PRIMARY_DARK,
        )
        self._prog_ring.pack(side='left')
        bar_frame = tk.Frame(prog, bg='white')
        bar_frame.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self._prog_bar = tk.Canvas(
            bar_frame, height=10, bg='#f0f0f0', highlightthickness=0, bd=0)
        self._prog_bar.pack(fill='x')
        self._prog_cap = tk.Label(
            bar_frame, text='', font=('Microsoft YaHei UI', 9),
            bg='white', fg=TEXT_MUTED, anchor='w',
        )
        self._prog_cap.pack(fill='x', pady=(2, 0))

        # 待办列表容器（可滚动）
        list_frame = tk.Frame(top, bg='white')
        list_frame.pack(fill='both', expand=True, padx=8, pady=(4, 0))
        self._task_list_frame = list_frame

        # 新增输入区：标题 + 截止时间（年/月/日/时/分 数字框）
        add_frame = tk.Frame(top, bg='white')
        add_frame.pack(fill='x', padx=16, pady=(6, 12))
        self._task_title_var = tk.StringVar()
        entry = tk.Entry(
            add_frame, textvariable=self._task_title_var,
            font=('Microsoft YaHei UI', 11),
            bg='white', fg=TEXT_DARK,
            insertbackground=TEXT_DARK, relief='flat',
            highlightthickness=1, highlightbackground='#e5e7eb',
            highlightcolor=PRIMARY,
        )
        entry.pack(fill='x', ipady=6)
        entry.bind('<Return>', lambda e: self._on_task_add())

        # 日期时间行：年 月 日 时 分
        dt_frame = tk.Frame(add_frame, bg='white')
        dt_frame.pack(fill='x', pady=(6, 0))
        today = datetime.now()
        self._due_vars = {}   # 收集年/月/日/时/分 字符串
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
                bg='white', fg=TEXT_DARK, justify='center',
                insertbackground=TEXT_DARK, relief='flat',
                highlightthickness=1, highlightbackground='#e5e7eb',
                highlightcolor=PRIMARY,
            )
            e.pack(side='left')
            tk.Label(dt_frame, text=suffix,
                     font=('Microsoft YaHei UI', 11),
                     bg='white', fg=TEXT_MUTED).pack(side='left', padx=(2, 6))

        add_btn = tk.Button(
            add_frame, text='添加', command=self._on_task_add,
            font=('Microsoft YaHei UI', 11),
            bg=PRIMARY, fg='white', relief='flat', bd=0,
            activebackground=PRIMARY_DARK, activeforeground='white',
            padx=14,
        )
        add_btn.pack(anchor='e', pady=(6, 0))

        # 窗口尺寸与位置：贴在桌宠下方
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
        # 清空列表容器
        for w in self._task_list_frame.winfo_children():
            w.destroy()

        # 已完成/未完成逻辑：勾掉的今天展示（done_at 当天），未完成全部轮换展示
        # 计算进度（当天）仅看未完成 + 今天完成的
        today = datetime.now().strftime('%Y-%m-%d')
        visible = [r for r in rows if not r[3] or (r[4] and r[4][:10] == today)]
        total = len(visible)
        done = sum(1 for r in visible if r[3])
        self._prog_ring.config(text=f'{done}/{total}')
        # 画进度条
        self._prog_bar.delete('all')
        w = self._prog_bar.winfo_width()
        if w <= 1:
            w = 200
        self._prog_bar.create_rectangle(
            0, 0, w, 10, fill='#f0f0f0', outline='')
        if total:
            fill_w = max(2, int(w * done / total))
            self._prog_bar.create_rectangle(
                0, 0, fill_w, 10, fill=PRIMARY, outline='')
        self._prog_cap.config(text=f'已完成 {done} 项，还剩 {total - done} 项')

        if not visible:
            tk.Label(
                self._task_list_frame, text='今天没有待办，记一件吧~',
                font=('Microsoft YaHei UI', 11),
                bg='white', fg=TEXT_MUTED,
            ).pack(pady=16)
            self._refresh_badge()
            return

        for r in visible:
            self._make_task_row(r)

        # 刷新角标（数据可能已变）
        self._refresh_badge()

    def _make_task_row(self, row):
        """渲染单行待办：勾选框 + 标题 + 第三列完整汉字日期时间。

        row = (id, title, due_at, done, done_at).
        第三列按近及远排序（由 get_all_todos 保证）；
        已过期标红、今天截止标粉、未来灰色。
        """
        task_id, title, due_at, done, done_at = row
        rowf = tk.Frame(self._task_list_frame, bg='white')
        rowf.pack(fill='x', padx=8, pady=3)

        done_var = tk.BooleanVar(value=bool(done))
        cb = tk.Checkbutton(
            rowf, variable=done_var,
            command=lambda i=task_id, v=done_var: self._on_task_toggle(i, v.get()),
            bg='white', activebackground='white',
            selectcolor='white',
        )
        cb.pack(side='left', padx=(0, 6))

        # 标题（完成时划线）
        title_label = tk.Label(
            rowf, text=title,
            font=('Microsoft YaHei UI', 11),
            bg='white', fg=TEXT_DARK, anchor='w',
        )
        title_label.pack(side='left', fill='x', expand=True)
        if done:
            title_label.config(fg=TEXT_MUTED,
                               font=('Microsoft YaHei UI', 11, 'overstrike'))

        # 第三列：完整汉字日期时间 + 状态着色
        due_color = TEXT_MUTED
        try:
            from datetime import datetime as _dt
            due_dt = _dt.strptime(due_at, '%Y-%m-%d %H:%M')
            now = _dt.now()
            if not done and due_dt < now:
                due_color = '#e24b4a'          # 已过期 → 红
            elif due_at[:10] == now.strftime('%Y-%m-%d'):
                due_color = PRIMARY_DARK       # 今天截止 → 粉
        except Exception:
            pass
        tk.Label(
            rowf, text=db_todo.format_due(due_at),
            font=('Microsoft YaHei UI', 10),
            bg='white', fg=due_color, anchor='e',
        ).pack(side='right', padx=(8, 6))

        # 删除
        del_btn = tk.Label(
            rowf, text='×', font=('Microsoft YaHei UI', 12),
            bg='white', fg=TEXT_MUTED, cursor='hand2',
        )
        del_btn.pack(side='right', padx=(2, 2))
        del_btn.bind(
            '<Button-1>',
            lambda e, i=task_id: self._on_task_delete(i))

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
        """新增待办：从年月日时分数字框组装 due_at。

        用户只填数字（不记格式），程序拼成 'YYYY-MM-DD HH:MM' 存库。
        """
        title = self._task_title_var.get().strip()
        if not title:
            return
        due_at = self._compose_due()
        if due_at is None:
            # 日期时间非法时给个提示并终止
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
            # 校验合法性
            from datetime import datetime as _dt
            _dt(y, mo, d, h, mi)   # 非法会抛 ValueError
            return f'{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}'
        except Exception:
            return None

"""历史表格：全部历史（日期 | 次数 | MVP 键，倒序）。

从原 pet_ui.py 原样迁移为 Mixin。
"""
import tkinter as tk
from tkinter import ttk

import db
from logger import logger
from pet_ui.theme import PRIMARY_DARK, TEXT_DARK, TEXT_MUTED


class TableMixin:
    """提供 _show_table。"""

    def _show_table(self):
        """以表格形式展示全部历史点击次数。

        只保留「历史所有」一档：查询本身按日期倒序（最近的排最前），
        最近 7 天天然包含在最上面几行，无需再单独提供「最近 7 天」入口。
        使用 ttk.Treeview 渲染「日期 | 次数 | MVP 键」三列表格。
        """
        # 打开表格前，先用同一个原子快照完成「写库 + 取值」，
        # 保证表头「今天」与表格里「今天」那一行是同一个数字，
        # 彻底消除实时值与快照之间的竞态偏差（含 60s 落库滞后）。
        today_count = self.manager.snapshot()

        rows = db.get_daily_mvp()
        title = '历史所有'

        top = tk.Toplevel(self.root)
        top.title(f'点击次数历史 — {title}')
        top.attributes('-topmost', True)
        top.config(bg='white')
        top.resizable(False, False)
        # 先藏后显：构建期间不映射，避免闪现默认浅色空壳
        top.withdraw()

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
        px = self.root.winfo_x() + self._frame_w + 8
        py = self.root.winfo_y()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        if px + win_w > sw:
            px = self.root.winfo_x() - win_w - 8
        px = max(0, min(px, sw - win_w))
        py = max(0, min(py, sh - win_h))
        top.geometry(f'+{int(px)}+{int(py)}')
        # 内容与位置就绪，一次性显示（消除闪现的浅色空窗）
        top.deiconify()

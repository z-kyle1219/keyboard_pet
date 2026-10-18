"""键盘热力图：26 键实时热度面板（深色 HUD 动态版）。

从原 pet_ui.py 原样迁移为 Mixin。按键回调仍在监听线程触发，
通过 root.after 调度回主线程绘制，线程模型与拆分前一致。
"""
import tkinter as tk


class HeatmapMixin:
    """提供 _show_heatmap。"""

    def _show_heatmap(self):
        """弹出 26 键键盘热力图（深色 HUD 动态版）。

        - 实时监听敲键：每敲一个键，对应键位立刻加深并播放环形扩散特效。
        - 温度色阶：绿→黄→橙→红（低频到最热），图例用英文 COOL/ACTIVE/HOT/PEAK。
        - 按键回调在监听线程触发，通过 root.after 调度回主线程绘制。
        """
        # 热力图按键布局：三行 QWERTY。None 表示该列空白（占位）。
        layout = [
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', None],
            ['z', 'x', 'c', 'v', 'b', 'n', 'm', None, None, None],
        ]

        # 初始计数快照
        key_counts = self.manager.snapshot_keys()
        counts = {k: key_counts.get(k, 0) for row in layout
                  for k in row if k}

        top = tk.Toplevel(self.root)
        top.title('键盘热力图')
        top.attributes('-topmost', True)
        top.config(bg='#0a0f1e')
        top.resizable(False, False)

        # ---------- 顶部 HUD ----------
        header = tk.Frame(top, bg='#0a0f1e')
        header.pack(fill='x', padx=16, pady=(12, 2))
        tk.Label(
            header, text='KEYBOARD HEATMAP',
            font=('Consolas', 11, 'bold'), fg='#5b7db1', bg='#0a0f1e',
        ).pack(side='left')
        tk.Label(
            header, text='LIVE', fg='#22d3ee', bg='#0a0f1e',
            font=('Consolas', 10, 'bold'),
        ).pack(side='right')

        stats = tk.Frame(top, bg='#0a0f1e')
        stats.pack(fill='x', padx=16, pady=(2, 6))
        tk.Label(
            stats, text=f"今天 {self.manager.current_count()} 次", fg='#e5e7eb',
            bg='#0a0f1e', font=('Microsoft YaHei UI', 11, 'bold'),
        ).pack(side='left')
        top_key = max(counts, key=counts.get) if counts else '-'
        top_key_label = tk.Label(
            stats, text=f'HOT KEY {top_key}', fg='#ef4444',
            bg='#0a0f1e', font=('Consolas', 11, 'bold'),
        )
        top_key_label.pack(side='right')

        # ---------- 棋盘 canvas ----------
        canvas = tk.Canvas(top, bg='#0a0f1e', highlightthickness=0, bd=0,
                          width=320, height=130)
        canvas.pack(padx=16, pady=4)

        # ---------- 图例（英文）----------
        legend = tk.Frame(top, bg='#0a0f1e')
        legend.pack(fill='x', padx=16, pady=(6, 6))
        for label, color in [('COOL', '#4ade80'), ('ACTIVE', '#facc15'),
                             ('HOT', '#fb923c'), ('PEAK', '#ef4444')]:
            sw = tk.Label(legend, text=label, fg='#7dd3fc', bg='#0a0f1e',
                          font=('Consolas', 9, 'bold'))
            sw.pack(side='left', padx=(0, 14))
            c = tk.Canvas(legend, width=12, height=12, bg='#0a0f1e',
                          highlightthickness=0, bd=0)
            c.pack(side='left', padx=(0, 4))
            c.create_rectangle(1, 1, 12, 12, fill=color, outline='')

        # ---------- 布局几何（键位坐标）----------
        key_w, key_h, gap = 20, 18, 4
        row_w = 10 * key_w + 9 * gap
        indents = [0, 4, 26]
        res = canvas.winfo_width(), canvas.winfo_height()
        cw = res[0] if res[0] > 1 else 320
        ch = res[1] if res[1] > 1 else 130
        start_x = (cw - row_w) // 2
        start_y = 6
        # 每键的矩形坐标存起来，供高亮/特效定位
        cell_rects = {}   # key -> (x1,y1,x2,y2)
        for ridx, row in enumerate(layout):
            y = start_y + ridx * (key_h + gap)
            x = start_x + indents[ridx]
            for cidx, k in enumerate(row):
                if k is None:
                    continue
                x1 = x + cidx * (key_w + gap)
                y1 = y
                cell_rects[k] = (x1, y1, x1 + key_w, y1 + key_h)

        # ---------- 热度色阶 ----------
        def _ramp(ratio):
            if ratio >= 0.86:
                return '#ef4444'
            if ratio >= 0.62:
                return '#fb923c'
            if ratio >= 0.36:
                return '#facc15'
            if ratio >= 0.12:
                return '#4ade80'
            return '#166534'

        def _refresh_counts():
            """重新读取最新计数并更新 counts 字典。"""
            kc = self.manager.snapshot_keys()
            counts.clear()
            counts.update({k: kc.get(k, 0) for row in layout for k in row if k})

        def _cur_max():
            """当前 26 键的最大计数（做颜色归一化）。"""
            return max(counts.values()) if counts else 0

        # ---------- 绘制键位基线 ----------
        def _draw_base():
            canvas.delete('all')
            canvas.update_idletasks()
            # 点阵背景（用 canvas 实际尺寸，避免超出区域浪费）
            bgw = canvas.winfo_width()
            bgh = canvas.winfo_height()
            if bgw <= 1:
                bgw = 320
            if bgh <= 1:
                bgh = 130
            for gx in range(0, bgw, 15):
                for gy in range(0, bgh, 15):
                    canvas.create_rectangle(gx, gy, gx + 1, gy + 1,
                                            fill='#1a2a44', outline='')
            # 键位
            mc = _cur_max()
            for k, (x1, y1, x2, y2) in cell_rects.items():
                cnt = counts.get(k, 0)
                ratio = (cnt / mc) if mc else 0
                color = _ramp(ratio)
                canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
                canvas.create_text(
                    (x1 + x2) // 2, (y1 + y2) // 2, text=k.upper(),
                    fill='#0a0f1e', font=('Consolas', 8, 'bold'))
            # 更新 HOT KEY 标签
            if counts:
                tk_top = max(counts, key=counts.get)
                top_key_label.config(text=f'HOT KEY {tk_top}')

        # ---------- 击键特效（环形扩散 + 亮度闪）----------
        def _flash_key(k):
            """给某个键一次「加深 + 环形扩散」特效（主线程调度）。"""
            if not top.winfo_exists():
                return
            if k not in cell_rects:
                return
            x1, y1, x2, y2 = cell_rects[k]
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cnt = counts.get(k, 0)
            mc = _cur_max()
            ratio = (cnt / mc) if mc else 0
            color = _ramp(ratio)
            # 高亮该键（加深背景 + 亮色描边）
            rid = canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline='#ffffff', width=2)
            canvas.create_text((x1 + x2) // 2, (y1 + y2) // 2, text=k.upper(),
                               fill='#ffffff', font=('Consolas', 8, 'bold'))
            # 环形扩散：逐帧放大、淡出
            def _ring(step):
                r = 4 + step * 5
                oid = canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline=color, width=2)
                canvas.after(int(step * 40), lambda: canvas.delete(oid))

            for s in range(1, 5):
                canvas.after(int(s * 40), (lambda s=s: _ring(s)))
            # 一段时间后移除高亮，回归基线
            def _restore():
                if top.winfo_exists():
                    _draw_base()
            canvas.after(400, _restore)

        # ---------- 按键回调：监听线程触发，调度回主线程 ----------
        def _on_key(name):
            try:
                # 只关心 26 个字母键（name 为小写单个字母）
                if len(name) == 1 and name.isalpha():
                    key = name.lower()
                    if key in cell_rects:
                        self.root.after(0, lambda k=key: _flash_key(k))
            except Exception:
                pass

        self.manager.add_listener(_on_key)

        # 启动时就画一次基线
        _draw_base()

        # 周期轮询：让计数缓慢变化的键位颜色随之更新（兜底）。
        def _poll():
            if not top.winfo_exists():
                return
            _refresh_counts()
            _draw_base()
            canvas.after(1000, _poll)

        canvas.bind('<Configure>', lambda e: _draw_base())
        top.update_idletasks()
        _draw_base()
        _poll()

        # 窗口关闭时移除按键监听，避免残留回调访问已销毁的窗口/画布。
        def _cleanup():
            try:
                self.manager.remove_listener(_on_key)
            except Exception:
                pass
            try:
                top.destroy()
            except Exception:
                pass
        top.protocol('WM_DELETE_WINDOW', _cleanup)

        # 窗口定位到桌宠旁
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

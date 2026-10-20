"""自绘圆形勾选框（取代原生 tk.Checkbutton）。

原生 Checkbutton 在 Windows 上固定约 16px、样式由系统主题决定，
既小又不能改色（用户反馈"太小了不好打勾、颜色一直是粉的"）。
这里用 tk.Canvas + PIL 抗锯齿绘制 26px 圆环勾选框：

- 未选：淡色圆底（该行状态色按 18% 混入背景）+ 状态色描边环
- 悬停：环加粗、底色略加深
- 勾选：整圆填充状态色 + 深色对勾（在亮色上压深色，对比更冲）

配色由调用方以 acc 传入（来自 theme 的 ACC_*），
背景 bg 用于混出"暗底透彩"的未选态底色。
"""
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from pet_ui.theme import tint


class RoundCheckbox(tk.Canvas):
    """圆形勾选框控件。

    参数：
      master  父容器
      size    外径（像素），默认 26
      acc     状态色（勾选填充 / 边框）
      bg      所在行背景色，用于混出未选态淡底
      variable 绑定的 tk.BooleanVar（与 db 勾选状态同步）
      command 点击后回调，无参
    """

    def __init__(self, master, size=26, acc='#22d3ee', bg='#131b2a',
                 variable=None, command=None, **kw):
        self._size = size
        self._acc = acc
        self._bg = bg
        self._var = variable if variable is not None else tk.BooleanVar()
        self._command = command
        self._hover = False
        # 预留 2px 内边距，避免粗环被画布边缘裁掉
        pad = 2
        c = size + pad * 2
        super().__init__(master, width=c, height=c, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._img_ref = None
        self._render()
        self.bind('<Button-1>', self._on_click)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)

    # ---------- 绘制 ----------
    def _render(self):
        """按当前状态重建图片（勾选/悬停/未选三态）。"""
        pad = 2
        n = self._size + pad * 2
        ss = 4                                  # 超采样倍率，平滑圆环
        img = Image.new('RGBA', (n * ss, n * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        cx = cy = n * ss / 2
        r = self._size * ss / 2
        checked = bool(self._var.get())

        if checked:
            ring_w = self._size * ss * 0.10
            d.ellipse([cx - r + ring_w, cy - r + ring_w,
                       cx + r - ring_w, cy + r - ring_w],
                      fill=self._acc)
            ink = self._ink_on(self._acc)
            self._draw_tick(d, cx, cy, r, ink, ss)
        else:
            # 未选：淡色圆底 + 状态色描边
            fill = tint(self._acc, self._bg, 0.20 if self._hover else 0.13)
            d.ellipse([cx - r + 1, cy - r + 1, cx + r - 1, cy + r - 1],
                      fill=fill)
            ring_w = self._size * ss * (0.10 if self._hover else 0.075)
            d.ellipse([cx - r + ring_w / 2, cy - r + ring_w / 2,
                       cx + r - ring_w / 2, cy + r - ring_w / 2],
                      outline=self._acc, width=int(ring_w))

        img = img.resize((n, n), Image.LANCZOS)
        self._img_ref = ImageTk.PhotoImage(img)
        self.delete('all')
        self.create_image(0, 0, image=self._img_ref, anchor='nw')

    def _ink_on(self, color):
        """按状态色亮度选对勾颜色：亮色上压深色，暗色上用白。"""
        try:
            c = color.lstrip('#')
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            return '#06121a' if lum > 150 else '#ffffff'
        except Exception:
            return '#06121a'

    def _draw_tick(self, d, cx, cy, r, ink, ss):
        """在圆心绘制对勾（按半径等比缩放）。"""
        w = max(2, int(r * 0.20))
        pts = [
            (cx - r * 0.40, cy + r * 0.02),
            (cx - r * 0.12, cy + r * 0.30),
            (cx + r * 0.44, cy - r * 0.30),
        ]
        d.line(pts, fill=ink, width=w, joint='curve')
        # 端点补圆，避免直角缺口
        for (px, py) in (pts[0], pts[-1]):
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2],
                      fill=ink)

    # ---------- 交互 ----------
    def _on_click(self, _e):
        self._var.set(not self._var.get())
        self._render()
        if callable(self._command):
            self._command()

    def _on_enter(self, _e):
        self._hover = True
        self.configure(cursor='hand2')
        self._render()

    def _on_leave(self, _e):
        self._hover = False
        self._render()

    # ---------- 外部同步 ----------
    def sync(self):
        """外部改动 BooleanVar 后调用，重绘以反映最新状态。"""
        self._render()

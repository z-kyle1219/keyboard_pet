"""PetApp 主类：窗口、图标加载、拖拽、右键菜单等粘合层。

拆分说明（2026-10-18）：
本模块只保留「核心窗口与交互」——透明漂浮窗、图标加载与帧预生成、
拖拽/单击/右键菜单、更换图标、自启动开关。
其余职责由 Mixin 拆分到独立文件，通过多重继承组合：
- AnimationMixin  呼吸 / 挤压 / 拎起动画
- PopupMixin      气泡卡片 / MVP 徽章 / 冠军登场特效
- HeatmapMixin    键盘热力图
- TableMixin      历史表格

对外接口保持 `from pet_ui import PetApp` 不变，UI 行为与拆分前一致。
"""
import os
import tkinter as tk
from tkinter import filedialog

from PIL import Image

import autostart
import config
from logger import logger
from pet_ui.animations import AnimationMixin
from pet_ui.heatmap import HeatmapMixin
from pet_ui.popup import PopupMixin
from pet_ui.renderer import (
    _placeholder_icon,
    _prepare_pet,
    _compose_frame,
    frame_to_photo,
)
from pet_ui.table import TableMixin
from pet_ui.theme import TRANSPARENT, TEXT_DARK


class PetApp(AnimationMixin, PopupMixin, HeatmapMixin, TableMixin):
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
        # ---------- 动画状态 ----------
        self._frame_w = None        # 帧画布宽度
        self._frame_h = None        # 帧画布高度
        self._idle_photos = []      # 呼吸循环帧
        self._squash_photos = []    # 点击挤压帧
        self._lift_photo = None     # 拖拽拎起帧
        self._anim_mode = 'idle'    # idle / squash
        self._anim_job = None       # 当前 after 任务 id
        self._idle_idx = 0          # 呼吸帧游标
        self._lifting = False       # 是否处于拖拽拎起态
        self._setup_window()
        self._load_icon()

    # ---------- 窗口基础 ----------
    def _setup_window(self):
        self.root.overrideredirect(True)               # 去掉标题栏/边框
        self.root.attributes('-topmost', True)         # 始终置顶
        self.root.config(bg=TRANSPARENT)               # 背景设为透明色
        self.root.wm_attributes('-transparentcolor', TRANSPARENT)  # 抠掉该颜色
        # 尺寸依赖图标帧，在 _load_icon 里确定后再 apply

    # ---------- 图标 ----------
    def _load_icon(self):
        # 直接使用用户手动上传到 assets/ 的图标
        icon_path = self.config.get('icon_path')
        if not icon_path or not os.path.exists(icon_path):
            icon_path = config.PET_ICON
        try:
            img = Image.open(icon_path)
        except Exception:
            # 图片损坏/路径错误：记录日志并回退到内置占位图标，不崩溃
            logger.exception('图标加载失败，回退到占位图：%s', icon_path)
            img = _placeholder_icon()

        # 基准人物（按高度缩放，透明图保留轮廓）
        pet = _prepare_pet(img, config.PET_HEIGHT)

        # 预生成动画帧
        self._idle_photos = [
            frame_to_photo(_compose_frame(pet, s, l)) for s, l in self._idle_pose()
        ]
        self._squash_photos = [
            frame_to_photo(_compose_frame(pet, 1.0, 0, sq))
            for sq in ((1.0, 1.0), (1.10, 0.88), (0.95, 1.06),
                       (1.04, 0.96), (1.0, 1.0))
        ]
        self._lift_photo = frame_to_photo(_compose_frame(pet, 0.75, 6))

        self._frame_w = self._idle_photos[0].width()
        self._frame_h = self._idle_photos[0].height()

        if self._icon is not None:
            self._icon.destroy()
        self._icon = tk.Label(self.root, image=self._idle_photos[0],
                              bg=TRANSPARENT, bd=0)
        self._icon.pack(fill='both', expand=True)

        # 事件挂在图标上
        self._icon.bind('<ButtonPress-1>', self._on_press)
        self._icon.bind('<B1-Motion>', self._on_motion)
        self._icon.bind('<ButtonRelease-1>', self._on_release)
        self._icon.bind('<Button-3>', self._show_menu)

        # 应用窗口尺寸（帧画布大小）并开始呼吸动画
        self.root.geometry(f'{self._frame_w}x{self._frame_h}+120+120')
        self._resume_idle()

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
            if not self._moved:
                self._moved = True
                # 拖拽开始：切换到拎起帧（阴影缩小、人物上浮）
                self._lifting = True
                self._stop_anim()
                self._icon.configure(image=self._lift_photo)
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
        # 拖拽结束：从拎起态落回呼吸
        if self._lifting:
            self._lifting = False
            self._resume_idle()
        # 按住未拖动视为"单击" → 挤压回弹 + 显示/关闭气泡
        if not self._moved:
            self._play_squash()
            self._show_bubble()
        self._press_origin = None

    # ---------- 右键菜单 ----------
    def _show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0,
                       font=('Microsoft YaHei UI', 10),
                       bg='white', fg=TEXT_DARK,
                       activebackground='#1f1f1f', activeforeground='white')
        menu.add_command(label='最近 7 天', command=lambda: self._show_table(7))
        menu.add_command(label='历史所有', command=lambda: self._show_table(None))
        menu.add_separator()
        menu.add_command(label='键盘热力图', command=self._show_heatmap)
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

    # ---------- 更换图标 ----------
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

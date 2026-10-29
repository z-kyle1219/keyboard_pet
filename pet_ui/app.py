"""PetApp 主类：窗口、图标加载、拖拽、右键菜单等粘合层。

拆分说明（2026-10-18）：
本模块只保留「核心窗口与交互」——透明漂浮窗、图标加载与帧预生成、
拖拽/单击/右键菜单、自启动开关。
其余职责由 Mixin 拆分到独立文件，通过多重继承组合：
- AnimationMixin  呼吸 / 挤压 / 拎起动画
- PopupMixin      气泡卡片 / MVP 徽章 / 冠军登场特效
- HeatmapMixin    键盘热力图
- TableMixin      历史表格
- AppStatsMixin   各软件分布（今天条形 / 近 7 天折线）
- MinimizeMixin   一键最小化
- VaultMixin      琥珀（密码存储：搜索 + 解密显示）
- TranslateMixin  翻译（热键快译 + 输入框）

对外接口保持 `from pet_ui import PetApp` 不变，UI 行为与拆分前一致。
"""
import tkinter as tk

from PIL import Image

import autostart
import config
from logger import logger
from pet_ui.animations import AnimationMixin
from pet_ui.app_stats import AppStatsMixin
from pet_ui.heatmap import HeatmapMixin
from pet_ui.minimize import MinimizeMixin
from pet_ui.popup import PopupMixin
from pet_ui.renderer import (
    _placeholder_icon,
    _prepare_pet,
    _compose_frame,
    frame_to_photo,
)
from pet_ui.schedule import ScheduleMixin
from pet_ui.table import TableMixin
from pet_ui.vault_ui import VaultMixin
from pet_ui.translate_ui import TranslateMixin
from pet_ui.weather_popup import WeatherMixin
from pet_ui.theme import TRANSPARENT, TEXT_DARK


class PetApp(AnimationMixin, PopupMixin, HeatmapMixin, TableMixin,
              AppStatsMixin, ScheduleMixin, WeatherMixin, MinimizeMixin,
              VaultMixin, TranslateMixin):
    def __init__(self, root, manager, app_tracker=None):
        self.root = root
        self.manager = manager
        # 按应用统计（可能为 None：只影响「各软件分布」菜单）
        self.app_tracker = app_tracker
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
        # ---------- 日程表状态 ----------
        self._badge_label = None    # 头顶「N 待办」角标 Label
        self._badge_image = None    # 角标图片（防 GC）
        self._schedule_win = None   # 日程窗口（防止叠加多个）
        # ---------- 天气状态 ----------
        self._weather_win = None    # 天气卡片窗口
        self._weather_state = None  # 由 main.py 注入的 WeatherState
        # ---------- 关机提醒 ----------
        self._shutdown_win = None   # 关机提醒气泡（点「知道啦」才退出）
        # ---------- 琥珀（密码存储）----------
        self._vault_win = None      # 琥珀搜索窗口
        self._reveal_win = None     # 密码明文显示气泡（自动清屏）
        self._reveal_after_ids = []
        self._vault_w = 380         # 琥珀窗口尺寸缓存（拖拽跟随用）
        self._vault_h = 200
        self._reveal_w = 260        # 密码气泡尺寸缓存
        self._reveal_h = 120
        # ---------- 翻译 ----------
        self._translate_win = None        # 翻译输入窗口
        self._translate_entry = None      # 输入框（Text）
        self._translate_result_win = None # 译文结果卡片
        self._translate_w = 360           # 输入窗口尺寸缓存
        self._translate_h = 180
        self._result_w = 300              # 结果卡尺寸缓存
        self._result_h = 140
        self._translate_pending = 0       # 请求令牌（只认最后一次）
        self._translate_hotkey = None     # pynput GlobalHotKeys 监听器
        self._translate_last_hit = 0.0    # 热键节流时间戳
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
        # 图标直接取自 assets/：换图只需替换 assets/ 里的图片，重启后生效
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

        # 事件挂在图标上（角标在 schedule.py 里绑同一组处理函数）
        self._bind_pet_events(self._icon)

        # 应用窗口尺寸（帧画布大小）并开始呼吸动画
        self.root.geometry(f'{self._frame_w}x{self._frame_h}+120+120')
        self._resume_idle()
        # 在图标上叠加头顶角标（「N 待办」，临近截止变红）
        self._setup_badge()

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
        # 让天气卡片跟随桌宠（并保持置顶不被遮挡）
        if getattr(self, '_weather_win', None) is not None:
            self._place_weather_win()
        # 让琥珀搜索窗口跟随桌宠
        if getattr(self, '_vault_win', None) is not None:
            self._place_vault_win()
        # 让密码显示气泡跟随桌宠
        if getattr(self, '_reveal_win', None) is not None:
            self._place_reveal_win()
        # 让翻译输入窗口 / 结果卡片跟随桌宠
        if getattr(self, '_translate_win', None) is not None:
            self._place_translate_win()
        if getattr(self, '_translate_result_win', None) is not None:
            self._place_result_win()
        # 让关机提醒气泡跟随桌宠
        sw = getattr(self, '_shutdown_win', None)
        if sw is not None:
            try:
                if sw.winfo_exists():
                    sw.geometry(
                        f'+{self.root.winfo_x() + self._frame_w // 2 - sw.winfo_width() // 2}'
                        f'+{max(0, self.root.winfo_y() - sw.winfo_height() - 8)}')
            except Exception:
                pass

    def _on_release(self, e):
        # 拖拽结束：从拎起态落回呼吸
        if self._lifting:
            self._lifting = False
            self._resume_idle()
        # 按住未拖动视为"单击" → 挤压回弹 + 同步开关气泡与日程
        if not self._moved:
            self._play_squash()
            self._toggle_panels()
        self._press_origin = None

    # ---------- 事件绑定 ----------
    def _bind_pet_events(self, widget):
        """把拖拽/单击/右键事件绑到给定控件上。

        桌宠图标与头顶角标是两个独立控件。Tk 的事件只发给指针下那个
        控件、不会自动冒泡到父控件，若只在图标上绑定，点击落在角标
        区域时会被角标吞掉，表现为「有时左键点桌宠没反应」。
        故两处都绑定同一组处理函数。
        """
        widget.bind('<ButtonPress-1>', self._on_press)
        widget.bind('<B1-Motion>', self._on_motion)
        widget.bind('<ButtonRelease-1>', self._on_release)
        widget.bind('<Button-3>', self._show_menu)

    # ---------- 气泡 / 日程同步开关 ----------
    def _panels_open(self):
        """日程窗口或统计气泡是否有任一个正在显示。

        作为「面板已展开」的统一判定：只要两者之一还开着，
        下一次点击桌宠就应当把两者一起收起。
        """
        w = getattr(self, '_schedule_win', None)
        try:
            if w is not None and w.winfo_exists():
                return True
        except Exception:
            pass
        p = getattr(self, '_active_popup', None)
        try:
            return p is not None and p.winfo_exists()
        except Exception:
            return False

    def _toggle_panels(self):
        """左键单击：气泡与日程窗口同步开关。

        未展开时两者一起出现；再次点击桌宠时两者一起关闭，
        无需再手动点日程窗口的叉号。日程窗口的叉号仍可单独关闭它。
        """
        if self._panels_open():
            self._on_schedule_close()   # 关日程窗口
            self._close_popup()         # 关统计气泡
        else:
            # 气泡若已在显示则保留，避免被 _show_bubble 的 toggle 逻辑误关
            if not (self._active_popup is not None
                    and self._active_popup.winfo_exists()):
                self._show_bubble()
            self._show_schedule()

    # ---------- 右键菜单 ----------
    def _show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0,
                       font=('Microsoft YaHei UI', 10),
                       bg='white', fg=TEXT_DARK,
                       activebackground='#1f1f1f', activeforeground='white')
        menu.add_command(label='历史所有', command=self._show_table)
        menu.add_separator()
        menu.add_command(label='各软件分布', command=self._show_app_stats)
        menu.add_separator()
        menu.add_command(label='键盘热力图', command=self._show_heatmap)
        menu.add_separator()
        menu.add_command(label='琥珀', command=self._show_vault)
        menu.add_separator()
        menu.add_command(label='翻译', command=self._show_translate)
        menu.add_separator()
        menu.add_command(label='一键最小化', command=self._minimize_all)
        menu.add_separator()
        # 开机自启动开关（勾选表示已开启）
        menu.add_checkbutton(
            label='开机自启动',
            onvalue=True, offvalue=False,
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        menu.add_separator()
        menu.add_command(label='退出', command=self._shutdown_prompt)
        menu.tk_popup(e.x_root, e.y_root)

    def _toggle_autostart(self):
        """切换开机自启动状态。"""
        enabled = autostart.toggle()
        # 让 checkbutton 状态与真实结果保持一致
        self._autostart_var.set(enabled)
        msg = '开机自启动已开启' if enabled else '开机自启动已关闭'
        self._toast(msg)

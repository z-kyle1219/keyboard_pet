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
TRANSPARENT_RGB = (255, 0, 255)

# 时尚配色：主色（水母粉）、深色文字、浅色底
PRIMARY = '#ff7aa2'
PRIMARY_DARK = '#ff4d80'
TEXT_DARK = '#2b2b2b'
TEXT_MUTED = '#8a8a8a'

# ---------- 桌宠渲染与动画参数 ----------
IDLE_FRAMES = 10          # 呼吸循环帧数
IDLE_INTERVAL = 220       # 呼吸每帧间隔(ms)，约 2.2s 一个呼吸周期
SQUASH_INTERVAL = 45      # 点击挤压每帧间隔(ms)
PAD_X = 24                # 帧画布左右留白（容纳挤压变宽与呼吸）
PAD_TOP = 8               # 帧画布顶部留白
SHADOW_H_RATIO = 0.16     # 阴影高度占人物高度比例


def _has_alpha(img):
    """判断图片是否带透明通道。"""
    if img.mode in ('RGBA', 'LA'):
        return True
    if img.mode == 'P' and 'transparency' in img.info:
        return True
    return False


def _prepare_pet(img, pet_h):
    """把原始图标转成基准人物 RGBA（高度=pet_h）。

    透明图：等比缩放保留人物轮廓；无透明图：居中裁正方形 + 圆角兜底。
    """
    if _has_alpha(img):
        w, h = img.size
        pet_w = max(1, round(pet_h * w / h))
        return img.convert('RGBA').resize((pet_w, pet_h), Image.LANCZOS)
    # 无透明通道：沿用旧的圆角处理，避免生硬矩形
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).convert('RGBA')
    img = img.resize((pet_h, pet_h), Image.LANCZOS)
    radius = max(8, int(pet_h * 0.28))
    mask = Image.new('L', (pet_h, pet_h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, pet_h, pet_h], radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(pet_h * 0.03))
    out = Image.new('RGBA', (pet_h, pet_h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _make_shadow(pet_w, shadow_h, scale=1.0):
    """生成柔和椭圆阴影（不透明灰色渐变，模拟 alpha 阴影）。

    tkinter 的 transparentcolor 只抠纯色、不支持半透明，故阴影用多层同心
    椭圆从内到外渐浅的灰色来模拟柔边，浅色桌面下边界自然。
    """
    sw = max(1, round(pet_w * scale))
    sh = max(1, round(shadow_h * scale))
    img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    layers = [
        (0.40, (176, 176, 184, 255)),
        (0.34, (188, 188, 196, 255)),
        (0.28, (200, 200, 207, 255)),
        (0.22, (212, 212, 218, 255)),
        (0.16, (224, 224, 229, 255)),
    ]
    for r, col in layers:
        d.ellipse([sw * (0.5 - r / 2), sh * 0.15,
                   sw * (0.5 + r / 2), sh * 0.95], fill=col)
    return img


def _compose_frame(pet, shadow_scale, lift, squash=(1.0, 1.0)):
    """合成一帧完整渲染图（RGBA）：人物 + 底部阴影。

    pet          基准人物 RGBA
    shadow_scale 阴影缩放系数（呼吸/拎起时变化）
    lift         人物上浮像素
    squash       (sx, sy) 挤压因子，用于点击回弹
    """
    pw, ph = pet.size
    sx, sy = squash
    nw = max(1, round(pw * sx))
    nh = max(1, round(ph * sy))
    p = pet.resize((nw, nh), Image.LANCZOS)

    shadow_h = round(ph * SHADOW_H_RATIO)
    shadow = _make_shadow(pw, shadow_h, shadow_scale)

    W = pw + 2 * PAD_X
    H = ph + PAD_TOP + shadow_h + 6

    frame = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sw, sh = shadow.size
    frame.alpha_composite(shadow, ((W - sw) // 2, H - sh - 2))
    px = (W - nw) // 2
    py = PAD_TOP + (ph - nh) // 2 - lift
    frame.alpha_composite(p, (px, py))
    return frame


def frame_to_photo(frame):
    """把 RGBA 帧转成品红抠底的 PhotoImage（tkinter 可显示）。

    二值化 alpha：>=128 保留前景色，<128 填品红，由窗口 transparentcolor 抠掉。
    """
    w, h = frame.size
    base = Image.new('RGB', (w, h), TRANSPARENT_RGB)
    fg = frame.convert('RGB')
    mask = frame.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    base.paste(fg, (0, 0), mask)
    return ImageTk.PhotoImage(base)


def _placeholder_icon():
    """生成一个简单的占位水母图标（RGBA），用于图片加载失败时兜底。"""
    size = config.PET_HEIGHT
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 120.0
    # 身体
    d.ellipse([18 * s, 12 * s, 102 * s, 78 * s], fill=(255, 170, 190, 210))
    d.ellipse([36 * s, 26 * s, 86 * s, 66 * s], fill=(255, 214, 224, 160))
    # 触须
    for t in range(5):
        base_x = (30 + t * 14) * s
        pts = []
        for step in range(0, 40):
            y = (72 + step * 1.1) * s
            x = base_x + math.sin(step / 4.0 + t) * 6 * s
            pts.append((x, y))
        d.line(pts, fill=(255, 170, 190, 180), width=max(1, int(2 * s)))
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

    def _idle_pose(self):
        """呼吸循环的姿态序列：[(shadow_scale, lift), ...]。

        吸气时人物上浮、阴影略小；呼气时人物下沉、阴影略大。
        """
        poses = []
        for i in range(IDLE_FRAMES):
            phase = 2 * math.pi * i / IDLE_FRAMES
            lift = round(2.5 * (1 - math.cos(phase)))
            shadow_scale = 0.90 + 0.10 * math.cos(phase)
            poses.append((shadow_scale, lift))
        return poses

    # ---------- 动画 ----------
    def _stop_anim(self):
        """取消当前排队的动画 tick。"""
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _resume_idle(self):
        """回到呼吸循环。"""
        self._anim_mode = 'idle'
        self._idle_idx = 0
        self._icon.configure(image=self._idle_photos[0])
        self._animate_idle()

    def _animate_idle(self):
        if self._anim_mode != 'idle':
            return
        self._idle_idx = (self._idle_idx + 1) % len(self._idle_photos)
        self._icon.configure(image=self._idle_photos[self._idle_idx])
        self._anim_job = self.root.after(IDLE_INTERVAL, self._animate_idle)

    def _play_squash(self):
        """点击挤压回弹动画（squash & stretch）。"""
        self._anim_mode = 'squash'
        self._stop_anim()
        idx = [0]

        def step():
            if idx[0] >= len(self._squash_photos):
                self._resume_idle()
                return
            self._icon.configure(image=self._squash_photos[idx[0]])
            idx[0] += 1
            self._anim_job = self.root.after(SQUASH_INTERVAL, step)

        step()

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
        import math

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

    def _toast(self, msg):
        """在桌宠上方短暂显示一条提示。"""
        self._popup(body=msg, duration=2200)

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
        px = self.root.winfo_x() + self._frame_w + 8
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

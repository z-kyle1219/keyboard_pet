"""翻译：中英互译（热键快译 + 右键输入框）。

流程：
    Ctrl+Alt+T（复制任意文本后按）→ 读剪贴板 → 后台请求 → 玄墨卡片出译文
    右键「翻译」→ 输入框手打 → 回车翻译

设计要点：
- 作为 Mixin 混入 PetApp（与 vault_ui.py 同套路）。
- 网络请求放后台线程，绝不在主线程阻塞（否则桌宠呼吸动画会卡住）；
  结果统一用 root.after(0, ...) 甩回主线程再碰界面。
- 请求带序号令牌：连按热键时只认最后一次的结果，不会被旧请求覆盖。
- 结果卡片用「玄墨极简」配色（与琥珀密码气泡同一体系），
  跟随桌宠移动，点 ✕ 或 Esc 关闭。
- 翻译内容**只在内存**：不落库、不写日志，查完即散。
- 输入窗口沿用琥珀搜索窗的深空霓虹配色，两套主题各管各的。
"""
import threading
import time
import tkinter as tk

import translate
from logger import logger
from pet_ui.theme import (
    ACC_TODAY,
    INK_ACCENT,
    INK_BG,
    INK_BORDER,
    INK_DANGER,
    INK_FAINT,
    INK_INK,
    INK_LINE,
    INK_MUTED,
    INK_TEXT,
    UI_BG,
    UI_BORDER,
    UI_MUTED,
    UI_TEXT,
)

# 全局热键：复制文本后按下，直接译剪贴板里的内容
HOTKEY = '<ctrl>+<alt>+t'
HOTKEY_LABEL = 'Ctrl+Alt+T'

# 热键节流（秒）：按住不放时 key repeat 会连续触发，只认第一次
HOTKEY_COOLDOWN = 0.6

# 结果卡片正文换行宽度
RESULT_WRAP = 320

# 原文在结果卡片里最多显示多少字（译文才是重点）
SRC_PREVIEW = 100


class TranslateMixin:
    """提供翻译相关能力（_show_translate / 热键 / 结果卡片）。"""

    # ========================================================
    # 热键
    # ========================================================
    def start_translate_hotkey(self):
        """注册全局热键（失败只记日志，绝不影响主流程）。"""
        if getattr(self, '_translate_hotkey', None) is not None:
            return
        try:
            from pynput import keyboard
            listener = keyboard.GlobalHotKeys(
                {HOTKEY: self._on_translate_hotkey})
            listener.start()
            self._translate_hotkey = listener
            logger.info('翻译热键已注册：%s', HOTKEY_LABEL)
        except Exception:
            logger.exception('注册翻译热键失败（不影响主流程）')

    def stop_translate_hotkey(self):
        """注销热键（退出时调用）。"""
        listener = getattr(self, '_translate_hotkey', None)
        self._translate_hotkey = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass

    def _on_translate_hotkey(self):
        """pynput 线程里触发：节流后把活甩回主线程。"""
        now = time.monotonic()
        if now - getattr(self, '_translate_last_hit', 0.0) < HOTKEY_COOLDOWN:
            return
        self._translate_last_hit = now
        try:
            self.root.after(0, self._translate_from_clipboard)
        except Exception:
            logger.exception('翻译热键回调异常')

    # ========================================================
    # 触发与请求
    # ========================================================
    def _translate_from_clipboard(self):
        """热键入口：译剪贴板；剪贴板没文字就退化成手打窗口。"""
        text = self._read_clipboard()
        if not text:
            self._show_translate()
            return
        self._translate_text(text)

    def _read_clipboard(self):
        """读剪贴板文本；图片/空内容都返回空串（不打扰用户）。"""
        try:
            return (self.root.clipboard_get() or '').strip()
        except Exception:
            return ''

    def _translate_text(self, text):
        """后台线程请求翻译，完成后回主线程出卡片。"""
        src = (text or '').strip()
        if not src:
            self._toast('先输入要翻译的文字')
            return

        # 令牌：只显示最后一次请求的结果
        self._translate_pending += 1
        token = self._translate_pending

        def _work():
            try:
                result = translate.translate(src)
            except Exception:
                logger.exception('翻译线程异常')
                result = translate.TranslateResult(
                    False, src=src, error='翻译失败')
            try:
                self.root.after(
                    0, lambda: self._on_translate_done(token, result))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _on_translate_done(self, token, result):
        """主线程：丢弃过期结果，显示最新一张卡片。"""
        if token != self._translate_pending:
            return
        self._show_translate_result(result)

    # ========================================================
    # 结果卡片（玄墨极简）
    # ========================================================
    def _show_translate_result(self, result):
        """弹出翻译结果卡片（失败时显示原因，不弹系统对话框）。"""
        self._clear_translate_result()

        win = tk.Toplevel(self.root)
        self._translate_result_win = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.config(bg=INK_BG)
        win.withdraw()
        win.bind('<Escape>', lambda e: self._clear_translate_result())

        pad = 16
        frame = tk.Frame(win, bg=INK_BG, highlightthickness=1,
                         highlightbackground=INK_BORDER)
        frame.pack(fill='both', expand=True)

        # ---- 标题行：方向标签 + ✕ ----
        head = tk.Frame(frame, bg=INK_BG)
        head.pack(fill='x', padx=pad, pady=(pad, 2))
        tk.Label(
            head, text=result.label or '翻译',
            font=('Microsoft YaHei UI', 9), bg=INK_BG, fg=INK_FAINT,
            anchor='w',
        ).pack(side='left')
        close_btn = tk.Label(
            head, text='✕', font=('Microsoft YaHei UI', 12),
            bg=INK_BG, fg=INK_FAINT, cursor='hand2',
        )
        close_btn.pack(side='right')
        close_btn.bind('<Button-1>', lambda e: self._clear_translate_result())
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg=INK_DANGER))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=INK_FAINT))

        # ---- 原文（小字灰，过长截断）----
        src = result.src or ''
        if len(src) > SRC_PREVIEW:
            src = src[:SRC_PREVIEW] + '…'
        if src:
            tk.Label(
                frame, text=src, font=('Microsoft YaHei UI', 9),
                bg=INK_BG, fg=INK_MUTED, justify='left',
                wraplength=RESULT_WRAP, anchor='w',
            ).pack(fill='x', padx=pad, pady=(2, 0))

        if not result.ok:
            # 失败：柔红一句人话，不再显示其它内容
            tk.Label(
                frame, text=result.error or '翻译失败',
                font=('Microsoft YaHei UI', 11), bg=INK_BG, fg=INK_DANGER,
                justify='left', wraplength=RESULT_WRAP, anchor='w',
            ).pack(fill='x', padx=pad, pady=(10, pad))
        else:
            # ---- 译文区：左侧细线 + 亮墨白主文字（玄墨标志性处理）----
            body = tk.Frame(frame, bg=INK_BG)
            body.pack(fill='x', padx=pad, pady=(10, 0))
            tk.Frame(body, bg=INK_LINE, width=2).pack(side='left', fill='y')
            tk.Label(
                body, text=result.dst, font=('Microsoft YaHei UI', 13),
                bg=INK_BG, fg=INK_TEXT, justify='left',
                wraplength=RESULT_WRAP - 14, anchor='w',
            ).pack(side='left', fill='x', expand=True, padx=(12, 0))

            # ---- 操作区：复制译文 ----
            btns = tk.Frame(frame, bg=INK_BG)
            btns.pack(fill='x', padx=pad, pady=(12, pad))
            copy_btn = tk.Label(
                btns, text='复制译文', font=('Microsoft YaHei UI', 10),
                bg=INK_ACCENT, fg=INK_INK, padx=14, pady=6, cursor='hand2',
            )
            copy_btn.pack(side='left')
            copy_btn.bind(
                '<Button-1>', lambda e, t=result.dst: self._translate_copy(t))
            if result.cached:
                tk.Label(
                    btns, text='缓存', font=('Microsoft YaHei UI', 9),
                    bg=INK_BG, fg=INK_FAINT,
                ).pack(side='left', padx=(10, 0))

        win.update_idletasks()
        self._result_w = max(win.winfo_reqwidth(), 240)
        self._result_h = win.winfo_reqheight()
        self._place_result_win()
        win.deiconify()
        try:
            win.focus_force()   # 让 Esc 能关掉卡片
        except Exception:
            pass

    def _place_result_win(self):
        """结果卡片贴桌宠上方；上方放不下就放下方，夹紧到屏幕内。"""
        win = getattr(self, '_translate_result_win', None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            w = getattr(self, '_result_w', 300)
            h = getattr(self, '_result_h', 140)
            x = self.root.winfo_x() + self._frame_w // 2 - w // 2
            y = self.root.winfo_y() - h - 8
            if y < 0:
                y = self.root.winfo_y() + self._frame_h + 8
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
            win.geometry(f'{w}x{h}+{int(x)}+{int(y)}')
            win.attributes('-topmost', True)
        except Exception:
            pass

    def _clear_translate_result(self):
        """销毁结果卡片（幂等）。"""
        win = getattr(self, '_translate_result_win', None)
        self._translate_result_win = None
        if win is None:
            return
        try:
            win.destroy()
        except tk.TclError:
            try:
                win.tk.call('destroy', win._w)
            except Exception:
                pass

    def _translate_copy(self, text):
        """复制译文到剪贴板。"""
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._toast('已复制译文')
        except Exception:
            logger.exception('复制译文失败')
            self._toast('复制失败')

    # ========================================================
    # 手打窗口（深空霓虹，与琥珀搜索窗同一套壳）
    # ========================================================
    def _show_translate(self):
        """打开/聚焦翻译输入窗口。"""
        win = getattr(self, '_translate_win', None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass

        top = tk.Toplevel(self.root)
        self._translate_win = top
        top.title('翻译')
        top.attributes('-topmost', True)
        top.config(bg=UI_BG)
        top.resizable(False, False)
        top.protocol('WM_DELETE_WINDOW', self._on_translate_close)
        top.withdraw()   # 先藏后显，避免闪一下默认空壳

        # ---- 标题栏 ----
        header = tk.Frame(top, bg=UI_BG)
        header.pack(fill='x', padx=16, pady=(14, 6))
        tk.Label(
            header, text='翻译', font=('Microsoft YaHei UI', 14, 'bold'),
            bg=UI_BG, fg=UI_TEXT,
        ).pack(side='left')
        tk.Label(
            header, text=f'{HOTKEY_LABEL} 直接译剪贴板',
            font=('Microsoft YaHei UI', 9), bg=UI_BG, fg=UI_MUTED,
        ).pack(side='right')

        # ---- 输入区（3 行，回车翻译 / Shift+回车换行）----
        box = tk.Frame(top, bg=UI_BG)
        box.pack(fill='both', expand=True, padx=16, pady=(0, 6))
        text = tk.Text(
            box, height=3, width=32, wrap='word',
            font=('Microsoft YaHei UI', 12),
            bg=UI_BG, fg=UI_TEXT, insertbackground=ACC_TODAY,
            relief='flat', highlightthickness=1,
            highlightbackground=UI_BORDER, highlightcolor=ACC_TODAY,
            padx=8, pady=7,
        )
        text.pack(fill='both', expand=True)

        def _on_enter(_e):
            # Enter 翻译；返回 'break' 阻止默认换行
            self._on_translate_input()
            return 'break'

        text.bind('<Return>', _on_enter)
        self._translate_entry = text

        # ---- 按钮区 ----
        btns = tk.Frame(top, bg=UI_BG)
        btns.pack(fill='x', padx=16, pady=(0, 14))
        tk.Button(
            btns, text='翻译', command=self._on_translate_input,
            font=('Microsoft YaHei UI', 11), bg=ACC_TODAY, fg='#06121a',
            relief='flat', bd=0, padx=18, activebackground=ACC_TODAY,
        ).pack(side='left')
        tk.Label(
            btns, text='Enter 翻译 · Shift+Enter 换行',
            font=('Microsoft YaHei UI', 9), bg=UI_BG, fg=UI_MUTED,
        ).pack(side='right')

        # ---- 定位：贴在桌宠右侧（放不下则左侧），夹紧到屏幕内 ----
        top.update_idletasks()
        self._translate_w = max(top.winfo_reqwidth(), 360)
        self._translate_h = top.winfo_reqheight()
        self._place_translate_win()

        top.deiconify()
        top.bind('<Escape>', lambda e: self._on_translate_close())
        text.focus_set()

    def _place_translate_win(self):
        """输入窗口跟随桌宠（规则与琥珀搜索窗一致）。"""
        top = getattr(self, '_translate_win', None)
        if top is None:
            return
        try:
            if not top.winfo_exists():
                return
            win_w = getattr(self, '_translate_w', 360)
            win_h = getattr(self, '_translate_h', 180)
            px = self.root.winfo_x() + self._frame_w + 8
            py = self.root.winfo_y()
            sw = top.winfo_screenwidth()
            sh = top.winfo_screenheight()
            if px + win_w > sw:
                px = self.root.winfo_x() - win_w - 8
            px = max(0, min(px, sw - win_w))
            py = max(0, min(py, sh - win_h))
            top.geometry(f'+{int(px)}+{int(py)}')
            top.attributes('-topmost', True)
        except Exception:
            pass

    def _on_translate_input(self):
        """取输入框内容去翻译（窗口保留，方便改词再翻）。"""
        entry = getattr(self, '_translate_entry', None)
        if entry is None:
            return
        try:
            raw = entry.get('1.0', 'end').strip()
        except tk.TclError:
            return
        if not raw:
            self._toast('先输入要翻译的文字')
            return
        self._translate_text(raw)

    def _on_translate_close(self):
        """关闭输入窗口。"""
        win = getattr(self, '_translate_win', None)
        self._translate_win = None
        self._translate_entry = None
        if win is None:
            return
        try:
            win.destroy()
        except tk.TclError:
            try:
                win.tk.call('destroy', win._w)
            except Exception:
                pass

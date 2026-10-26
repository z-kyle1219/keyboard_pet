"""琥珀：密码存储界面 —— 搜索窗口 + 模糊匹配列表 + 点击解密显示 + 自动清屏。

（名字取自「琥珀把东西封存起来」的意象：别人看得到密文，但打不开。）

流程（用户定稿）：
    录入(手动) → 加密落库 → 桌宠右键 → 搜索框 + 模糊匹配
    → 选中 → 解密显示 → 自动清屏

支持的操作：新增 / 编辑（密码留空即不改）/ 删除 / 显示密码。

设计要点：
- 作为 Mixin 混入 PetApp（与 popup.py / schedule.py 同套路）。
- 「先藏后显」：窗口构建期间 withdraw，全部就绪再 deiconify，
  避免 Windows 闪一下默认浅色空壳（沿用 schedule.py 的做法）。
- 搜索走 vault_search（归一化 + 加权打分），支持 github/GitHub、
  半截词、别名（aliases）命中。
- 密码**只在点击「显示」时**才解密，明文只短暂显示在一个只读框里，
  到点自动清空并关闭；不写日志、不进列表。
- **搜索驱动（隐私）**：窗口默认不铺任何条目名，只有搜索框；
  **必须输入关键词才检索**，查什么名字才出什么结果。避免把全部
  账号清单直接晾在屏幕上。
- 配色沿用 theme 的深空霓虹体系（UI_THEME）。
"""
import tkinter as tk

import db_vault
import vault_crypto
import vault_search
from logger import logger
from pet_ui.theme import (
    ACC_OVERDUE,
    ACC_TODAY,
    UI_BG,
    UI_BORDER,
    UI_MUTED,
    UI_TEXT,
    tint,
)

# 明文自动清屏倒计时（秒）：到点清空显示并关闭密码气泡
#
# 字段（用户定稿）：名称/密码必填，网址选填；账号/别名/备注已去除。
# 条目选中后，「显示密码」气泡会同时展示 名称 + 网址 + 密码。
REVEAL_SECONDS = 12


class VaultMixin:
    """提供密码本窗口相关能力（_show_vault 等）。"""

    # ---------- 打开窗口 ----------
    def _show_vault(self):
        """打开/聚焦密码本搜索窗口。"""
        win = getattr(self, '_vault_win', None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass

        top = tk.Toplevel(self.root)
        self._vault_win = top
        top.title('琥珀')
        top.attributes('-topmost', True)
        top.config(bg=UI_BG)
        top.resizable(False, False)
        top.protocol('WM_DELETE_WINDOW', self._on_vault_close)
        top.withdraw()   # 先藏后显

        # ---- 标题栏 ----
        header = tk.Frame(top, bg=UI_BG)
        header.pack(fill='x', padx=16, pady=(14, 6))
        tk.Label(
            header, text='琥珀', font=('Microsoft YaHei UI', 14, 'bold'),
            bg=UI_BG, fg=UI_TEXT,
        ).pack(side='left')
        self._vault_count_label = tk.Label(
            header, text='', font=('Microsoft YaHei UI', 10),
            bg=UI_BG, fg=UI_MUTED,
        )
        self._vault_count_label.pack(side='right')

        # ---- 搜索框 ----
        search_frame = tk.Frame(top, bg=UI_BG)
        search_frame.pack(fill='x', padx=16, pady=(0, 6))
        self._vault_query = tk.StringVar()
        entry = tk.Entry(
            search_frame, textvariable=self._vault_query,
            font=('Microsoft YaHei UI', 12),
            bg=UI_BG, fg=UI_TEXT, insertbackground=ACC_TODAY,
            relief='flat', highlightthickness=1,
            highlightbackground=UI_BORDER, highlightcolor=ACC_TODAY,
        )
        entry.pack(fill='x', ipady=7)
        # 输入即搜（模糊匹配），回车也可
        entry.bind('<KeyRelease>', lambda e: self._vault_refresh())
        entry.bind('<Return>', lambda e: self._vault_refresh())
        self._vault_entry = entry

        # ---- 结果列表（Listbox 行 = 名称 · 账号 · 网址）----
        list_frame = tk.Frame(top, bg=UI_BG)
        list_frame.pack(fill='both', expand=True, padx=16, pady=(0, 6))
        self._vault_list = tk.Listbox(
            list_frame, height=8, font=('Microsoft YaHei UI', 11),
            bg=UI_BG, fg=UI_TEXT, selectbackground=ACC_TODAY,
            selectforeground='#06121a', relief='flat',
            highlightthickness=1, highlightbackground=UI_BORDER,
            activestyle='none',
        )
        self._vault_list.pack(side='left', fill='both', expand=True)
        vsb = tk.Scrollbar(list_frame, command=self._vault_list.yview)
        vsb.pack(side='right', fill='y')
        self._vault_list.config(yscrollcommand=vsb.set)
        # 双击 = 显示密码（单击只选中，不揭露任何内容）
        self._vault_list.bind('<Double-Button-1>', lambda e: self._on_vault_reveal())
        self._vault_list.bind('<Return>', lambda e: self._on_vault_reveal())

        # ---- 按钮区 ----
        btns = tk.Frame(top, bg=UI_BG)
        btns.pack(fill='x', padx=16, pady=(0, 14))
        tk.Button(
            btns, text='显示密码', command=self._on_vault_reveal,
            font=('Microsoft YaHei UI', 11), bg=ACC_TODAY, fg='#06121a',
            relief='flat', bd=0, padx=14, activebackground=ACC_TODAY,
        ).pack(side='left')
        tk.Button(
            btns, text='新增', command=self._on_vault_add,
            font=('Microsoft YaHei UI', 11), bg=UI_BG, fg=UI_TEXT,
            relief='flat', bd=0, padx=12, highlightthickness=1,
            highlightbackground=UI_BORDER, activebackground=UI_BORDER,
        ).pack(side='left', padx=(8, 0))
        tk.Button(
            btns, text='编辑', command=self._on_vault_edit,
            font=('Microsoft YaHei UI', 11), bg=UI_BG, fg=UI_TEXT,
            relief='flat', bd=0, padx=12, highlightthickness=1,
            highlightbackground=UI_BORDER, activebackground=UI_BORDER,
        ).pack(side='left', padx=(8, 0))
        tk.Button(
            btns, text='删除', command=self._on_vault_delete,
            font=('Microsoft YaHei UI', 11), bg=UI_BG, fg=UI_TEXT,
            relief='flat', bd=0, padx=12, highlightthickness=1,
            highlightbackground=UI_BORDER, activebackground=UI_BORDER,
        ).pack(side='left', padx=(8, 0))

        # ---- 新增 / 编辑区（默认隐藏，点「新增」或「编辑」展开）----
        # 字段：名称/密码必填；网址、备注选填。
        # （账号/别名列保留在表里但前端不再录入；备注已按需加回。）
        # 编辑态与新增态共用此表单：编辑时密码框留空表示「不修改密码」。
        self._vault_editing_id = None   # 非 None 表示当前处于编辑态
        self._vault_add_frame = tk.Frame(top, bg=UI_BG)
        self._vault_add_vars = {}
        self._vault_add_labels = {}
        add_specs = [
            ('name', '名称 *', 18),
            ('password', '密码 *', 16),
            ('url', '网址', 18),
            ('note', '备注', 18),
        ]
        for key, label, width in add_specs:
            row = tk.Frame(self._vault_add_frame, bg=UI_BG)
            row.pack(fill='x', pady=2)
            lab = tk.Label(
                row, text=label, width=16, anchor='w',
                font=('Microsoft YaHei UI', 10), bg=UI_BG, fg=UI_MUTED,
            )
            lab.pack(side='left')
            self._vault_add_labels[key] = lab
            var = tk.StringVar()
            self._vault_add_vars[key] = var
            # 密码框右侧留一个「小眼睛」开关（先 pack 右侧，占住位置）
            eye = None
            if key == 'password':
                eye = tk.Label(
                    row, text='👁', font=('Microsoft YaHei UI', 12),
                    bg=UI_BG, fg=UI_MUTED, cursor='hand2',
                )
                eye.pack(side='right', padx=(4, 2))
                eye.bind('<Button-1>', lambda e: self._toggle_pw_visible())
                # 用默认参数把 eye 当场绑死：否则 lambda 晚绑定，
                # 事件触发时读到的 eye 已是循环结束后的 None。
                eye.bind('<Enter>', lambda e, w=eye: w.config(fg=ACC_TODAY))
                eye.bind('<Leave>', lambda e, w=eye: w.config(fg=UI_MUTED))
                self._vault_eye = eye
            entry = tk.Entry(
                row, textvariable=var, width=width,
                show='*' if key == 'password' else '',
                font=('Microsoft YaHei UI', 11),
                bg=UI_BG, fg=UI_TEXT, insertbackground=ACC_TODAY,
                relief='flat', highlightthickness=1,
                highlightbackground=UI_BORDER, highlightcolor=ACC_TODAY,
            )
            entry.pack(side='left', fill='x', expand=True, ipady=4)
            if key == 'password':
                self._vault_pw_entry = entry
                self._vault_pw_visible = False
        self._vault_form_hint = tk.Label(
            self._vault_add_frame, text='* 为必填；网址/备注选填',
            font=('Microsoft YaHei UI', 9), bg=UI_BG, fg=UI_MUTED,
            anchor='w',
        )
        self._vault_form_hint.pack(fill='x', pady=(4, 0))
        self._vault_save_btn = tk.Button(
            self._vault_add_frame, text='保存', command=self._on_vault_save,
            font=('Microsoft YaHei UI', 11), bg=ACC_TODAY, fg='#06121a',
            relief='flat', bd=0, padx=16, activebackground=ACC_TODAY,
        )
        self._vault_save_btn.pack(anchor='e', pady=(6, 0))

        # ---- 定位：贴在桌宠右侧（放不下则左侧），夹紧到屏幕内 ----
        top.update_idletasks()
        win_w = max(top.winfo_reqwidth(), 380)
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

        # 内容就绪：刷新列表并显示
        self._vault_refresh()
        top.deiconify()
        # Esc 退出编辑态（若有）
        top.bind('<Escape>', lambda e: self._vault_cancel_edit())
        entry.focus_set()

    def _on_vault_close(self):
        """关闭密码本窗口（同时清掉可能的明文显示）。"""
        self._clear_reveal()
        try:
            if getattr(self, '_vault_win', None) is not None:
                self._vault_win.destroy()
        except Exception:
            pass
        self._vault_win = None

    # ---------- 列表刷新 ----------
    def _vault_build_rows(self):
        """按当前搜索词取「命中记录」列表。

        **必须有关键词才检索**：空词返回空列表，窗口打开时不铺任何条目名，
        避免把全部账号清单晾在屏幕上。查什么名字才出什么结果。
        """
        q = self._vault_query.get().strip()
        if not q:
            return []
        return vault_search.search(q, db_vault.list_accounts())

    def _vault_refresh(self):
        """重画结果列表（搜索词改变 / 数据变化后调用）。"""
        if not self._vault_ui_ready():
            return
        q = self._vault_query.get().strip()
        rows = self._vault_build_rows()
        self._vault_rows = rows
        self._vault_list.delete(0, 'end')
        # 结果行只显示条目名（登录账号/网址等细节留给「显示密码」气泡），
        # 降低无关信息在屏幕上的暴露面。
        for r in rows:
            self._vault_list.insert('end', r['name'])
        total = db_vault.count_accounts()
        if not q:
            hint = f'共 {total} 条 · 输入关键词开始检索' if total \
                else '还没有条目，点「新增」录一条'
            self._vault_count_label.config(text=hint)
        elif not rows:
            self._vault_count_label.config(text=f'未找到匹配项（共 {total} 条）')
        else:
            self._vault_count_label.config(
                text=f'匹配 {len(rows)}/{total} 条')

    def _vault_ui_ready(self):
        win = getattr(self, '_vault_win', None)
        return (win is not None
                and getattr(self, '_vault_list', None) is not None)

    def _vault_selected(self):
        """当前选中的记录 dict；未选中返回 None。"""
        if getattr(self, '_vault_list', None) is None:
            return None
        sel = self._vault_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        rows = getattr(self, '_vault_rows', [])
        if 0 <= idx < len(rows):
            return rows[idx]
        return None

    # ---------- 动作 ----------
    def _on_vault_reveal(self):
        """显示选中条目的密码：解密 → 只读显示 → 自动清屏。"""
        rec = self._vault_selected()
        if rec is None:
            self._toast('先选中一条记录')
            return
        try:
            plain = vault_crypto.decrypt(rec['password_enc'])
        except Exception:
            # 注意：绝不把密文/明文/异常细节抛给用户
            logger.exception('密码解密失败（条目 id=%s）', rec.get('id'))
            self._toast('解密失败：密文损坏或换了机器/账户')
            return
        self._show_reveal_window(rec, plain)

    def _show_reveal_window(self, rec, plain):
        """弹出密码显示气泡，显示明文，可点「✕」手动关闭，
        或到 REVEAL_SECONDS 后自动清屏关闭。"""
        self._clear_reveal()

        win = tk.Toplevel(self.root)
        self._reveal_win = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.config(bg=UI_BG)
        win.withdraw()
        # Esc 也可手动关闭
        win.bind('<Escape>', lambda e: self._clear_reveal())

        pad = 14
        frame = tk.Frame(win, bg=UI_BG, highlightthickness=1,
                         highlightbackground=ACC_TODAY)
        frame.pack(fill='both', expand=True)

        # 标题行：左名称 + 右「×」手动关闭（复制完可自己叉掉）
        head = tk.Frame(frame, bg=UI_BG)
        head.pack(fill='x', padx=pad, pady=(pad, 2))
        tk.Label(
            head, text=rec['name'], font=('Microsoft YaHei UI', 12, 'bold'),
            bg=UI_BG, fg=UI_TEXT, anchor='w',
        ).pack(side='left')
        close_btn = tk.Label(
            head, text='✕', font=('Microsoft YaHei UI', 12),
            bg=UI_BG, fg=UI_MUTED, cursor='hand2',
        )
        close_btn.pack(side='right')
        close_btn.bind('<Button-1>', lambda e: self._clear_reveal())
        # 悬停变红，暗示「关掉」
        close_btn.bind(
            '<Enter>', lambda e: close_btn.config(fg=ACC_OVERDUE))
        close_btn.bind(
            '<Leave>', lambda e: close_btn.config(fg=UI_MUTED))

        # 网址：与密码一同展示（用户要求“网址和密码一块显示”）
        if rec.get('url'):
            tk.Label(
                frame, text=f'网址：{rec["url"]}',
                font=('Microsoft YaHei UI', 10), bg=UI_BG, fg=UI_MUTED,
                anchor='w',
            ).pack(fill='x', padx=pad)
            tk.Button(
                frame, text='打开网址',
                command=lambda u=rec['url']: self._open_url(u),
                font=('Microsoft YaHei UI', 9), bg=UI_BG, fg=ACC_TODAY,
                relief='flat', bd=0, cursor='hand2',
                activebackground=UI_BG,
            ).pack(anchor='w', padx=pad)

        # 备注：一并展示（若有）
        if rec.get('note'):
            tk.Label(
                frame, text=f'备注：{rec["note"]}',
                font=('Microsoft YaHei UI', 10), bg=UI_BG, fg=UI_MUTED,
                anchor='w', justify='left', wraplength=260,
            ).pack(fill='x', padx=pad)

        # 密码：只读 Entry（可全选复制），明文只在此短暂存在
        pw_var = tk.StringVar(value=plain)
        pw_entry = tk.Entry(
            frame, textvariable=pw_var, font=('Consolas', 13),
            bg=tint(ACC_TODAY, UI_BG, 0.12), fg=UI_TEXT, relief='flat',
            readonlybackground=tint(ACC_TODAY, UI_BG, 0.12),
            highlightthickness=0, justify='center',
        )
        pw_entry.configure(state='readonly')
        pw_entry.pack(fill='x', padx=pad, pady=(8, 4), ipady=6)
        pw_entry.focus_set()
        pw_entry.selection_range(0, 'end')

        tk.Button(
            frame, text='复制密码', command=lambda: self._copy_text(plain),
            font=('Microsoft YaHei UI', 9), bg=UI_BG, fg=ACC_TODAY,
            relief='flat', bd=0, cursor='hand2', activebackground=UI_BG,
        ).pack(anchor='w', padx=pad, pady=(0, 2))

        countdown = tk.Label(
            frame, text='', font=('Microsoft YaHei UI', 9),
            bg=UI_BG, fg=UI_MUTED,
        )
        countdown.pack(fill='x', padx=pad, pady=(0, pad))

        win.update_idletasks()
        w = max(win.winfo_reqwidth(), 260)
        h = win.winfo_reqheight()
        x = self.root.winfo_x() + self._frame_w // 2 - w // 2
        y = self.root.winfo_y() - h - 8
        if y < 0:
            y = self.root.winfo_y() + self._frame_h + 8
        win.geometry(f'{w}x{h}+{x}+{y}')
        win.deiconify()

        # 倒计时自动清屏：先清明文，再关窗口
        self._reveal_after_ids = []

        def _tick(remain):
            if not self._reveal_exists():
                return
            if remain <= 0:
                self._clear_reveal()
                return
            try:
                countdown.config(text=f'{remain} 秒后自动清屏')
            except Exception:
                return
            aid = win.after(1000, lambda r=remain - 1: _tick(r))
            self._reveal_after_ids.append(aid)

        _tick(REVEAL_SECONDS)

    def _reveal_exists(self):
        try:
            return (getattr(self, '_reveal_win', None) is not None
                    and self._reveal_win.winfo_exists())
        except Exception:
            return False

    def _clear_reveal(self):
        """清掉明文显示并销毁密码气泡（幂等）。"""
        win = getattr(self, '_reveal_win', None)
        self._reveal_win = None
        for aid in getattr(self, '_reveal_after_ids', []):
            try:
                win.after_cancel(aid)
            except Exception:
                pass
        self._reveal_after_ids = []
        if win is None:
            return
        try:
            win.destroy()
        except tk.TclError:
            try:
                win.tk.call('destroy', win._w)
            except Exception:
                pass

    def _toggle_pw_visible(self):
        """小眼睛：在掩码 / 明文之间切换密码框显示，方便确认输对没。"""
        entry = getattr(self, '_vault_pw_entry', None)
        eye = getattr(self, '_vault_eye', None)
        if entry is None:
            return
        self._vault_pw_visible = not getattr(self, '_vault_pw_visible', False)
        try:
            entry.config(show='' if self._vault_pw_visible else '*')
        except Exception:
            return
        # 显示明文时眼睛点亮为主色，提示当前状态
        if eye is not None:
            try:
                eye.config(fg=ACC_TODAY if self._vault_pw_visible else UI_MUTED)
            except Exception:
                pass

    def _reset_pw_visible(self):
        """把密码框恢复为掩码态（切换表单模式 / 保存 / 取消时调用）。"""
        self._vault_pw_visible = False
        entry = getattr(self, '_vault_pw_entry', None)
        if entry is not None:
            try:
                entry.config(show='*')
            except Exception:
                pass
        eye = getattr(self, '_vault_eye', None)
        if eye is not None:
            try:
                eye.config(fg=UI_MUTED)
            except Exception:
                pass

    def _on_vault_add(self):
        """展开/折叠新增表单（新增态）。

        若当前正处于编辑态，点「新增」视为退出编辑、切换到新增态。
        """
        f = self._vault_add_frame
        # 已在新增态且表单已展开 → 收起
        if f.winfo_ismapped() and self._vault_editing_id is None:
            f.pack_forget()
            return
        self._enter_form_mode(editing_id=None)

    def _on_vault_edit(self):
        """编辑选中条目：把名称/网址填回表单，密码框留空（留空=不改密码）。"""
        rec = self._vault_selected()
        if rec is None:
            self._toast('先选中一条记录')
            return
        self._enter_form_mode(editing_id=rec['id'], rec=rec)

    def _enter_form_mode(self, editing_id, rec=None):
        """切到表单态（新增或编辑），统一处理填值、文案、按钮与定位。"""
        self._vault_editing_id = editing_id
        self._reset_pw_visible()   # 每次进入表单都回到掩码态
        v = self._vault_add_vars
        # 清空后按需回填
        for var in v.values():
            var.set('')
        if editing_id is not None and rec is not None:
            v['name'].set(rec.get('name', ''))
            v['url'].set(rec.get('url', ''))
            v['note'].set(rec.get('note', ''))
            # 密码框留空：不回填明文，留空即不修改
            self._vault_add_labels['password'].config(
                text='密码（留空不改）', width=16)
            self._vault_form_hint.config(
                text='编辑中：密码留空则保持原密码不变')
            self._vault_save_btn.config(text='保存修改')
        else:
            self._vault_add_labels['password'].config(
                text='密码 *', width=16)
            self._vault_form_hint.config(
                text='* 为必填；网址/备注选填')
            self._vault_save_btn.config(text='保存')

        f = self._vault_add_frame
        if not f.winfo_ismapped():
            f.pack(fill='x', padx=16, pady=(0, 12))
        # 窗口变高后重新夹紧到屏幕内，避免超出下边界
        try:
            self._vault_win.update_idletasks()
            win = self._vault_win
            h = win.winfo_reqheight()
            sh = win.winfo_screenheight()
            py = min(win.winfo_y(), max(0, sh - h))
            win.geometry(f'+{win.winfo_x()}+{int(py)}')
        except Exception:
            pass
        try:
            self._vault_win.focus_force()
        except Exception:
            pass

    def _vault_cancel_edit(self):
        """取消编辑/收起表单（Esc 或保存后调用）。"""
        self._vault_editing_id = None
        self._reset_pw_visible()
        for var in self._vault_add_vars.values():
            var.set('')
        self._vault_add_labels['password'].config(text='密码 *', width=16)
        self._vault_form_hint.config(
            text='* 为必填；网址/备注选填')
        self._vault_save_btn.config(text='保存')
        try:
            self._vault_add_frame.pack_forget()
        except Exception:
            pass

    def _on_vault_save(self):
        """保存：新增走 add，编辑走 update（密码留空则不改）。

        密码先加密再落库（绝不存明文）。
        """
        v = self._vault_add_vars
        name = v['name'].get().strip()
        password = v['password'].get()
        editing = self._vault_editing_id
        if not name:
            self._toast('名称不能为空')
            return
        # 新增：密码必填；编辑：密码可留空（表示不改）
        if editing is None and not password:
            self._toast('密码不能为空')
            return

        enc = None
        if password:
            try:
                enc = vault_crypto.encrypt(password)
            except Exception:
                logger.exception('密码加密失败')
                self._toast('加密失败，无法保存')
                return
        try:
            if editing is None:
                db_vault.add_account(
                    name=name, password_enc=enc, url=v['url'].get(),
                    note=v['note'].get(),
                )
            else:
                # password_enc=None 时 update_account 保持原密码不变
                ok = db_vault.update_account(
                    editing, name=name, url=v['url'].get(),
                    password_enc=enc, note=v['note'].get(),
                )
                if not ok:
                    self._toast('修改失败：条目可能已被删除')
                    return
        except Exception:
            logger.exception('保存琥珀条目失败')
            self._toast('保存失败')
            return
        self._vault_cancel_edit()
        self._vault_refresh()
        self._toast('已保存修改' if editing is not None else '已保存')

    # ---------- 小工具 ----------
    def _open_url(self, url):
        """用默认浏览器打开网址（自动补 https://）。"""
        import webbrowser
        target = url if '://' in url else 'https://' + url
        try:
            webbrowser.open(target)
        except Exception:
            logger.exception('打开网址失败')
            self._toast('打开网址失败')

    def _copy_text(self, text):
        """把文本复制到系统剪贴板。"""
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._toast('已复制')
        except Exception:
            logger.exception('复制失败')
            self._toast('复制失败')

    def _on_vault_delete(self):
        """删除选中条目（二次确认，避免误删）。"""
        rec = self._vault_selected()
        if rec is None:
            self._toast('先选中一条记录')
            return
        if not self._vault_confirm(f'删除「{rec["name"]}」？此操作不可恢复'):
            return
        try:
            db_vault.delete_account(rec['id'])
        except Exception:
            logger.exception('删除琥珀条目失败')
            self._toast('删除失败')
            return
        # 若正在编辑的正是被删的这条，退出编辑态避免保存到已删条目
        if self._vault_editing_id == rec['id']:
            self._vault_cancel_edit()
        self._vault_refresh()
        self._toast('已删除')

    def _vault_confirm(self, message):
        """轻量确认框（返回布尔）。"""
        from tkinter import messagebox
        try:
            return messagebox.askyesno('确认', message, parent=self._vault_win)
        except Exception:
            return False

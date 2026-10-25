"""琥珀：密码存储界面 —— 搜索窗口 + 模糊匹配列表 + 点击解密显示 + 自动清屏。

（名字取自「琥珀把东西封存起来」的意象：别人看得到密文，但打不开。）

流程（用户定稿）：
    录入(手动) → 加密落库 → 桌宠右键 → 搜索框 + 模糊匹配
    → 选中 → 解密显示 → 自动清屏

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
    ACC_TODAY,
    UI_BG,
    UI_BORDER,
    UI_MUTED,
    UI_TEXT,
    tint,
)

# 明文自动清屏倒计时（秒）：到点清空显示并关闭密码气泡
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
            btns, text='删除', command=self._on_vault_delete,
            font=('Microsoft YaHei UI', 11), bg=UI_BG, fg=UI_MUTED,
            relief='flat', bd=0, padx=12, highlightthickness=1,
            highlightbackground=UI_BORDER, activebackground=UI_BORDER,
        ).pack(side='left', padx=(8, 0))

        # ---- 新增区（默认隐藏，点「新增」展开）----
        self._vault_add_frame = tk.Frame(top, bg=UI_BG)
        self._vault_add_vars = {}
        add_specs = [
            ('name', '名称', 18),
            ('url', '网址', 18),
            ('username', '账号', 18),
            ('password', '密码', 18),
            ('aliases', '别名(逗号分隔)', 18),
            ('note', '备注', 18),
        ]
        for key, label, width in add_specs:
            row = tk.Frame(self._vault_add_frame, bg=UI_BG)
            row.pack(fill='x', pady=2)
            tk.Label(
                row, text=label, width=14, anchor='w',
                font=('Microsoft YaHei UI', 10), bg=UI_BG, fg=UI_MUTED,
            ).pack(side='left')
            var = tk.StringVar()
            self._vault_add_vars[key] = var
            tk.Entry(
                row, textvariable=var, width=width,
                show='*' if key == 'password' else '',
                font=('Microsoft YaHei UI', 11),
                bg=UI_BG, fg=UI_TEXT, insertbackground=ACC_TODAY,
                relief='flat', highlightthickness=1,
                highlightbackground=UI_BORDER, highlightcolor=ACC_TODAY,
            ).pack(side='left', fill='x', expand=True, ipady=4)
        tk.Button(
            self._vault_add_frame, text='保存', command=self._on_vault_save,
            font=('Microsoft YaHei UI', 11), bg=ACC_TODAY, fg='#06121a',
            relief='flat', bd=0, padx=16, activebackground=ACC_TODAY,
        ).pack(anchor='e', pady=(6, 0))

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
        """弹出密码显示气泡，显示明文并在 REVEAL_SECONDS 后自动清屏关闭。"""
        self._clear_reveal()

        win = tk.Toplevel(self.root)
        self._reveal_win = win
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.config(bg=UI_BG)
        win.withdraw()

        pad = 14
        frame = tk.Frame(win, bg=UI_BG, highlightthickness=1,
                         highlightbackground=ACC_TODAY)
        frame.pack(fill='both', expand=True)

        tk.Label(
            frame, text=rec['name'], font=('Microsoft YaHei UI', 12, 'bold'),
            bg=UI_BG, fg=UI_TEXT, anchor='w',
        ).pack(fill='x', padx=pad, pady=(pad, 2))
        if rec['username']:
            tk.Label(
                frame, text=f'账号：{rec["username"]}',
                font=('Microsoft YaHei UI', 10), bg=UI_BG, fg=UI_MUTED,
                anchor='w',
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

    def _on_vault_add(self):
        """展开/折叠新增表单。"""
        f = self._vault_add_frame
        if f.winfo_ismapped():
            f.pack_forget()
            return
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

    def _on_vault_save(self):
        """保存新条目：密码先加密再落库（绝不存明文）。"""
        v = self._vault_add_vars
        name = v['name'].get().strip()
        password = v['password'].get()
        if not name:
            self._toast('名称不能为空')
            return
        if not password:
            self._toast('密码不能为空')
            return
        try:
            enc = vault_crypto.encrypt(password)
        except Exception:
            logger.exception('密码加密失败')
            self._toast('加密失败，无法保存')
            return
        try:
            db_vault.add_account(
                name=name, password_enc=enc,
                url=v['url'].get(), username=v['username'].get(),
                aliases=v['aliases'].get(), note=v['note'].get(),
            )
        except Exception:
            logger.exception('保存密码条目失败')
            self._toast('保存失败')
            return
        # 清空表单并收起
        for var in v.values():
            var.set('')
        self._vault_add_frame.pack_forget()
        self._vault_refresh()
        self._toast('已保存')

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
            logger.exception('删除密码条目失败')
            self._toast('删除失败')
            return
        self._vault_refresh()
        self._toast('已删除')

    def _vault_confirm(self, message):
        """轻量确认框（返回布尔）。"""
        from tkinter import messagebox
        try:
            return messagebox.askyesno('确认', message, parent=self._vault_win)
        except Exception:
            return False

# 键盘计数桌宠 — 项目结构说明

> 这是一个记录每天键盘点击次数的桌面宠物。项目采用标准 Python 模块化结构。

## 一、目录结构

```
keyboard_pet/
│
├── main.py              # 程序入口：启动键盘监听 + 桌宠窗口 + 后台线程（含异常兜底）
├── autostart.py         # 开机自启动（启动文件夹 + VBS 静默启动器）
├── logger.py            # 运行日志（写入 pet.log，避免异常无声消失）
├── config.py            # 配置与路径（find_icon 自动扫描 assets/ 图标）
├── db.py                # SQLite 数据层（daily_stats 表，按天聚合）
├── tracker.py           # 计数核心：线程安全的当天计数 + 跨天滚动
├── listener.py          # 全局键盘监听（pynput，仅键盘）
├── scheduler.py         # 后台线程：24:00 跨天刷新 + 每 60s 落库
├── pet_ui.py            # 桌宠界面：透明漂浮窗 + 左键气泡 + 右键菜单 + 图标处理
│
├── assets/              # 资源目录
│   └── *.jpg             # 桌宠图标（自动扫描取第一张图片）
│
├── keyboard_stats.db    # SQLite 数据库（运行时自动生成）
├── config.json          # 用户配置（图标路径等，运行时自动生成）
│
├── run.bat              # Windows 一键启动脚本
├── pyproject.toml       # uv 项目配置（依赖声明）
├── requirements.txt     # pip 依赖清单（备用）
├── README.md            # 使用说明
└── PROJECT_STRUCTURE.md # 本文档
```

## 二、各模块职责

| 文件 | 职责 | 关键点 |
|------|------|--------|
| **main.py** | 程序入口 | 串起监听、窗口、后台线程；全局 try/except 兜底 + 退出前落库 |
| **autostart.py** | 开机自启动 | 「启动」文件夹写入 `KeyboardPet.vbs`，用 pythonw 无窗口启动 main.py；开启/关闭 |
| **logger.py** | 日志 | 写入 `pet.log`（UTF-8）；配合各模块排查运行时问题 |
| **config.py** | 路径与配置 | `find_icon()` 自动扫描 `assets/` 取第一张图片；JSON 持久化 |
| **db.py** | 数据存取 | `daily_stats(date PRIMARY KEY, count)` 按天一行；支持读写/查近7天/查全部历史 |
| **tracker.py** | 计数核心 | 线程安全 `Lock`；跨天归档；重启恢复当天次数 |
| **listener.py** | 键盘监听 | `pynput.keyboard.Listener`；仅键盘（含修饰键），鼠标不计 |
| **scheduler.py** | 定时任务 | `midnight_loop` 等 24:00 跨天滚动；`periodic_save` 每 60s 落库 |
| **pet_ui.py** | 界面交互 | 透明漂浮窗、拖拽、左键气泡、右键表格、`make_pet_image` 圆角处理 |

## 三、数据模型

```sql
CREATE TABLE daily_stats (
    date  TEXT PRIMARY KEY,   -- '2026-10-12'
    count INTEGER NOT NULL    -- 当天总次数（仅键盘，含修饰键）
);
```

- 每天 24:00：把当天 `count` 写入该表 → 清空 → 开始新的一天
- `db.get_recent_days(7)`：查询最近 7 天记录（右键"查看历史"）

## 四、图标方案

- **默认**：`find_icon()` 自动扫描 `assets/` 目录，取第一张图片（png/jpg/jpeg/gif/bmp）
- **更换**：右键桌宠 → 更换图标，或直接替换 `assets/` 里的图片
- **JPG 处理**：`make_pet_image()` 做居中裁切 + 圆角遮罩 + 边缘羽化，避免矩形生硬

## 五、运行

```bash
cd D:\keyboard_pet
# 方式一：uv
uv run python main.py
# 方式二：pip + python
python -m pip install -r requirements.txt
python main.py
# 或直接双击 run.bat
```

## 六、交互说明

| 操作 | 效果 |
|------|------|
| 拖动图标 | 拖到任意位置 |
| 左键单击 | 弹气泡「宝宝今天点击键盘的次数是 X，快去休息吧~」 |
| 右键 → 最近 7 天 | 弹出表格，展示近 7 天记录（日期 | 次数） |
| 右键 → 历史所有 | 弹出表格，展示全部历史记录（日期 | 次数） |
| 右键 → 更换图标 | 上传自定义图片 |
| 右键 → 开机自启动 | 切换开关；勾选 = 开机自动常驻 |
| 右键 → 退出 | 退出程序（自动落库） |

> 历史查看统一使用 `ttk.Treeview` 表格呈现，带「日期」「次数」两列表头及滚动条。

## 七、健壮性与设计细节

1. **异常兜底**：`main.py` 用全局 try/except 包围，任意异常写入 `pet.log` 而非无声退出；`pet_ui._load_icon` 图片加载失败时回退到 `_placeholder_icon()` 占位图并记日志。
2. **跨天前置检查**：`tracker.increment()` 在每次 +1 前先检查日期是否变化（`now != self._today`），若已跨天立即归档旧的一天再计数，避免依赖 `midnight_loop` 线程因休眠/挂起漏滚动。
3. **长按计数口径**：长按一键时 `pynput` 自动重复触发 `on_press`，每次均 +1，与单击效果一致（均计入）。
4. **落库容错**：`tracker.persist()`、跨天归档均用 try/except 包裹，写库失败只记日志，不拖垮程序。

## 八、UI 设计（已优化）

1. **DPI 感知**：`main.py` 在创建窗口前开启 `SetProcessDpiAwareness(2)`（per-monitor），解决高分屏下 `tkinter` 文字模糊成像素块的问题。
2. **时尚气泡**：左键点击、自启动提示改用 `_popup()`，绘制圆角卡片（`rounded_rectangle`）+ 水母粉描边 + 顶部色条 + 渐入渐淡动画。
3. **气泡跟随**：拖拽图标时，已显示的悬浮气泡通过 `_on_motion` 同步重定位，不再留在原地（`_active_popup` + `_popup_offset`）。
4. **历史表格美化**：`_show_table` 用粉色头部卡片 + `ttk.Style`（行高 32、隔行变色、清晰微软雅黑 UI 字体），并 try/except 兜底样式失败。
5. **菜单字体**：右键菜单用 `Microsoft YaHei UI` 和主色高亮，更清晰时尚。


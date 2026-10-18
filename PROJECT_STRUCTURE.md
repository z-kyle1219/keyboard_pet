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
├── db.py                # SQLite 数据层（daily_stats 按天聚合 + daily_key_stats 按键明细）
├── db_todo.py           # SQLite 待办数据层（todo 表：标题/截止/是否完成/完成时刻）
├── tracker.py           # 计数核心：线程安全的当天计数 + 按键明细 + 跨天滚动
├── listener.py          # 全局键盘监听（pynput，仅键盘）
├── scheduler.py         # 后台线程：24:00 跨天刷新 + 周期落库
├── pet_ui/              # 桌宠界面包（原单文件 pet_ui.py 拆分而来）
│   ├── __init__.py      # 对外导出 PetApp（导入方式保持不变）
│   ├── theme.py         # 配色与渲染参数常量
│   ├── renderer.py      # 图像流水线（Pillow：抠底/阴影/帧合成/占位图）
│   ├── animations.py    # 呼吸 / 挤压回弹 / 拖拽拎起动画
│   ├── popup.py         # 气泡卡片 + MVP 徽章 + 冠军登场特效
│   ├── heatmap.py       # 键盘热力图窗口
│   ├── table.py         # 历史表格（近 7 天 / 全部）
│   ├── schedule.py      # 日程表（独立窗口 + 头顶角标）
│   └── app.py           # PetApp 主类：窗口 / 图标 / 拖拽 / 右键菜单
│
├── assets/              # 资源目录
│   ├── *.png             # 桌宠图标（优先带透明通道的 PNG，人物轮廓最佳）
│   └── *.jpg             # 无透明图时兜底（圆角显示）
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
| **config.py** | 路径与配置 | `find_icon()` 优先扫描 `assets/` 里带透明通道的 PNG（回退任意图片）；JSON 持久化 |
| **db.py** | 数据存取 | `daily_stats` 按天聚合 + `daily_key_stats` 按键明细；提供 `get_daily_mvp` 冠军键查询 |
| **db_todo.py** | 待办数据层 | `todo` 表（标题/截止/是否完成/完成时刻）；未完成轮换、勾掉留一天的查询逻辑 |
| **tracker.py** | 计数核心 | 线程安全 `Lock`；累计各键次数；跨天归档；重启恢复当天数据 |
| **listener.py** | 键盘监听 | `pynput.keyboard.Listener`；仅键盘（含修饰键），鼠标不计 |
| **scheduler.py** | 定时任务 | `midnight_loop` 等 24:00 跨天滚动；`periodic_save` 每 20s 落库 |
| **pet_ui/app.py** | 界面主类 | 透明漂浮窗（人物轮廓+阴影）、拖拽拎起、右键菜单、更换图标、帧预生成 |
| **pet_ui/renderer.py** | 图像渲染 | `_prepare_pet` / `_make_shadow` / `_compose_frame` / `frame_to_photo` / 占位图 |
| **pet_ui/animations.py** | 动画 | 呼吸循环、点击挤压回弹、拖拽拎起状态机 |
| **pet_ui/popup.py** | 气泡 | 自适应圆角卡片、MVP 徽章、冠军登场特效、气泡跟随与关闭兜底 |
| **pet_ui/heatmap.py** | 热力图 | 26 键实时热度、环形扩散特效、HOT KEY 统计 |
| **pet_ui/table.py** | 历史表格 | `ttk.Treeview` 三列（日期/次数/MVP 键）、隔行变色 |
| **pet_ui/schedule.py** | 日程表 | 独立日程窗口（卡片+勾选+进度条，第三列完整汉字日期时间）；头顶角标（临近截止变红） |
| **pet_ui/theme.py** | 常量 | 配色、DPI 与动画参数集中管理 |

> 拆分后各模块通过 Mixin 混入 `PetApp`（`AnimationMixin` / `PopupMixin` / `HeatmapMixin` / `TableMixin` / `ScheduleMixin`），
> `main.py` 的 `from pet_ui import PetApp` 无需任何改动，UI 行为与拆分前完全一致。

## 三、数据模型

```sql
CREATE TABLE daily_stats (
    date  TEXT PRIMARY KEY,   -- '2026-10-12'
    count INTEGER NOT NULL    -- 当天总次数（仅键盘，含修饰键）
);

CREATE TABLE daily_key_stats (
    date  TEXT NOT NULL,      -- '2026-10-12'
    key   TEXT NOT NULL,      -- 按键名（如 'e'、'space'）
    count INTEGER NOT NULL,   -- 该键当天次数
    PRIMARY KEY (date, key)
);
```

- 每天 24:00：把当天总次数与各键次数写入上述两表 → 清空 → 开始新的一天
- `db.get_daily_mvp(days)`：查询历史记录（日期 | 次数 | MVP 键）；MVP 键仅从 26 个英文字母中选出

### 待办日程表

```sql
CREATE TABLE todo (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,               -- 待办标题
    due_at     TEXT NOT NULL,               -- 截止时间 'YYYY-MM-DD HH:MM'（排序键）
    done       INTEGER NOT NULL DEFAULT 0,  -- 0未完成 / 1已完成
    done_at    TEXT,                        -- 完成时刻（勾掉留一天用）
    created_at TEXT DEFAULT (datetime('now','localtime'))  -- 创建时间，调试用
);
CREATE INDEX idx_todo_due_at ON todo(due_at);
```

业务规则（用户定稿）：
- **勾掉留一天**：`done=1` 时写入 `done_at`；查询时只显示 `done_at` 属于当天的已完成项，第二天自动隐藏。
- **没做轮换下一天**：`done=0` 的未完成项 `due_at` 不随日期变化，第二天查询自然还在。
- **排序**：`ORDER BY due_at` 升序（近→远）。
- **单字段 `due_at`**：既做排序，又经 `format_due()` 转成汉字 `2026年10月19日 14时00分` 展示，还能用 `substr(due_at,1,10)` 统计今天/过期/未来。
- **无优先级、无完成率/近7天统计**。

列表第三列显示完整汉字日期时间（近→远）；已过期标红、今天截止标粉。
新增待办时用户只填「年月日时分」数字框，由 `_compose_due()` 拼成 `due_at` 存库。

待办查询由 `db_todo.get_today_todos()` 实现：`WHERE done=0 OR done_at LIKE '今天%' ORDER BY due_at`。

## 四、图标方案

- **默认**：`find_icon()` 自动扫描 `assets/` 目录，优先选带透明通道的 PNG（人物轮廓最适合做桌宠），找不到透明图时回退到任意第一张图片（png/jpg/jpeg/gif/bmp）
- **更换**：右键桌宠 → 更换图标，或直接替换 `assets/` 里的图片
- **透明图处理**：`_prepare_pet()` 等比缩放到 `PET_HEIGHT` 高度，保留人物轮廓，`_compose_frame()` 在人物底部叠加柔和椭圆阴影
- **无透明图兜底**：居中裁切 + 圆角遮罩 + 边缘羽化，避免矩形生硬
- **立体互动动画**：呼吸（人物上浮+阴影缩放）、点击挤压回弹、拖拽拎起（阴影缩小+人物上浮）

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
| 待机 | 呼吸动画：人物轻微上下浮动，阴影随之缩放 |
| 拖动图标 | 拖到任意位置（拖拽时人物"拎起"：阴影缩小、人物上浮） |
| 左键单击 | 挤压回弹动画 + 弹气泡（统计）+ 弹日程窗口（待办，方案 A 分离式） |
| 头顶角标 | 常驻显示「N 待办」；存在临近截止（≤12h）的待办时由粉色变红 |
| 右键 → 最近 7 天 | 弹出表格，展示近 7 天记录（日期 | 次数 | MVP 键） |
| 右键 → 历史所有 | 弹出表格，展示全部历史记录（日期 | 次数 | MVP 键） |
| 右键 → 键盘热力图 | 弹出 26 键实时热度面板 |
| 右键 → 更换图标 | 上传自定义图片 |
| 右键 → 开机自启动 | 切换开关；勾选 = 开机自动常驻 |
| 右键 → 退出 | 退出程序（自动落库） |

> 历史查看统一使用 `ttk.Treeview` 表格呈现，带「日期」「次数」「MVP 键」三列表头及纵向/横向滚动条。

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

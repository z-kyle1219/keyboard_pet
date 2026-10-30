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
├── db_vault.py          # SQLite 琥珀数据层（vault_accounts 表；只存密文）
├── vault_crypto.py      # 琥珀加密层（Windows DPAPI，明文永不落库）
├── vault_search.py      # 琥珀模糊匹配（归一化 + 多字段加权打分，纯函数）
├── tracker.py           # 计数核心：线程安全的当天计数 + 按键明细 + 跨天滚动
├── listener.py          # 全局键盘监听（pynput，仅键盘）
├── foreground.py        # 前台窗口检测（纯 ctypes，取当前 exe 名 + HWND 缓存）
├── app_usage.py         # 按应用统计（敲键次数 + 前台停留秒数 + 跨天归档）
├── app_aliases.py       # exe → 友好名 + 分类 的映射（读 app_aliases.json）
├── stats_export.py      # 稳定 JSON 出口（app_stats.json，供 AI 读取）
├── scheduler.py         # 后台线程：24:00 跨天刷新 + 周期落库 + JSON 导出
├── translate.py         # 翻译（百度翻译 API：方向判断 + 内存 LRU 缓存，纯逻辑）
├── pet_ui/              # 桌宠界面包（原单文件 pet_ui.py 拆分而来）
│   ├── __init__.py      # 对外导出 PetApp（导入方式保持不变）
│   ├── theme.py         # 配色与渲染参数常量
│   ├── renderer.py      # 图像流水线（Pillow：抠底/阴影/帧合成/占位图）
│   ├── animations.py    # 呼吸 / 挤压回弹 / 拖拽拎起动画
│   ├── popup.py         # 气泡卡片 + MVP 徽章 + 冠军登场特效
│   ├── heatmap.py       # 键盘热力图窗口
│   ├── table.py         # 历史表格（全部历史，倒序）
│   ├── app_stats.py     # 各软件分布（今天=横向条形 / 近 7 天=折线）
│   ├── schedule.py      # 日程表（独立窗口 + 头顶角标）
│   ├── vault_ui.py      # 琥珀（密码存储：搜索 + 模糊匹配 + 点击解密 + 自动清屏）
│   ├── translate_ui.py  # 翻译（热键快译 + 输入窗口 + 玄墨译文卡片）
│   └── app.py           # PetApp 主类：窗口 / 图标 / 拖拽 / 右键菜单
│
├── tests/               # pytest 回归用例（琥珀加解密/模糊匹配、天气解析与循环、应用统计、翻译方向/缓存/错误兜底、跨天滚动、归属对账、7 天聚合窗口）
├── conftest.py          # pytest 配置（让 tests/ 可被自动发现）
├── scripts/             # 开发辅助脚本（非程序一部分）
│   └── preview_weather_card.py  # 天气卡片离线预览生成
│
├── assets/              # 资源目录
│   ├── *.png             # 桌宠图标（优先带透明通道的 PNG，人物轮廓最佳）
│   └── *.jpg             # 无透明图时兜底（圆角显示）
│
├── keyboard_stats.db    # SQLite 数据库（运行时自动生成）
├── app_aliases.json     # exe 别名/分类表（首次运行生成，可手动增补）
├── app_stats.json       # 统计导出（运行时生成，供 AI 读取）
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
| **config.py** | 路径与资源发现 | `find_icon()` 优先扫描 `assets/` 里带透明通道的 PNG（回退任意图片）；无配置文件，换图只需替换 `assets/` 图片 |
| **db.py** | 数据存取 | `daily_stats` 按天聚合 + `daily_key_stats` 按键明细 + `daily_app_stats` 按应用明细（复合主键 `(date, app)`）；提供 `get_daily_mvp` 冠军键查询 |
| **db_todo.py** | 待办数据层 | `todo` 表（标题/截止/是否完成/完成时刻）；未完成轮换、勾掉留一天的查询逻辑 |
| **db_vault.py** | 琥珀数据层 | `vault_accounts` 表；**只存取密文**，不负责加解密；名称/密码必填，网址/备注选填 |
| **vault_crypto.py** | 琥珀加密 | Windows DPAPI（CryptProtectData）加密/解密；密钥由系统绑定当前账户，不落盘 |
| **vault_search.py** | 模糊匹配 | 归一化（大小写/分隔符）+ 多字段加权打分；纯函数、无副作用，便于测试 |
| **tracker.py** | 计数核心 | 线程安全 `Lock`；累计各键次数；跨天归档；重启恢复当天数据；时间源可注入 `now_fn`（便于测试跨天，生产默认读系统日期） |
| **listener.py** | 键盘监听 | `pynput.keyboard.Listener`；仅键盘（含修饰键），鼠标不计 |
| **scheduler.py** | 定时任务 | `midnight_loop` 等 24:00 跨天滚动；`periodic_save` 每 20s 落库并刷新 `app_stats.json` |
| **translate.py** | 翻译 | 百度翻译 API；`detect_direction` 自动判方向（含汉字→译英）；内存 LRU 缓存；错误码转人话；**永不抛异常** |
| **foreground.py** | 前台检测 | 纯 ctypes 调 Win32（GetForegroundWindow → PID → QueryFullProcessImageNameW），HWND→exe 缓存；不新增依赖 |
| **app_usage.py** | 按应用统计 | 内存计数 + 每秒采样前台窗口累计秒数；跨天归档；线程安全 |
| **app_aliases.py** | 别名表 | `app_aliases.json` 映射 exe → 友好名 + 分类（dev/terminal/browse/chat/work/media/other）；未命中兜底 other |
| **stats_export.py** | JSON 出口 | 生成结构固定的 `app_stats.json`（今天 + 近 7 天，含 count/seconds/占比），AI 可直接读 |
| **pet_ui/app.py** | 界面主类 | 透明漂浮窗（人物轮廓+阴影）、拖拽拎起、右键菜单、帧预生成 |
| **pet_ui/renderer.py** | 图像渲染 | `_prepare_pet` / `_make_shadow` / `_compose_frame` / `frame_to_photo` / 占位图 |
| **pet_ui/animations.py** | 动画 | 呼吸循环、点击挤压回弹、拖拽拎起状态机 |
| **pet_ui/popup.py** | 气泡 | 自适应圆角卡片、MVP 徽章、冠军登场特效、气泡跟随与关闭兜底 |
| **pet_ui/heatmap.py** | 热力图 | 26 键实时热度、环形扩散特效、HOT KEY 统计 |
| **pet_ui/table.py** | 历史表格 | `ttk.Treeview` 三列（日期/次数/MVP 键）、隔行变色；全部历史按日期倒序（最近的排最前） |
| **pet_ui/app_stats.py** | 各软件分布 | 顶层切换「今天 / 近 7 天」，两个视图都可切「次数 / 时长」；今天为横向条形（Top5、默认只显相对长度、点击展开当前指标的具体值）；近 7 天为折线（Top3）；Pillow 2x 超采样渲染（Canvas 手绘无抗锯齿会发毛） |
| **pet_ui/schedule.py** | 日程表 | 独立日程窗口（卡片+勾选+进度条，第三列完整汉字日期时间）；头顶角标（临近截止变红） |
| **pet_ui/vault_ui.py** | 琥珀界面 | 搜索窗口（**输入关键词才检索**、默认不铺条目名）、模糊匹配列表、双击/按钮解密显示、明文自动清屏、新增/编辑（密码留空即不改，密码框有小眼睛） |
| **pet_ui/translate_ui.py** | 翻译界面 | `Ctrl+Alt+T` 正则热键读剪贴板；后台线程请求 + 令牌防串号；玄墨译文卡片（跟随桌宠、Esc/✕ 关闭）；右键手打窗口（Enter 翻译 / Shift+Enter 换行） |
| **pet_ui/theme.py** | 常量 | 配色（含玄墨 `INK_*`，琥珀与翻译共用）、DPI 与动画参数集中管理 |

> 拆分后各模块通过 Mixin 混入 `PetApp`（`AnimationMixin` / `PopupMixin` / `HeatmapMixin` / `TableMixin` / `ScheduleMixin` / `VaultMixin` / `TranslateMixin`），
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

CREATE TABLE daily_app_stats (
    date    TEXT NOT NULL,      -- '2026-10-27'
    app     TEXT NOT NULL,      -- exe 名（如 'chrome.exe'）
    count   INTEGER NOT NULL,   -- 当天在该应用里敲键次数
    seconds INTEGER NOT NULL,   -- 当天该应用作为前台窗口的秒数
    PRIMARY KEY (date, app)
);
```

`daily_app_stats` 的复合主键 `(date, app)` 表示「某天某应用的一格统计」：
同一应用同一天只允许一行，天然防重复，不需要自增 id。
它的两个指标是正交的——`count` 是打字强度，`seconds` 是占用时长；
只看 count 会把「在浏览器看两小时网页」误判成低频使用。

时间范围一律**单表聚合**（不是联表）：

```sql
-- 近 7 天各应用总和
SELECT app, SUM(count), SUM(seconds) FROM daily_app_stats
WHERE date >= ? GROUP BY app ORDER BY SUM(count) DESC;
```

`daily_stats`（运行态计数器）与 `daily_app_stats`（历史明细）职责不同，
不是外键关系，查询各取所需，**不做 JOIN**。

- 每天 24:00：把当天总次数与各键次数写入上述两表 → 清空 → 开始新的一天
- `db.get_daily_mvp()`：查询全部历史记录（日期 | 次数 | MVP 键，按日期倒序）；MVP 键仅从 26 个英文字母中选出

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

### 琥珀（vault_accounts）

```sql
CREATE TABLE vault_accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,   -- 条目名（如 'GitHub'），**必填**，搜索主字段
    url          TEXT,            -- 网址，**选填**（域名参与搜索）
    password_enc TEXT NOT NULL,   -- 密码**密文**（DPAPI，见 vault_crypto），**必填**，绝不存明文
    username     TEXT,            -- 已弃用（保留列，前端不再录入）
    aliases      TEXT,            -- 已弃用（保留列）
    note         TEXT,            -- 备注，**选填**，低权重参与搜索
    created_at   TEXT DEFAULT (datetime('now','localtime')),
    updated_at   TEXT DEFAULT (datetime('now','localtime'))
);
```

字段口径（用户定稿）：**名称、密码必填；网址、备注选填**。
`username` / `aliases` 两列保留在表里（不影响旧数据、无需迁移），
但录入界面不再展示、不再写入，恒为空。

功能流程（用户定稿）：
```
录入(手动) → 加密落库 → 桌宠右键「琥珀」 → 搜索框 + 模糊匹配
→ 选中 → 解密显示 → 自动清屏
```

- **加密（vault_crypto.py）**：用 Windows **DPAPI**（`CryptProtectData`）
  加密后再写库，密钥由系统绑定当前登录账户，本程序不管理/不落盘任何密钥。
  含附加熵（限定本程序）。密文**只能在同一台机器、同一 Windows 账户**下解开；
  拷库到别的机器/账户无法解密。密码明文只在内存中短暂存在，用完即弃，
  **不写日志、不进异常消息**。
- **模糊匹配（vault_search.py）**：不是精确查询。先归一化（统一小写、
  去掉空格/连字符/下划线/点等），于是 `GitHub` / `github` / `git-hub` 视为同一形态；
  再对 名称 / 网址域名 / 备注 多字段加权打分，完全相等 > 前缀 > 子串，
  支持打半截、直接粘完整链接。（账号/别名两路仍保留在打分函数里，
  但因前端不再录入、恒为空，实际不参与。）
- **显示与清屏（pet_ui/vault_ui.py）**：窗口为**搜索驱动**——默认不铺任何
  条目名，**必须输入关键词才检索**，避免把全部账号清单晾在屏幕上。
  只有**选中并点击「显示密码」**（或双击行）时才解密；气泡内**同时展示
  名称 + 网址 + 备注 + 密码**；密码可一键复制、网址可一键打开；
  明文显示在只读框里，可点「✕」或按 `Esc` 手动关闭，
  倒计时（`REVEAL_SECONDS=12` 秒）后也会自动清空关闭。
  **气泡配色为「玄墨极简」专属体系**（`INK_*` 常量，墨灰底 + 左侧细线），
  与左键「今日战报」的锡金国潮刻意分开，互不影响。
- **编辑（更新已有条目）**：选中条目 → 点「编辑」→ 名称/网址回填、
  **密码框留空**（留空表示不修改原密码）；也可按 `Esc` 取消。
  保存走 `db_vault.update_account()`（密码传 `None` 保持原值）。
  避免「删了重录」这种既费事又容易删错的操作。

### 翻译（不落库）

```
复制文本 → Ctrl+Alt+T → translate.translate() → 玄墨译文卡片 → 关掉即散
右键「翻译」→ 输入框手打 → Enter → 同一张卡片
```

- **不落库、不写历史**：翻译内容只在内存里走一趟，卡片关掉就没了。
  退出程序后不留下任何查询痕迹（复制的内容会发给第三方，没必要持久化）。
- **方向判断**：含汉字 → 译成英文，否则 → 译成中文（中英混排按中文算）；
  最终以百度返回的 `from` 字段为准，不盲信本地判断。
- **内存缓存**：进程内 LRU（`CACHE_SIZE=256`），同一个词/句不重复请求，
  既省额度又让重复查询瞬回（卡片上会标「缓存」）。
- **密钥**：`.env` 里的 `BAIDU_APPID` / `BAIDU_KEY`，不进代码、不进仓库；
  没配置时只提示一句，不影响其它功能。

## 四、图标方案

- **默认**：`find_icon()` 自动扫描 `assets/` 目录，优先选带透明通道的 PNG（人物轮廓最适合做桌宠），找不到透明图时回退到任意第一张图片（png/jpg/jpeg/gif/bmp）
- **更换**：直接把图片放进/替换 `assets/` 目录，重启程序即可生效（无需改代码、无需改配置；多张图时按上述规则取一张）
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
| 右键 → 历史所有 | 弹出表格，展示全部历史记录（日期 | 次数 | MVP 键），按日期倒序（最近的排最前） |
| 右键 → 各软件分布 | 弹出分布窗口：顶部切「今天」（横向条形，Top5，点击条目展开次数+时长）/「近 7 天」（折线，Top3，可切「次数 / 时长」） |
| 右键 → 键盘热力图 | 弹出 26 键实时热度面板 |
| 右键 → 琥珀 | 打开琥珀搜索窗口（**输入名字才检索**，模糊匹配 + 点击解密显示；支持新增/编辑/删除） |
| 右键 → 翻译 | 打开翻译输入窗口（**中英互译，自动判方向**），Enter 翻译 / Shift+Enter 换行 |
| `Ctrl+Alt+T` | 复制任意文本后按下：**直译剪贴板**，译文卡片飘在桌宠头顶；剪贴板没文字则退化为打开输入窗口 |
| 右键 → 一键最小化 | 最小化所有可见窗口回到桌面（不关闭） |
| 右键 → 开机自启动 | 切换开关；勾选 = 开机自动常驻 |
| 右键 → 退出 | 退出程序（自动落库） |

> 历史查看统一使用 `ttk.Treeview` 表格呈现，带「日期」「次数」「MVP 键」三列表头及纵向/横向滚动条。

## 七、健壮性与设计细节

1. **异常兜底**：`main.py` 用全局 try/except 包围，任意异常写入 `pet.log` 而非无声退出；`pet_ui._load_icon` 图片加载失败时回退到 `_placeholder_icon()` 占位图并记日志。
2. **跨天前置检查**：`tracker.increment()` 在每次 +1 前先检查日期是否变化（`now != self._today`），若已跨天立即归档旧的一天再计数，避免依赖 `midnight_loop` 线程因休眠/挂起漏滚动。
3. **长按计数口径**：长按一键时 `pynput` 自动重复触发 `on_press`，每次均 +1，与单击效果一致（均计入）。
4. **落库容错**：`tracker.persist()`、跨天归档均用 try/except 包裹，写库失败只记日志，不拖垮程序。
5. **前台检测不新增依赖**：`foreground.py` 用 ctypes 直调 Win32（`GetForegroundWindow` → `GetWindowThreadProcessId` → `QueryFullProcessImageNameW`），并对 HWND→exe 做缓存。取不到就跳过本次统计，绝不影响键盘监听。
6. **时长采样防睡眠跳变**：`app_usage.tick()` 每帧最多累计 3 秒（`MAX_TICK_DELTA`），避免电脑休眠 8 小时后把整段时间全算到某个应用头上。
7. **统计 JSON 原子写入**：`stats_export.write_json()` 先写 `.tmp` 再 `os.replace`，AI 不会读到写了一半的文件。
8. **按键归属不丢**：每次按键都必须有归属——采样失败记入 `__unattributed__`（未识别），桌宠自己窗口（日程表/琥珀）里打的字记入 `__host__`（桌宠）。启动恢复时还会与 `daily_stats` 总数对一次账，把历史缺口也补进「未识别」。这样气泡的总次数与分布窗口的明细之和永远一致，不会出现 531 / 517 这种对不上的情况。
9. **翻译不阻塞界面**：请求在后台线程跑，结果用 `root.after(0, …)` 甩回主线程再碰控件（与天气线程同一套路）；带请求令牌，连按 `Ctrl+Alt+T` 只显示最后一次的结果，不会被慢请求反向覆盖。热键监听、翻译请求任意一步失败都只记日志，不影响计数与呼吸动画。
10. **时间源可注入**：`CountManager(now_fn=...)` 接收一个返回 `'YYYY-MM-DD'` 的函数（默认 `datetime.now()`），`db.get_daily_mvp(today=...)` 同理。跨天滚动、重启恢复、盲盒 MVP 这些依赖「今天是几号」的逻辑因此可以在测试里把日期直接拨到次日，不必等真实零点、也不会因为测试跑在 23:59 而偶发失败。`AppUsageTracker` / `weather_loop` 原本就有同类注入参数，口径一致。

## 八、UI 设计（已优化）

1. **DPI 感知**：`main.py` 在创建窗口前开启 `SetProcessDpiAwareness(2)`（per-monitor），解决高分屏下 `tkinter` 文字模糊成像素块的问题。
2. **时尚气泡**：左键点击、自启动提示改用 `_popup()`，绘制圆角卡片（`rounded_rectangle`）+ 水母粉描边 + 顶部色条 + 渐入渐淡动画。
3. **气泡跟随**：拖拽图标时，已显示的悬浮气泡通过 `_on_motion` 同步重定位，不再留在原地（`_active_popup` + `_popup_offset`）。
4. **历史表格美化**：`_show_table` 用粉色头部卡片 + `ttk.Style`（行高 32、隔行变色、清晰微软雅黑 UI 字体），并 try/except 兜底样式失败。
5. **菜单字体**：右键菜单用 `Microsoft YaHei UI` 和主色高亮，更清晰时尚。

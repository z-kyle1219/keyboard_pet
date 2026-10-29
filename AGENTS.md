# AGENTS.md

键盘计数桌宠（Windows）。常驻桌面的桌宠，记录每天敲击键盘次数 + 待办日程。Python 3.8+，uv 管理依赖，tkinter 渲染，pynput 全局监听，SQLite 存数据。

## 命令

- 装依赖：`uv sync`
- 运行：`uv run python main.py`（或 `python main.py` / 双击 `run.bat`）
- 测试：`uv run pytest`
- 快速语法检查：`uv run python -m py_compile <改动的文件>`

改完代码至少跑一遍 `uv run pytest` 再收尾。

## 架构与数据流

```
listener.py（pynput 全局键盘监听，仅键盘）
  → tracker.py（线程安全计数 + 按键明细 + 跨天滚动）
  → db.py（daily_stats 按天聚合 / daily_key_stats 按键明细）
  → db_todo.py（todo 待办表）
  → db_vault.py（vault_accounts 琥珀表，只存密文）
  ↳ vault_crypto.py（Windows DPAPI 加解密）+ vault_search.py（模糊匹配，纯函数）
scheduler.py（后台线程：24:00 跨天刷新 + 每 20s 落库）
translate.py（翻译：百度翻译 API，纯逻辑 + 内存缓存，不落库）
pet_ui/（界面包，各模块通过 Mixin 混入 PetApp）
main.py（入口，全局 try/except 兜底，退出前落库）
```

改 UI 时注意：`main.py` 用 `from pet_ui import PetApp`，不要破坏这个导入。

## 约定

- **计数口径**：仅键盘（含修饰键），鼠标不计。长按一键时 pynput 自动重复触发 `on_press`，每次 +1。
- **跨天**：`tracker.increment()` 每次 +1 前先检查日期，跨天立即归档再计数——不要依赖 `midnight_loop` 线程（它可能因休眠漏滚动）。
- **待办规则**：勾掉留一天（`done=1` 写入 `done_at`，当天显示次日隐藏）；未完成项自然顺延下一天；`due_at` 单字段既做排序又经 `format_due()` 转汉字展示。
- **落库容错**：`persist()` / 跨天归档都用 try/except 包住，写库失败只记日志，不拖垮程序。
- **琥珀（密码存储）口径**：密码**永不存明文**——`vault_crypto.encrypt()`（Windows DPAPI）加密后才写 `vault_accounts`；明文只在内存短暂存在，不写日志、不进异常消息。模糊匹配在 `vault_search.py`（归一化 + 加权打分），不要改成 SQL 精确查询。UI 为搜索驱动：**空词不铺列表**。
- **图标来源**：唯一真相是 `assets/`。`config.PET_ICON` 在导入时由 `find_icon()` 自动发现（优先带透明通道的 PNG）。换图只需替换 `assets/` 里的图片并重启，无配置文件、无运行时图标路径。
- **翻译口径**：中英互译走百度翻译 API，密钥在 `.env`（`BAIDU_APPID` / `BAIDU_KEY`），不进代码。**翻译内容不落库、不写历史、不写日志**——查完即散。请求必须放后台线程（`root.after(0, ...)` 回主线程），绝不能在 UI 线程阻塞。

## 坑（真踩过的，别重犯）

- **透明窗**：Windows tkinter 不支持逐像素 alpha，用 `transparentcolor` 抠色（品红 `#ff00ff`）。不要试图用 alpha 通道。
- **柔边阴影**：用多层同心椭圆模拟，不要用渐变/模糊（渲染不了）。
- **高分屏模糊**：窗口创建前必须先 `SetProcessDpiAwareness(2)`（per-monitor），否则文字糊成像素块。
- **图标**：优先带 alpha 通道的 PNG；无透明图时走「居中裁切 + 圆角遮罩 + 边缘羽化」兜底，避免矩形生硬。

## 红线（Never）

- **桌宠图标是用户本地人物照片（含隐私），永不入库。** `assets/*.{png,jpg,jpeg,gif,bmp}` 已 gitignore。仓库是 public，历史上出过误提交事故——每次 commit 前扫一眼 diff 确认没混进隐私文件。
- **不代用户 git commit。** 提交由用户自己完成，规范为英文 conventional commit。
- 涉及隐私 / 个人信息时先提醒、保守处理，再操作。

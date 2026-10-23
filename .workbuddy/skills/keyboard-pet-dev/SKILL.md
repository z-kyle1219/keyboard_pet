---
name: keyboard-pet-dev
description: This skill should be used when adding a feature, changing behavior, or fixing a bug in the keyboard_pet project (a Windows tkinter keyboard-counting desktop pet). Provides the module map, the step-by-step feature workflow, the verification loop, and privacy red lines.
agent_created: true
---

# keyboard_pet 开发 SOP

给 keyboard_pet 项目加功能 / 改行为 / 修 bug 时使用。

## 前置：先读约定

先读根目录 `AGENTS.md`（命令、架构、坑、红线）。本 skill 只讲流程，事实以 `AGENTS.md` 为准，不重复复制。

## 流程（按顺序执行）

1. **定位层级**：判断改动属于哪一层
   - 数据 → `db.py`（按键统计）或 `db_todo.py`（待办）
   - 计数/监听 → `tracker.py` / `listener.py`
   - 定时 → `scheduler.py`
   - 界面 → `pet_ui/` 下对应 Mixin（`app.py` / `renderer.py` / `animations.py` / `popup.py` / `heatmap.py` / `table.py` / `schedule.py` / `theme.py`）
   - 跨层 → 按数据流顺序 `listener → tracker → db → (scheduler) → pet_ui`

2. **需要存数据** → 先在 db 层加表 / 查询，再往上走。

3. **需要界面** → 在 `pet_ui/` 新建或改对应 Mixin，混入 `PetApp`（参照现有 Mixin 的混入方式）；保持 `main.py` 的 `from pet_ui import PetApp` 导入不变。

4. **注册入口** → 右键菜单 / 事件在 `pet_ui/app.py` 注册。

5. **验证闭环**（每次改动后必做）
   - `uv run pytest`
   - `uv run python -m py_compile <改动的文件>`
   - 纯逻辑模块留了 `__main__` 自测，可 `uv run python weather.py` 之类单独验证。

6. **隐私检查**：不碰 `assets/` 本地照片；不把照片路径写进任何代码或配置。

7. **收尾**：不代用户 git commit（用户自己提交，英文 conventional commit）。

## 关键坑（细节见 AGENTS.md，这里只列提醒）

- tkinter 透明窗抠色 `#ff00ff` / 多层椭圆阴影 / DPI awareness
- 跨天滚动别依赖 `midnight_loop`（`tracker.increment()` 里要先查日期）
- 落库用 try/except 兜底，失败只记日志不拖垮程序

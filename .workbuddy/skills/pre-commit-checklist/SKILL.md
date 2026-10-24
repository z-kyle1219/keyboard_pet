---
name: pre-commit-checklist
description: This skill should be used whenever finishing a change in the keyboard_pet project and getting ready to deliver it — "准备提交"、"收尾"、"提交前检查"、"这个功能做完了"、"帮我看看能不能 commit"、"结构文档更新了吗"，or any moment the user is about to run git commit / git push. It drives the pre-delivery checklist: refresh PROJECT_STRUCTURE.md, run the verification loop (_compile_check.py + pytest), scan the diff for privacy files, and write a conventional-commit message. Use it proactively before ANY commit in this repo, even if the user only says "做完了".
agent_created: true
---

# keyboard_pet 提交前检查（Pre-commit Checklist）

在 keyboard_pet 项目里，**每次收尾/准备提交前**走一遍。目标：让每次交付都「可验证、无隐私泄漏、文档同步、提交信息规范」。

> 事实与红线以根目录 `AGENTS.md` 为准，本 skill 只讲**交付流程**，不复制事实。

## 为什么需要这一步

这个仓库是 **public**，且历史上出过一次真实事故（人物照片误提交并 push）。所以「提交前扫 diff」不是形式主义，是防止隐私再次泄漏的最后一道闸。

## 流程（按顺序）

1. **语法 + 导入链自检**
   ```
   uv run python _compile_check.py
   ```
   它编译所有源码并检查 `from pet_ui import PetApp` 及 Mixin 方法是否解析成功。看到 `FAIL` / `IMPORT-ERR` 必须先修，别继续。

2. **跑测试**
   ```
   uv run pytest
   ```
   改完代码不通过测试就不算做完。重点看 `tests/` 里的回归用例（如 `test_weather_parse` 的「只取明天」）。

3. **结构文档同步**（关键，容易漏）
   - 若本次**新增/删除/重命名了模块**，或**改了数据表结构**，必须更新 `PROJECT_STRUCTURE.md`（目录树、模块职责表、数据模型）。
   - 纯逻辑改动不用动它。判断标准：**`PROJECT_STRUCTURE.md` 里有没有一句话因为这次改动而变得不准确？** 有就改。

4. **扫 diff，确认没有隐私文件**（红线）
   ```
   git status
   git diff --cached --stat
   ```
   - 确认没有 `assets/*.png|jpg|jpeg|gif|bmp`、没有本地照片路径、没有一次性工具（`_cutout.py` 等）混进来。
   - 一旦发现隐私文件被 staged，**立即停下并提醒用户**，不要自行 commit。

5. **写提交信息**（英文 conventional commit）
   - 格式：`<type>(<scope>): <subject>`
   - 常用 type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore`
   - 示例：
     - `feat(weather): 新增降雨时段确定提醒`
     - `fix(schedule): 修复确认按钮仍弹窗`
     - `refactor(ui): 拆分 pet_ui 为 Mixin 包`
   - 一次提交只做一件事；正文（可选）说清「为什么」。

6. **不代用户提交**（红线）
   - 流程走到这里就停。**给出建议的 commit message 和命令，由用户自己执行 `git commit`。**
   - 不要运行 `git commit` / `git push`，除非用户明确逐字要求。

## 与 hook 的关系

以上是**给 AI 的思路**（软约束，靠触发）。若用户想要「一定跑得掉」的硬约束，可另配 `.git/hooks/pre-commit`（Git 强制、失败拦提交）——但那是独立的一层，本 skill 只负责流程判断与隐私把关。

## 快速自检清单（可复制）

- [ ] `_compile_check.py` 全 OK
- [ ] `pytest` 通过
- [ ] 模块/表结构变了 → `PROJECT_STRUCTURE.md` 已同步
- [ ] `git diff --cached` 无隐私文件、无本地照片路径
- [ ] commit message 是英文 conventional commit
- [ ] 没代用户 commit

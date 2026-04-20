# CLI 命令规范

## 工具名称

```bash
task-agent
```

安装后全局可用（通过 `uv tool install` 或 `pip install -e .`）。

---

## 命令总览

```
task-agent
├── run        全流程：architect → dev → review
├── architect  仅执行需求梳理阶段
├── dev        仅执行开发阶段（需要已有 contract.md）
├── review     仅执行代码审查阶段（需要已有代码）
├── resume     从上次中断处继续
├── status     查看当前任务状态
├── list       列出所有历史任务
├── hint       获取 AI 修复建议（不修改文件）
├── pause      暂停当前任务
└── abort      放弃当前任务
```

---

## 命令详细规范

### `task-agent run`

```
task-agent run [DESCRIPTION] [OPTIONS]

描述：
  启动完整工作流（architect → dev → review）。
  如果不提供 DESCRIPTION，进入交互式输入模式。

参数：
  DESCRIPTION   任务描述（可省略，支持中文）

选项：
  --model TEXT          使用的 Claude 模型 [默认: claude-opus-4-6]
  --max-dev-retry INT   Developer 最大重试次数 [默认: 5]
  --lang TEXT           目标语言 python|javascript [默认: python]
  --skip-review         跳过 Review 阶段（不推荐）
  --task-dir PATH       指定任务目录（默认自动生成）

示例：
  task-agent run "帮我做一个用户同步接口"
  task-agent run --lang python --max-dev-retry 3
  task-agent run  # 进入交互模式
```

### `task-agent architect`

```
task-agent architect [OPTIONS]

描述：
  仅执行需求梳理阶段，生成契约文档后停止。
  适用于：需求不清晰，想先讨论清楚再开发。

选项：
  --task-id TEXT    指定已有任务（继续追问）
  --output PATH     契约文档输出路径 [默认: tasks/{id}/contract.md]

示例：
  task-agent architect
  task-agent architect --task-id 2026-04-20_用户同步接口
```

### `task-agent dev`

```
task-agent dev [OPTIONS]

描述：
  仅执行开发阶段（TDD）。需要当前任务目录下已有 contract.md。

  执行顺序：RED → GREEN（迭代）→ REFACTOR

选项：
  --task-id TEXT        指定任务目录（默认使用最近的任务）
  --max-retry INT       最大重试次数 [默认: 5]
  --phase TEXT          指定从哪个阶段开始 red|green|refactor [默认: red]

示例：
  task-agent dev
  task-agent dev --task-id 2026-04-20_用户同步接口
  task-agent dev --phase green  # 跳过写测试，直接写代码（已有测试时使用）
```

### `task-agent review`

```
task-agent review [OPTIONS]

描述：
  仅执行代码审查阶段。需要当前任务目录下已有 contract.md 和 src/ 目录。

选项：
  --task-id TEXT    指定任务目录（默认使用最近的任务）
  --output PATH     审查报告输出路径 [默认: tasks/{id}/review.md]

示例：
  task-agent review
  task-agent review --task-id 2026-04-20_用户同步接口
```

### `task-agent resume`

```
task-agent resume [OPTIONS]

描述：
  从上次中断处继续。自动读取最近任务的 state.json，
  从当前状态对应的阶段继续执行。

选项：
  --task-id TEXT    指定要恢复的任务（默认使用最近的未完成任务）

恢复行为：
  ARCHITECT         恢复 Architect 对话（加载历史记录）
  DEV_RED           重新生成测试
  DEV_GREEN         读取最后一次失败的测试结果，继续修复
  DEV_REFACTOR      继续重构
  REVIEW_FAILED     提示人工修复，等待确认后重新审查
  PAUSED            显示失败信息，提示操作选项

示例：
  task-agent resume
  task-agent resume --task-id 2026-04-20_用户同步接口
```

### `task-agent status`

```
task-agent status [OPTIONS]

描述：
  查看当前（或指定）任务的状态。

选项：
  --task-id TEXT    指定任务（默认使用最近的任务）
  --json            以 JSON 格式输出

输出示例：
  ┌─────────────────────────────────────────────────┐
  │  任务：用户同步接口                              │
  │  ID：2026-04-20_用户同步接口                    │
  │  状态：DEV_GREEN（开发中 - GREEN phase）         │
  │  开始时间：2026-04-20 10:00:00                  │
  │  当前重试：1/5                                   │
  │                                                  │
  │  阶段进度：                                      │
  │  ✅ ARCHITECT  完成（10:00 - 10:15，5 轮对话）  │
  │  🔄 DEV        进行中                            │
  │     ✅ RED     完成（8个测试全红）               │
  │     🔄 GREEN   进行中（第1次修复）               │
  │     ⬜ REFACTOR 待开始                          │
  │  ⬜ REVIEW     待开始                            │
  └─────────────────────────────────────────────────┘

示例：
  task-agent status
  task-agent status --json
```

### `task-agent list`

```
task-agent list [OPTIONS]

描述：
  列出所有历史任务。

选项：
  --limit INT       显示最近 N 个任务 [默认: 10]
  --state TEXT      按状态筛选 done|paused|active|all [默认: all]

输出示例：
  ID                              状态    创建时间          描述
  ─────────────────────────────────────────────────────────────
  2026-04-20_用户同步接口         🔄      2026-04-20 10:00  帮我做一个用户同步接口
  2026-04-19_订单状态机重构       ✅      2026-04-19 14:30  重构订单状态机
  2026-04-18_支付回调接口         ❌      2026-04-18 09:00  (暂停：超过重试上限)

示例：
  task-agent list
  task-agent list --state done
  task-agent list --limit 5
```

### `task-agent hint`

```
task-agent hint [OPTIONS]

描述：
  获取 AI 对当前失败测试的修复建议。
  不修改任何文件，只输出建议（你自己决定是否采纳）。

选项：
  --task-id TEXT    指定任务（默认使用最近的任务）

输出示例：
  AI 修复建议（不会自动修改文件）：

  针对失败测试：test_下游超时_返回降级响应

  分析：当前代码在 service.py:45 调用 requests.get() 没有设置
  timeout，导致测试中的 mock Timeout 异常没有被触发。

  建议修改：
  ─ service.py:45
    response = requests.get(url)
  + response = requests.get(url, timeout=settings.HTTP_TIMEOUT)

  另外，src/service.py 缺少 fallback 处理...

示例：
  task-agent hint
```

### `task-agent pause / abort`

```
task-agent pause
  描述：暂停当前任务（状态置为 PAUSED），允许开始新任务。

task-agent abort [--task-id TEXT]
  描述：放弃当前任务。任务目录保留（不删除），状态置为 ERROR。
  会要求确认：
    "确认放弃任务 2026-04-20_用户同步接口？[y/N]"
```

---

## 终端输出风格

使用 `rich` 库，输出清晰、可读：

```
[10:00:05] 🚀 启动任务：用户同步接口
[10:00:05] 📁 任务目录：tasks/2026-04-20_用户同步接口/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1: Architect Agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Architect > 你说"同步用户数据"，我需要明确几点：
           1. 数据从哪个系统来？用户中心、CRM 还是第三方？
           2. 同步到哪里？MySQL 还是其他？

你 > [输入]

...

[10:15:33] ✅ 契约文档已生成：tasks/2026-04-20_用户同步接口/contract.md
[10:15:33] 请确认契约内容后按 Enter 继续...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2: Developer Agent（TDD）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:15:45] 📝 [RED] 生成测试用例...
[10:16:02] 🧪 执行测试（确认全红）...

  FAILED tests/test_user_sync.py::test_正常请求_返回200
  FAILED tests/test_user_sync.py::test_下游超时_返回降级响应
  FAILED tests/test_user_sync.py::test_重复请求_幂等性保证
  ...
  8 failed in 0.23s

[10:16:03] ✅ 全部 8 个测试为红色，符合 TDD 要求
[10:16:03] 💻 [GREEN] 生成业务代码（第 1 次尝试）...
[10:16:45] 🧪 执行测试...

  PASSED tests/test_user_sync.py::test_正常请求_返回200
  FAILED tests/test_user_sync.py::test_下游超时_返回降级响应
  ...
  6 passed, 2 failed in 0.31s

[10:16:46] ⚠️  2 个测试失败，尝试修复（1/5）...
[10:17:20] 🧪 执行测试...

  8 passed in 0.29s

[10:17:21] ✅ 全部测试通过！
[10:17:21] 🔨 [REFACTOR] 重构代码...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 3: Reviewer Agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:18:00] 🔍 开始代码审查...
[10:18:35] ✅ 审查完成：通过

  📄 审查报告：tasks/2026-04-20_用户同步接口/review.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 任务完成！用时 18 分 35 秒

产物：
  📋 契约文档  tasks/2026-04-20_用户同步接口/contract.md
  💻 业务代码  tasks/2026-04-20_用户同步接口/src/
  🧪 测试代码  tasks/2026-04-20_用户同步接口/tests/
  📊 审查报告  tasks/2026-04-20_用户同步接口/review.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 环境变量（.env）

```bash
# 必填
ANTHROPIC_API_KEY=sk-ant-...

# 可选（有默认值）
TASK_AGENT_MODEL=claude-opus-4-6
TASK_AGENT_MAX_DEV_RETRY=5
TASK_AGENT_TASKS_DIR=./tasks
TASK_AGENT_LOG_LEVEL=INFO
```

# Pipeline 状态机详细设计

## 状态定义

```python
class TaskState(str, Enum):
    INIT            = "INIT"             # 任务目录已创建，尚未开始
    ARCHITECT       = "ARCHITECT"        # Architect Agent 交互中
    ARCHITECT_DONE  = "ARCHITECT_DONE"   # 契约已确认，等待进入开发
    DEV_RED         = "DEV_RED"          # 正在生成测试（RED phase）
    DEV_RED_DONE    = "DEV_RED_DONE"     # 测试已生成且全部为红
    DEV_GREEN       = "DEV_GREEN"        # 正在生成业务代码（GREEN phase）
    DEV_GREEN_DONE  = "DEV_GREEN_DONE"   # 测试全部通过
    DEV_REFACTOR    = "DEV_REFACTOR"     # 重构中
    DEV_DONE        = "DEV_DONE"         # 开发完成（测试全绿）
    REVIEW          = "REVIEW"           # Reviewer Agent 审查中
    REVIEW_FAILED   = "REVIEW_FAILED"    # 审查不通过（有 P0）
    DONE            = "DONE"             # 全流程完成
    PAUSED          = "PAUSED"           # 等待人工介入（超过重试上限）
    ERROR           = "ERROR"            # 系统错误
```

## 状态转换图

```
INIT
  │ run() / architect()
  ▼
ARCHITECT ──────────────────────────────────────────┐
  │ 用户确认契约                                      │ 用户中断
  ▼                                                  │
ARCHITECT_DONE                                      PAUSED
  │ auto / dev()                                     │ resume()
  ▼                                                  │
DEV_RED ◄───────────────────────────────────────────┘
  │ pytest 确认全红
  ▼
DEV_RED_DONE
  │ auto
  ▼
DEV_GREEN
  │ pytest 全通过
  ├─ 失败（retry < MAX_DEV_RETRY）→ 重新进入 DEV_GREEN
  └─ 失败（retry >= MAX_DEV_RETRY）→ PAUSED
  │ 通过
  ▼
DEV_GREEN_DONE
  │ auto
  ▼
DEV_REFACTOR
  │ pytest 确认仍然全绿
  ▼
DEV_DONE
  │ auto / review()
  ▼
REVIEW
  │ 审查结果
  ├─ 有 P0 → REVIEW_FAILED → 人工介入 → DEV_GREEN（修复后）
  └─ 无 P0 → DONE

DONE  ✅
```

## state.json 格式

每个任务目录下的 `state.json` 记录完整状态：

```json
{
  "task_id": "2026-04-20_用户同步接口",
  "task_description": "帮我做一个用户同步接口",
  "state": "DEV_GREEN",
  "created_at": "2026-04-20T10:00:00+08:00",
  "updated_at": "2026-04-20T10:35:22+08:00",
  "phases": {
    "architect": {
      "started_at": "2026-04-20T10:00:00+08:00",
      "completed_at": "2026-04-20T10:15:00+08:00",
      "conversation_turns": 5,
      "contract_path": "contract.md",
      "user_confirmed": true
    },
    "dev": {
      "started_at": "2026-04-20T10:15:00+08:00",
      "current_phase": "GREEN",
      "retry_count": 1,
      "max_retries": 5,
      "test_results": [
        {
          "timestamp": "2026-04-20T10:20:00+08:00",
          "phase": "RED",
          "passed": 0,
          "failed": 8,
          "errors": 0,
          "output_path": "test_results/run_001.txt"
        },
        {
          "timestamp": "2026-04-20T10:30:00+08:00",
          "phase": "GREEN_attempt_1",
          "passed": 6,
          "failed": 2,
          "errors": 0,
          "output_path": "test_results/run_002.txt"
        }
      ]
    },
    "review": null
  },
  "paused_reason": null,
  "error": null
}
```

## 断点续跑机制

```bash
$ task-agent resume
```

执行流程：
1. 查找 `tasks/` 目录下最近修改的 `state.json`（或指定 `--task-id`）
2. 读取当前 `state`
3. 根据 state 决定从哪里恢复：

```python
RESUME_MAP = {
    TaskState.ARCHITECT:      resume_architect,   # 恢复对话（历史保存在 architect_history.json）
    TaskState.ARCHITECT_DONE: start_dev,
    TaskState.DEV_RED:        resume_dev_red,
    TaskState.DEV_RED_DONE:   start_dev_green,
    TaskState.DEV_GREEN:      resume_dev_green,   # 从最后一次失败的测试结果继续
    TaskState.DEV_GREEN_DONE: start_refactor,
    TaskState.DEV_REFACTOR:   resume_refactor,
    TaskState.DEV_DONE:       start_review,
    TaskState.REVIEW_FAILED:  prompt_manual_fix,
    TaskState.PAUSED:         prompt_manual_fix,
}
```

## PAUSED 状态处理

当 Developer Agent 连续 5 次修复失败时，进入 PAUSED：

```
⚠️  Developer Agent 已连续 5 次修复失败，进入暂停模式。

失败的测试：
  FAILED tests/test_user_sync.py::test_下游超时_返回降级响应
  FAILED tests/test_user_sync.py::test_并发请求_不产生重复数据

任务目录：tasks/2026-04-20_用户同步接口/

你可以：
  1. 手动修改 src/ 下的代码，然后运行 task-agent resume
  2. 运行 task-agent hint 获取 AI 的修复建议（不自动修改文件）
  3. 运行 task-agent abort 放弃本次任务
```

## 并发保护

同一时间只允许一个任务处于活跃状态（非 DONE/PAUSED）：

```bash
$ task-agent run "新任务"
# 如果有任务处于 ARCHITECT/DEV_*/REVIEW 状态

⚠️  检测到有任务正在进行中：2026-04-20_用户同步接口 (状态: DEV_GREEN)
请先完成或暂停当前任务：
  task-agent status          # 查看当前任务状态
  task-agent resume          # 继续当前任务
  task-agent pause           # 暂停当前任务，开始新任务
```

## 关键时序：Developer 迭代循环详解

```
workflow.run_dev_phase()
  │
  ├─ 1. call Developer Agent（写测试指令）
  │       ↓ 返回测试代码
  ├─ 2. 写入 tests/test_{feature}.py
  │
  ├─ 3. Runner.run_pytest() → 检查是否全红
  │       ├─ 有通过的测试 → 警告，要求 Developer 加强断言
  │       └─ 全红 → 继续
  │
  ├─ 4. call Developer Agent（写代码指令 + 测试代码内容）
  │       ↓ 返回业务代码
  ├─ 5. 写入 src/{module}.py
  │
  ├─ 6. Runner.run_pytest() → 检查结果
  │       ├─ 全绿 → 进入 REFACTOR
  │       └─ 有失败 →
  │             retry_count += 1
  │             如果 retry_count >= MAX_DEV_RETRY → PAUSED
  │             否则 → 回到步骤 4
  │                    传入：失败的测试输出 + 当前代码 + 失败次数
  │
  └─ 7. call Developer Agent（重构指令）
          ↓ 返回重构后代码
         写入文件 → Runner.run_pytest() 确认全绿 → DEV_DONE
```

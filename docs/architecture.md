# 系统架构设计

## 设计目标

| 目标 | 说明 |
|------|------|
| 最小人工干预 | 除 Architect 阶段的追问外，其余全自动 |
| 可断点续跑 | 任何阶段中断后，`task-agent resume` 从上次状态恢复 |
| 真实执行 | 代码真实写入磁盘，测试真实执行，不是"模拟" |
| 可审计 | 每次任务完整记录在 `tasks/` 目录，产物永久留存 |
| 单一职责 | 每个 Agent 只做一件事，靠契约文档传递上下文 |

---

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    CLI (task-agent)                      │
│                     typer + rich                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  Workflow Engine                          │
│              (workflow.py + state.py)                    │
│                                                          │
│   状态机：INIT → ARCHITECT → DEV → REVIEW → DONE        │
└────┬──────────────┬──────────────┬───────────────────────┘
     │              │              │
┌────▼────┐   ┌─────▼─────┐  ┌───▼──────┐
│Architect│   │ Developer  │  │ Reviewer │
│  Agent  │   │   Agent    │  │  Agent   │
│         │   │            │  │          │
│交互追问  │   │唯一编码Agent│  │对照契约  │
│生成契约  │   │测试+业务代码│  │黑白盒审  │
│         │   │配置+依赖声明│  │          │
└────┬────┘   └─────┬──────┘  └───┬──────┘
     │              │              │
     │         ┌────▼────┐        │
     │         │ Runner  │        │
     │         │(pytest) │        │
     │         └─────────┘        │
     │                            │
┌────▼────────────────────────────▼──────┐
│           Task Directory                │
│   tasks/2026-04-20_用户同步接口/        │
│   ├── contract.md                       │
│   ├── src/                              │
│   ├── tests/                            │
│   ├── review.md                         │
│   └── state.json                        │
└────────────────────────────────────────┘
```

---

## Agent 通信模型

三个 Agent **不直接互相调用**，通过**文件系统 + Workflow Engine** 传递上下文：

```
Architect Agent
    → 写入 contract.md
    → Workflow Engine 读取 contract.md
    → 传给 Developer Agent 作为系统 Prompt 上下文

Developer Agent
    → 写入 src/ 和 tests/
    → Runner 执行 pytest，输出写入 test_results.txt
    → 如果失败，Workflow Engine 把失败信息 + 当前代码传回 Developer Agent
    → 循环，最多 MAX_RETRY 次

Reviewer Agent
    → 读取 contract.md + src/ 下所有文件
    → 写入 review.md
```

**为什么不用流式 Agent 通信？**
- 文件系统作为中间层更可靠，支持断点续跑
- 每个 Agent 的输入输出清晰可审计
- 避免长对话上下文污染（每个 Agent 有干净的 context）

---

## Claude API 调用方式

每个 Agent 是一个**独立的对话线程**，使用 `Messages API`：

```python
# 客户端初始化（BaseAgent.__init__）
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key,
    base_url=settings.anthropic_base_url or None,  # 支持中转站，None = 官方
)

# 每个 Agent 的调用模式
client.messages.create(
    model="claude-opus-4-6",          # 使用最强模型保证质量
    max_tokens=8096,
    system=AGENT_SYSTEM_PROMPT,       # Agent 角色定义（来自 agents/ 目录）
    messages=conversation_history,    # 支持多轮对话（Architect 阶段）
)
```

### 模型接入配置

通过 `.env` 控制，无需改代码：

| 场景 | 配置 |
|------|------|
| 直连官方 API | 只填 `ANTHROPIC_API_KEY`，不填 `ANTHROPIC_BASE_URL` |
| 第三方中转站 | 同时填 `ANTHROPIC_API_KEY`（中转站的 key）和 `ANTHROPIC_BASE_URL` |

**中转站要求**：必须兼容 Anthropic Messages API 格式（`POST /v1/messages`）。
不兼容 OpenAI 格式，中转站若只转发 OpenAI 协议，需在中转站侧做协议适配。

**Architect Agent**：多轮对话，用户实时参与，history 保存在内存中。

**Developer Agent**：每次迭代是新的 Messages 调用，但把完整上下文（契约 + 当前代码 + 测试失败信息）打包进 user message。

**Reviewer Agent**：单轮调用，把所有文件内容打包进 user message。

---

## 状态机设计

```
INIT
  │ task-agent run / task-agent architect
  ▼
ARCHITECT
  │ 三要素收集完毕，用户确认契约
  ▼
DEV_WRITE_TESTS     ← 写测试（RED phase）
  │ pytest 跑测试，确认全部失败
  ▼
DEV_WRITE_CODE      ← 写业务代码（GREEN phase）
  │ pytest 跑测试
  ├─ 失败 → 重试（最多 MAX_DEV_RETRY=5 次）→ 超限则暂停等待人工介入
  └─ 通过
  ▼
DEV_REFACTOR        ← 重构（REFACTOR phase）
  │ pytest 确认仍然全绿
  ▼
REVIEW              ← 代码审查
  │ 审查通过（无 P0）
  ▼
DONE

任意阶段可 → PAUSED（等待人工介入）
PAUSED → 对应阶段（task-agent resume）
```

状态持久化在 `tasks/<task_dir>/state.json`，格式见 [workflow.md](workflow.md)。

---

## 任务目录命名规范

```
tasks/{date}_{slug}/

date: YYYY-MM-DD
slug: 从任务描述自动生成，取前 20 个字符，特殊字符替换为 _

示例:
  tasks/2026-04-20_用户同步接口/
  tasks/2026-04-20_订单状态机重构/
```

---

## 关键设计决策

### 决策 1：为什么选择文件系统而非内存传递

**背景**：Agent 之间的上下文（契约、代码、测试结果）需要传递。

**选择**：写入磁盘文件，下一个 Agent 读取。

**理由**：
- 支持断点续跑，进程崩溃不丢失状态
- 人工可介入（直接编辑 contract.md 修正需求）
- 可审计，每次任务留存完整产物

### 决策 2：为什么每个 Agent 用独立对话而非单一长对话

**背景**：可以把所有 Agent 放在一个长对话里。

**选择**：独立 Messages 调用，每次传入完整上下文。

**理由**：
- 避免长对话中早期内容被"忘记"（attention 稀释）
- 每个 Agent 有干净的角色设定，不被前序对话污染
- 更容易控制 token 消耗

### 决策 3：为什么 Developer Agent 是"唯一编码 Agent"

**背景**：可以把测试生成、业务代码生成、配置生成分给不同 Agent。

**选择**：所有代码产出（测试 + 业务 + 配置 + 依赖）都由 Developer Agent 完成。

**理由**：
- 代码各部分紧密耦合：测试的 mock 方式决定了业务代码的接口设计，配置项影响测试 fixture，不同 Agent 分工会造成大量上下文重复传递
- Developer Agent 在 GREEN 阶段必须同时看到测试代码 + 业务代码才能正确修复，人为拆分只会增加复杂度
- 职责清晰：Architect 决定"做什么"，Developer 决定"怎么做"，Reviewer 判断"做得够不够好"

### 决策 4：为什么 Developer Agent 真实执行测试

**背景**：可以让 AI "假装"测试通过。

**选择**：subprocess 执行 pytest，把真实 stdout/stderr 反馈给 Agent。

**理由**：
- 这是整个工作流的核心价值所在
- 虚假的测试通过 = 没有安全网
- 失败信息是 Agent 自我修正的唯一可靠依据

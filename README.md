# AI Workflow — 领导任务交付流水线

一个基于 Claude API 的多 Agent CLI 工具，把"收到模糊任务"到"提交可测试代码"的全过程自动化。

你只需要做两件事：**回答追问** 和 **看最终报告**。

---

## 工作流概览

```
$ task-agent run "帮我做一个用户同步接口"

[Phase 1] Architect Agent  →  交互追问  →  contract.md
[Phase 2] Developer Agent  →  RED/GREEN/REFACTOR  →  代码 + 测试通过
[Phase 3] Reviewer Agent   →  黑白盒审查  →  review.md

✅ 审查通过，可以提交代码
```

每次任务在 `tasks/` 目录下创建独立工作目录，完整记录过程产物。

---

## 快速开始

```bash
# 安装
git clone <repo>
cd AI-workflow
cp .env.example .env        # 填入 ANTHROPIC_API_KEY
uv sync

# 全流程（推荐）
task-agent run "你的任务描述"

# 分阶段调用
task-agent architect         # 仅需求梳理，输出契约文档
task-agent dev               # 仅开发+测试循环
task-agent review            # 仅代码审查
task-agent resume            # 从上次中断处继续
task-agent status            # 查看当前任务状态
```

---

## 项目结构

```
AI-workflow/
├── src/task_agent/
│   ├── agents/
│   │   ├── architect.py    # Agent 1：需求梳理 + 契约生成
│   │   ├── developer.py    # Agent 2：全能编码（测试+业务代码+配置+依赖）
│   │   └── reviewer.py     # Agent 3：契约式代码审查
│   ├── runner.py           # 测试执行器（subprocess + pytest）
│   ├── workflow.py         # Pipeline 编排 & 状态机
│   ├── state.py            # 任务状态持久化
│   └── cli.py              # CLI 入口（typer）
├── tasks/                  # 每次任务的独立工作目录（自动创建）
│   └── 2026-04-20_用户同步接口/
│       ├── contract.md     # 开发契约文档
│       ├── src/            # 生成的业务代码
│       ├── tests/          # 生成的测试代码
│       ├── review.md       # 审查报告
│       └── state.json      # 任务状态（支持断点续跑）
├── docs/                   # 设计文档
├── .env.example
├── pyproject.toml
└── README.md
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构 & Agent 设计 |
| [docs/agents.md](docs/agents.md) | 三个 Agent 的 Prompt & 行为规范 |
| [docs/workflow.md](docs/workflow.md) | Pipeline 状态机详细设计 |
| [docs/cli-spec.md](docs/cli-spec.md) | CLI 命令完整规范 |
| [docs/contract-spec.md](docs/contract-spec.md) | 《开发契约文档》格式规范 |
| [docs/dev-guide.md](docs/dev-guide.md) | 开发 & 贡献指南 |

---

## 核心约束（写死，不可绕过）

- **Architect Agent**：三要素（数据流 + 接口 I/O + ≥3 异常场景）未收集完 → 不生成任何代码
- **Developer Agent**：测试必须先跑红，不允许通过修改断言让测试通过
- **Reviewer Agent**：超时/重试/降级/日志 四件套任何一项缺失 → P0 否决，不允许"后续补充"

---

## 环境要求

- Python 3.12+
- uv（包管理）
- pytest（测试执行）
- Anthropic API Key

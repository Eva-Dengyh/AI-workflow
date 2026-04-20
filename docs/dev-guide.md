# 开发指南

## 环境搭建

### 前置要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（包管理工具）
- Anthropic API Key

### 安装步骤

```bash
# 1. 克隆项目
git clone <repo>
cd AI-workflow

# 2. 安装依赖
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY

# 4. 验证安装
task-agent --version
task-agent --help
```

---

## 项目结构详解

```
AI-workflow/
│
├── src/task_agent/              # 主包
│   ├── __init__.py
│   ├── cli.py                   # CLI 入口（typer）
│   │                            #   定义所有命令：run, architect, dev, review, ...
│   │
│   ├── workflow.py              # Pipeline 编排 & 状态机
│   │                            #   WorkflowEngine: 驱动整个流程
│   │                            #   state 转换逻辑
│   │
│   ├── state.py                 # 任务状态持久化
│   │                            #   TaskState 枚举
│   │                            #   TaskContext dataclass
│   │                            #   load_state() / save_state()
│   │
│   ├── runner.py                # 测试执行器
│   │                            #   TestRunner: subprocess 调用 pytest
│   │                            #   parse_pytest_output() → TestResult
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseAgent: Claude API 调用封装
│   │   ├── architect.py         # ArchitectAgent: 交互式需求梳理
│   │   ├── developer.py         # DeveloperAgent: TDD 代码生成
│   │   └── reviewer.py          # ReviewerAgent: 契约式代码审查
│   │
│   ├── prompts/                 # 系统 Prompt 文本文件
│   │   ├── architect.txt
│   │   ├── developer.txt
│   │   └── reviewer.txt
│   │
│   └── utils/
│       ├── __init__.py
│       ├── file_writer.py       # 安全写入文件（带备份）
│       ├── contract_validator.py # 校验 contract.md 格式
│       └── task_dir.py          # 任务目录命名 & 创建
│
├── tasks/                       # 任务工作目录（自动创建，不提交到 git）
│
├── tests/                       # 项目自身的测试（测试 task-agent 工具本身）
│   ├── test_runner.py
│   ├── test_state.py
│   ├── test_contract_validator.py
│   └── fixtures/
│       └── sample_contract.md
│
├── docs/                        # 设计文档
│
├── .env.example
├── .env                         # 本地环境变量（不提交）
├── .gitignore
└── pyproject.toml
```

---

## 核心模块说明

### `state.py` — 状态管理

```python
# 所有状态相关操作都通过这个模块
from task_agent.state import TaskContext, load_state, save_state

ctx = load_state(task_dir)    # 从 state.json 读取
ctx.state = TaskState.DEV_RED
save_state(ctx)                # 写回 state.json
```

**重要**：所有阶段切换前必须调用 `save_state()`，确保断点续跑正常工作。

### `runner.py` — 测试执行器

```python
from task_agent.runner import TestRunner, TestResult

runner = TestRunner(task_dir)
result: TestResult = runner.run_pytest()

# TestResult 字段：
# result.passed: int
# result.failed: int
# result.errors: int
# result.output: str     # pytest 完整输出
# result.failed_tests: list[str]  # 失败的测试名列表
```

执行方式：`subprocess.run(["python", "-m", "pytest", ...], capture_output=True)`

pytest 在任务目录的虚拟环境中执行，确保依赖隔离。

### `agents/base.py` — Claude API 封装

所有 Agent 的父类，统一管理 Claude 客户端的初始化。

支持通过 `ANTHROPIC_BASE_URL` 环境变量接入第三方中转站（兼容 Anthropic API 格式的代理服务）。未设置时直连官方 API。

```python
class BaseAgent:
    def __init__(self, model: str, system_prompt: str):
        # base_url 为空时 SDK 自动使用官方地址，无需特殊处理
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url or None,  # None = 官方默认
        )
        self.model = model
        self.system_prompt = system_prompt

    def call(self, messages: list[dict]) -> str:
        """单轮调用，返回文本响应"""

    def stream_call(self, messages: list[dict]) -> Iterator[str]:
        """流式调用，实时打印到终端"""
```

**中转站兼容性说明**：中转站需兼容 Anthropic Messages API 格式（`/v1/messages`）。
不兼容 OpenAI 格式的中转站无法直接使用，需要在中转站侧做协议转换。

### `agents/architect.py` — 交互式对话

```python
class ArchitectAgent(BaseAgent):
    def run(self, task_description: str) -> str:
        """
        返回 contract.md 的内容。
        内部维护 conversation_history，与用户实时交互。
        """
```

Architect Agent 的对话历史保存在 `tasks/{id}/architect_history.json`，支持断点恢复。

---

## pyproject.toml 结构

```toml
[project]
name = "task-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.40.0",      # Claude API
    "typer>=0.12.0",          # CLI 框架
    "rich>=13.0.0",           # 终端美化
    "python-dotenv>=1.0.0",   # .env 加载
    "tenacity>=9.0.0",        # 重试（Reviewer 检查用）
    "pydantic>=2.0.0",        # 数据模型校验
]

[project.scripts]
task-agent = "task_agent.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
    "pytest-asyncio>=0.23.0",
]
```

---

## 开发规范

### 代码风格

- 格式化：`ruff format`
- 检查：`ruff check`
- 类型检查：`mypy src/`

### 测试

```bash
# 运行项目自身的测试（不是生成的任务代码）
uv run pytest tests/ -v

# 运行特定测试
uv run pytest tests/test_runner.py -v
```

### 添加新功能的流程

1. 在 `docs/` 更新相关设计文档
2. 在 `tests/` 先写测试
3. 实现代码
4. 确认测试全绿
5. 更新 CHANGELOG

---

## 常见问题

**Q：任务目录里的代码用什么环境执行？**

A：Runner 会在任务目录下创建虚拟环境并安装 `tests/requirements.txt` 里的依赖，然后在这个虚拟环境里执行 pytest。这确保每个任务的依赖相互隔离。

```python
# runner.py 中的逻辑
subprocess.run(["uv", "venv", ".venv"], cwd=task_dir)
subprocess.run(["uv", "pip", "install", "-r", "tests/requirements.txt"], cwd=task_dir)
subprocess.run([".venv/bin/pytest", "tests/", "-v"], cwd=task_dir, capture_output=True)
```

**Q：Architect Agent 的对话历史如何恢复？**

A：每轮对话结束后，`architect_history.json` 立即写入磁盘。`resume` 时加载这个文件，传入 `messages` 数组继续对话。

**Q：如何跳过 Architect 阶段，直接用我自己写的契约文档？**

A：把你的契约文档放到 `tasks/{task_id}/contract.md`，然后运行：
```bash
task-agent dev --task-id {task_id}
```

**Q：生成的代码可以用于生产吗？**

A：可以作为起点，但建议人工审查后再用。Reviewer Agent 的审查覆盖稳定性和安全性基础要求，但不能替代人工的领域知识审查。

---

## .gitignore 建议

```gitignore
# 环境变量
.env

# 任务目录（包含生成的代码，通常不提交）
tasks/

# Python
__pycache__/
*.pyc
.venv/
dist/

# IDE
.idea/
.vscode/
```

如果希望提交某个任务的产物（用于演示），可以单独 `git add tasks/xxx/`。

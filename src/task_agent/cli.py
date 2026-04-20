"""CLI 入口：ai-workflow 交互式对话界面"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from task_agent import __version__

console = Console()

# ──────────────────────────────────────────────────────────
# 帮助文本
# ──────────────────────────────────────────────────────────

HELP_TEXT = """
[bold cyan]工作流命令[/bold cyan]
  [green]/run <任务描述>[/green]     启动完整工作流（architect → dev → review）
  [green]/resume [task-id][/green]   继续上次中断的任务
  [green]/dev [task-id][/green]      仅执行开发阶段
  [green]/review [task-id][/green]   仅执行代码审查
  [green]/hint [task-id][/green]     获取 AI 修复建议（不修改文件）
  [green]/abort [task-id][/green]    放弃当前任务

[bold cyan]查看信息[/bold cyan]
  [green]/status [task-id][/green]   查看任务状态
  [green]/list[/green]               列出所有历史任务

[bold cyan]其他[/bold cyan]
  [green]/clear[/green]              清空当前对话历史
  [green]/test[/green]               诊断中转站连通性
  [green]/help[/green]               显示此帮助
  [green]/quit[/green]  [green]/exit[/green]       退出

[dim]不带 / 的输入直接与 AI 对话[/dim]
"""


# ──────────────────────────────────────────────────────────
# 普通对话（chat 模式）
# ──────────────────────────────────────────────────────────

class ChatSession:
    """维护对话历史，直接与 Claude 聊天"""

    SYSTEM = "你是一个经验丰富的软件工程师助手，可以回答技术问题、帮助分析代码、讨论架构方案。如果用户有具体的开发任务需要执行，建议他们使用 /run 命令启动工作流。"

    def __init__(self) -> None:
        from task_agent.settings import settings
        from task_agent.agents.base import make_anthropic_client, make_openai_client
        self._format = settings.task_agent_api_format
        self.model = settings.task_agent_model
        self.client = make_openai_client() if self._format == "openai" else make_anthropic_client()
        self.history: list[dict] = []

    def chat(self, user_input: str) -> None:
        self.history.append({"role": "user", "content": user_input})
        full_reply = ""
        console.print("\n[bold cyan]AI[/bold cyan] ", end="")
        try:
            if self._format == "openai":
                full_reply = self._chat_openai()
            else:
                full_reply = self._chat_anthropic()
        except Exception as e:
            console.print(f"\n[red]错误：{e}[/red]")
            self.history.pop()
            return
        print()
        self.history.append({"role": "assistant", "content": full_reply})

    def _chat_anthropic(self) -> str:
        full = ""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=[{"type": "text", "text": self.SYSTEM}],
            messages=self.history,
        ) as stream:
            for chunk in stream.text_stream:
                print(chunk, end="", flush=True)
                full += chunk
        return full

    def _chat_openai(self) -> str:
        full = ""
        msgs = [{"role": "system", "content": self.SYSTEM}] + self.history
        with self.client.chat.completions.stream(
            model=self.model,
            max_tokens=4096,
            messages=msgs,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    print(delta, end="", flush=True)
                    full += delta
        return full

    def clear(self) -> None:
        self.history.clear()
        console.print("[dim]对话历史已清空[/dim]")


# ──────────────────────────────────────────────────────────
# 工作流命令处理器
# ──────────────────────────────────────────────────────────

def _engine(max_retry: int = 5):
    from task_agent.workflow import WorkflowEngine
    from task_agent.settings import settings
    return WorkflowEngine(max_dev_retry=max_retry or settings.task_agent_max_dev_retry)


def _parse_task_id(parts: list[str]) -> str | None:
    return parts[1] if len(parts) > 1 else None


def cmd_run(parts: list[str]) -> None:
    description = " ".join(parts[1:]).strip()
    if not description:
        description = console.input("[dim]请输入任务描述：[/dim] ").strip()
    if not description:
        console.print("[yellow]任务描述不能为空[/yellow]")
        return
    _engine().run(description)


def cmd_resume(parts: list[str]) -> None:
    from task_agent.utils.task_dir import find_task_dir
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
        _engine().resume(task_dir)
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")


def cmd_status(parts: list[str]) -> None:
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir
    from rich.table import Table
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
        ctx = load_state(task_dir)
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        return
    _ICONS = {"DONE": "✅", "PAUSED": "⏸️", "ERROR": "❌", "REVIEW_FAILED": "❌"}
    icon = _ICONS.get(ctx.state.value, "🔄")
    table = Table(title=f"任务：{ctx.task_id}", border_style="dim", show_header=False)
    table.add_column("项目", style="cyan", width=16)
    table.add_column("值")
    table.add_row("状态", f"{icon} {ctx.state.value}")
    table.add_row("描述", ctx.task_description)
    table.add_row("创建时间", ctx.created_at[:19])
    table.add_row("更新时间", ctx.updated_at[:19])
    if ctx.dev.retry_count:
        table.add_row("开发重试", f"{ctx.dev.retry_count}/{ctx.dev.max_retries}")
    if ctx.paused_reason:
        table.add_row("暂停原因", ctx.paused_reason)
    console.print(table)


def cmd_list() -> None:
    import json
    from task_agent.settings import settings
    from rich.table import Table
    tasks_dir = settings.task_agent_tasks_dir
    if not tasks_dir.exists():
        console.print("[dim]暂无任务记录[/dim]")
        return
    rows = []
    for d in tasks_dir.iterdir():
        sf = d / "state.json"
        if sf.exists():
            data = json.loads(sf.read_text())
            rows.append((
                data.get("updated_at", "")[:19],
                data.get("state", ""),
                d.name,
                data.get("task_description", "")[:40],
            ))
    if not rows:
        console.print("[dim]暂无任务记录[/dim]")
        return
    rows.sort(reverse=True)
    table = Table(border_style="dim")
    table.add_column("任务 ID", style="cyan", no_wrap=True)
    table.add_column("状态", width=16)
    table.add_column("更新时间", width=20)
    table.add_column("描述")
    _ICONS = {"DONE": "✅", "PAUSED": "⏸️", "ERROR": "❌", "REVIEW_FAILED": "❌"}
    for updated, state, name, desc in rows[:10]:
        table.add_row(name, f"{_ICONS.get(state, '🔄')} {state}", updated, desc)
    console.print(table)


def cmd_dev(parts: list[str]) -> None:
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
        ctx = load_state(task_dir)
        contract_path = task_dir / "contract.md"
        if not contract_path.exists():
            console.print("[red]找不到 contract.md，请先运行 /run 完成需求梳理[/red]")
            return
        _engine()._phase_dev(ctx, task_dir, contract_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")


def cmd_review(parts: list[str]) -> None:
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
        ctx = load_state(task_dir)
        contract = (task_dir / "contract.md").read_text(encoding="utf-8")
        _engine()._phase_review(ctx, task_dir, contract)
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")


def cmd_hint(parts: list[str]) -> None:
    from task_agent.agents.developer import DeveloperAgent
    from task_agent.utils.file_writer import collect_src_files
    from task_agent.utils.task_dir import find_task_dir
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        return
    results_dir = task_dir / "test_results"
    last_output = ""
    if results_dir.exists():
        runs = sorted(results_dir.glob("*.txt"))
        if runs:
            last_output = runs[-1].read_text(encoding="utf-8")
    if not last_output:
        console.print("[yellow]没有找到测试结果[/yellow]")
        return
    contract = (task_dir / "contract.md").read_text(encoding="utf-8")
    dev = DeveloperAgent()
    console.print("\n[bold cyan]AI 修复建议（不会修改文件）[/bold cyan]\n")
    msgs = [{"role": "user", "content": (
        f"<contract>\n{contract}\n</contract>\n\n"
        f"<current_files>\n{collect_src_files(task_dir)}\n</current_files>\n\n"
        f"<test_results>\n{last_output}\n</test_results>\n\n"
        "<instruction>只给出修复建议，不输出完整文件，用简洁 diff 格式说明需要修改什么</instruction>"
    )}]
    for chunk in dev.stream_call(msgs):
        print(chunk, end="", flush=True)
    print()


def cmd_abort(parts: list[str]) -> None:
    from task_agent.state import TaskState, load_state, save_state
    from task_agent.utils.task_dir import find_task_dir
    try:
        task_dir = find_task_dir(_parse_task_id(parts))
        ctx = load_state(task_dir)
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        return
    ans = console.input(f"确认放弃任务 [cyan]{ctx.task_id}[/cyan]？[y/N] ").strip().lower()
    if ans in ("y", "yes"):
        ctx.state = TaskState.ERROR
        ctx.error = "用户手动放弃"
        save_state(ctx, task_dir)
        console.print("[yellow]任务已放弃，目录保留[/yellow]")


# ──────────────────────────────────────────────────────────
# REPL 主循环
# ──────────────────────────────────────────────────────────

def cmd_test(_parts: list[str]) -> None:
    from task_agent.debug_relay import run_diagnosis
    run_diagnosis()


SLASH_COMMANDS: dict[str, object] = {
    "/run":    cmd_run,
    "/resume": cmd_resume,
    "/status": cmd_status,
    "/dev":    cmd_dev,
    "/review": cmd_review,
    "/hint":   cmd_hint,
    "/abort":  cmd_abort,
    "/test":   cmd_test,
}


def _print_banner() -> None:
    console.print(Panel(
        Text.assemble(
            ("AI Workflow ", "bold cyan"),
            (f"v{__version__}\n", "dim"),
            ("直接输入与 AI 对话，", "white"),
            ("/run <任务>", "green"),
            (" 启动工作流，", "white"),
            ("/help", "green"),
            (" 查看命令", "white"),
        ),
        border_style="cyan",
        padding=(0, 2),
    ))


def repl() -> None:
    _print_banner()
    session = ChatSession()

    while True:
        try:
            raw = console.input("\n[bold green]>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！[/dim]")
            break

        if not raw:
            continue

        # 退出
        if raw.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]再见！[/dim]")
            break

        # 帮助
        if raw.lower() in ("/help", "/h", "?"):
            console.print(HELP_TEXT)
            continue

        # 清空对话历史
        if raw.lower() == "/clear":
            session.clear()
            continue

        # 斜杠工作流命令
        if raw.startswith("/"):
            parts = raw.split()
            cmd = parts[0].lower()
            handler = SLASH_COMMANDS.get(cmd)
            if handler is None:
                console.print(f"[red]未知命令：{cmd}[/red]  输入 /help 查看可用命令")
                continue
            if cmd == "/list":
                cmd_list()
            else:
                handler(parts)  # type: ignore[call-arg]
            continue

        # 普通文本 → chat 模式
        session.chat(raw)


# ──────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────

def main() -> None:
    repl()


if __name__ == "__main__":
    main()

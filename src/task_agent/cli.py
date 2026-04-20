"""CLI 入口：task-agent"""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from task_agent.settings import settings

app = typer.Typer(
    name="task-agent",
    help="多 Agent 任务交付流水线：architect → dev → review",
    add_completion=False,
)
console = Console()


def _engine(max_retry: int | None = None):
    from task_agent.workflow import WorkflowEngine
    return WorkflowEngine(max_dev_retry=max_retry or settings.task_agent_max_dev_retry)


# ──────────────────────────────────────────────────────────
# task-agent run
# ──────────────────────────────────────────────────────────

@app.command()
def run(
    description: Annotated[Optional[str], typer.Argument(help="任务描述")] = None,
    max_retry: Annotated[int, typer.Option("--max-retry", help="Developer 最大重试次数")] = 5,
    skip_review: Annotated[bool, typer.Option("--skip-review", help="跳过 Review 阶段")] = False,
) -> None:
    """全流程：architect → dev → review"""
    if not description:
        description = typer.prompt("请输入任务描述")
    _engine(max_retry).run(description, skip_review=skip_review)


# ──────────────────────────────────────────────────────────
# task-agent architect
# ──────────────────────────────────────────────────────────

@app.command()
def architect(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
) -> None:
    """仅执行需求梳理阶段，生成契约文档"""
    from task_agent.utils.task_dir import find_task_dir

    if task_id:
        task_dir = find_task_dir(task_id)
        from task_agent.state import load_state
        ctx = load_state(task_dir)
        description = ctx.task_description
    else:
        description = typer.prompt("请输入任务描述")
        from task_agent.utils.task_dir import create_task_dir, make_task_id
        from task_agent.state import new_context, save_state
        tid = make_task_id(description)
        task_dir = create_task_dir(tid)
        ctx = new_context(tid, description)
        save_state(ctx, task_dir)

    engine = _engine()
    engine._phase_architect(ctx, task_dir, description)


# ──────────────────────────────────────────────────────────
# task-agent dev
# ──────────────────────────────────────────────────────────

@app.command()
def dev(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
    max_retry: Annotated[int, typer.Option("--max-retry")] = 5,
    phase: Annotated[str, typer.Option("--phase", help="red|green|refactor")] = "red",
) -> None:
    """仅执行开发阶段（需要已有 contract.md）"""
    from task_agent.state import load_state, TaskState
    from task_agent.utils.task_dir import find_task_dir

    task_dir = find_task_dir(task_id)
    ctx = load_state(task_dir)
    contract_path = task_dir / "contract.md"
    if not contract_path.exists():
        console.print("[red]错误：找不到 contract.md，请先运行 architect[/red]")
        raise typer.Exit(1)
    contract = contract_path.read_text(encoding="utf-8")
    _engine(max_retry)._phase_dev(ctx, task_dir, contract)


# ──────────────────────────────────────────────────────────
# task-agent review
# ──────────────────────────────────────────────────────────

@app.command()
def review(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
) -> None:
    """仅执行代码审查阶段"""
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir

    task_dir = find_task_dir(task_id)
    ctx = load_state(task_dir)
    contract = (task_dir / "contract.md").read_text(encoding="utf-8")
    _engine()._phase_review(ctx, task_dir, contract)


# ──────────────────────────────────────────────────────────
# task-agent resume
# ──────────────────────────────────────────────────────────

@app.command()
def resume(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
) -> None:
    """从上次中断处继续"""
    from task_agent.utils.task_dir import find_task_dir
    task_dir = find_task_dir(task_id)
    _engine().resume(task_dir)


# ──────────────────────────────────────────────────────────
# task-agent status
# ──────────────────────────────────────────────────────────

@app.command()
def status(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """查看当前任务状态"""
    import json
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir

    task_dir = find_task_dir(task_id)
    ctx = load_state(task_dir)

    if as_json:
        from dataclasses import asdict
        typer.echo(json.dumps(asdict(ctx), ensure_ascii=False, indent=2))
        return

    _STATE_ICONS = {
        "DONE": "✅", "PAUSED": "⏸️", "ERROR": "❌",
        "REVIEW": "🔍", "REVIEW_FAILED": "❌",
        "DEV_GREEN": "🔄", "DEV_RED": "🔄",
    }
    icon = _STATE_ICONS.get(ctx.state.value, "🔄")

    table = Table(title=f"任务：{ctx.task_id}", border_style="dim")
    table.add_column("项目", style="cyan")
    table.add_column("值")
    table.add_row("状态", f"{icon} {ctx.state.value}")
    table.add_row("描述", ctx.task_description)
    table.add_row("创建时间", ctx.created_at)
    table.add_row("更新时间", ctx.updated_at)
    if ctx.dev.retry_count:
        table.add_row("开发重试次数", f"{ctx.dev.retry_count}/{ctx.dev.max_retries}")
    if ctx.paused_reason:
        table.add_row("暂停原因", ctx.paused_reason)
    console.print(table)


# ──────────────────────────────────────────────────────────
# task-agent list
# ──────────────────────────────────────────────────────────

@app.command(name="list")
def list_tasks(
    limit: Annotated[int, typer.Option("--limit")] = 10,
    state_filter: Annotated[Optional[str], typer.Option("--state")] = None,
) -> None:
    """列出所有历史任务"""
    import json

    tasks_dir = settings.task_agent_tasks_dir
    if not tasks_dir.exists():
        console.print("暂无任务记录")
        return

    rows = []
    for d in tasks_dir.iterdir():
        sf = d / "state.json"
        if not sf.exists():
            continue
        data = json.loads(sf.read_text())
        s = data.get("state", "")
        if state_filter and state_filter.upper() not in s:
            continue
        rows.append((data.get("updated_at", ""), s, d.name, data.get("task_description", "")))

    rows.sort(reverse=True)
    rows = rows[:limit]

    table = Table(border_style="dim")
    table.add_column("任务 ID", style="cyan", no_wrap=True)
    table.add_column("状态")
    table.add_column("更新时间")
    table.add_column("描述")

    _ICONS = {"DONE": "✅", "PAUSED": "⏸️", "ERROR": "❌"}
    for updated, state, name, desc in rows:
        icon = _ICONS.get(state, "🔄")
        table.add_row(name, f"{icon} {state}", updated[:19], desc[:40])

    console.print(table)


# ──────────────────────────────────────────────────────────
# task-agent hint
# ──────────────────────────────────────────────────────────

@app.command()
def hint(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
) -> None:
    """获取 AI 修复建议（不修改文件）"""
    from task_agent.agents.developer import DeveloperAgent
    from task_agent.state import load_state
    from task_agent.utils.task_dir import find_task_dir

    task_dir = find_task_dir(task_id)
    ctx = load_state(task_dir)

    results_dir = task_dir / "test_results"
    last_output = ""
    if results_dir.exists():
        runs = sorted(results_dir.glob("*.txt"))
        if runs:
            last_output = runs[-1].read_text(encoding="utf-8")

    if not last_output:
        console.print("[yellow]没有找到测试结果，请先运行开发阶段[/yellow]")
        return

    contract = (task_dir / "contract.md").read_text(encoding="utf-8")
    dev = DeveloperAgent()
    console.print("\n[bold cyan]AI 修复建议（不会修改任何文件）[/bold cyan]\n")
    from task_agent.utils.file_writer import collect_src_files
    msgs = [{
        "role": "user",
        "content": (
            f"<contract>\n{contract}\n</contract>\n\n"
            f"<current_files>\n{collect_src_files(task_dir)}\n</current_files>\n\n"
            f"<test_results>\n{last_output}\n</test_results>\n\n"
            "<instruction>只给出修复建议，不要输出完整文件，用简洁的diff格式说明需要修改什么</instruction>"
        ),
    }]
    for chunk in dev.stream_call(msgs):
        print(chunk, end="", flush=True)
    print()


# ──────────────────────────────────────────────────────────
# task-agent abort
# ──────────────────────────────────────────────────────────

@app.command()
def abort(
    task_id: Annotated[Optional[str], typer.Option("--task-id")] = None,
) -> None:
    """放弃当前任务（保留目录，状态置为 ERROR）"""
    from task_agent.state import TaskState, load_state, save_state
    from task_agent.utils.task_dir import find_task_dir

    task_dir = find_task_dir(task_id)
    ctx = load_state(task_dir)
    confirm = typer.confirm(f"确认放弃任务 {ctx.task_id}？")
    if confirm:
        ctx.state = TaskState.ERROR
        ctx.error = "用户手动放弃"
        save_state(ctx, task_dir)
        console.print(f"[yellow]任务已标记为 ERROR，目录保留：{task_dir}[/yellow]")


if __name__ == "__main__":
    app()

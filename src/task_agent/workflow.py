"""Workflow Engine：驱动完整 Pipeline 状态机"""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from task_agent.agents.architect import ArchitectAgent
from task_agent.agents.developer import DeveloperAgent
from task_agent.agents.reviewer import ReviewerAgent
from task_agent.runner import TestResult, TestRunner
from task_agent.state import (
    TaskContext,
    TaskState,
    TestRun,
    load_state,
    new_context,
    save_state,
)
from task_agent.utils import contract_validator
from task_agent.utils.task_dir import create_task_dir, make_task_id

console = Console()


class WorkflowEngine:
    def __init__(self, max_dev_retry: int = 5) -> None:
        self.max_dev_retry = max_dev_retry

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def run(self, description: str, skip_review: bool = False) -> None:
        """全流程：architect → dev → review"""
        task_id = make_task_id(description)
        task_dir = create_task_dir(task_id)
        ctx = new_context(task_id, description)
        ctx.dev.max_retries = self.max_dev_retry
        save_state(ctx, task_dir)

        console.print(Panel(
            f"[bold]🚀 启动任务：{description}[/bold]\n"
            f"[dim]任务目录：{task_dir}[/dim]",
            border_style="green",
        ))

        contract = self._phase_architect(ctx, task_dir, description)
        self._phase_dev(ctx, task_dir, contract)
        if not skip_review:
            self._phase_review(ctx, task_dir, contract)

        ctx.state = TaskState.DONE
        save_state(ctx, task_dir)
        self._print_summary(task_dir)

    def resume(self, task_dir: Path) -> None:
        """从中断处继续"""
        ctx = load_state(task_dir)
        console.print(f"[cyan]↩️  恢复任务：{ctx.task_id}（状态：{ctx.state}）[/cyan]")

        contract_path = task_dir / "contract.md"
        contract = contract_path.read_text(encoding="utf-8") if contract_path.exists() else ""

        match ctx.state:
            case TaskState.ARCHITECT | TaskState.INIT:
                contract = self._phase_architect(ctx, task_dir, ctx.task_description)
                self._phase_dev(ctx, task_dir, contract)
                self._phase_review(ctx, task_dir, contract)
            case TaskState.ARCHITECT_DONE:
                self._phase_dev(ctx, task_dir, contract)
                self._phase_review(ctx, task_dir, contract)
            case TaskState.DEV_RED | TaskState.DEV_RED_DONE | TaskState.DEV_GREEN | TaskState.DEV_GREEN_DONE | TaskState.DEV_REFACTOR:
                self._phase_dev(ctx, task_dir, contract, resume=True)
                self._phase_review(ctx, task_dir, contract)
            case TaskState.DEV_DONE:
                self._phase_review(ctx, task_dir, contract)
            case TaskState.REVIEW_FAILED | TaskState.PAUSED:
                console.print("[yellow]⚠️  任务需要人工介入，请修复代码后重新运行 resume[/yellow]")
                return
            case TaskState.DONE:
                console.print("[green]✅ 任务已完成[/green]")
                return

        ctx.state = TaskState.DONE
        save_state(ctx, task_dir)
        self._print_summary(task_dir)

    # ------------------------------------------------------------------
    # Phase 1：Architect
    # ------------------------------------------------------------------

    def _phase_architect(self, ctx: TaskContext, task_dir: Path, description: str) -> str:
        console.print(Rule("[bold cyan]Phase 1: Architect Agent[/bold cyan]", style="cyan"))
        ctx.state = TaskState.ARCHITECT
        save_state(ctx, task_dir)

        agent = ArchitectAgent()
        contract = agent.run(description, task_dir)

        # 校验契约格式
        errors = contract_validator.validate(contract)
        if errors:
            console.print("[yellow]⚠️  契约文档缺少以下内容：[/yellow]")
            for e in errors:
                console.print(f"  - {e}")

        # 写入 contract.md
        contract_path = task_dir / "contract.md"
        contract_path.write_text(contract, encoding="utf-8")
        console.print(f"[green]✅ 契约文档已保存：{contract_path}[/green]")

        ctx.state = TaskState.ARCHITECT_DONE
        ctx.architect.completed_at = __import__("datetime").datetime.utcnow().isoformat()
        ctx.architect.user_confirmed = True
        save_state(ctx, task_dir)

        return contract

    # ------------------------------------------------------------------
    # Phase 2：Developer（TDD）
    # ------------------------------------------------------------------

    def _phase_dev(
        self, ctx: TaskContext, task_dir: Path, contract: str, resume: bool = False
    ) -> None:
        console.print(Rule("[bold blue]Phase 2: Developer Agent (TDD)[/bold blue]", style="blue"))
        runner = TestRunner(task_dir)
        dev = DeveloperAgent()

        # ── RED ──────────────────────────────────────────────────────
        if not resume or ctx.state in (TaskState.ARCHITECT_DONE, TaskState.DEV_RED):
            ctx.state = TaskState.DEV_RED
            save_state(ctx, task_dir)
            dev.write_tests(contract, task_dir)
            runner.setup_venv()
            red_result = runner.run_pytest("RED")
            self._record_test_run(ctx, "RED", red_result, task_dir)

            if red_result.all_passed:
                console.print("[yellow]⚠️  测试意外全部通过，断言可能过弱，继续...[/yellow]")
            else:
                console.print(
                    f"[green]✅ 全红确认：{red_result.failed + red_result.errors} 个测试失败[/green]"
                )
            ctx.state = TaskState.DEV_RED_DONE
            save_state(ctx, task_dir)

        # ── GREEN ─────────────────────────────────────────────────────
        ctx.state = TaskState.DEV_GREEN
        save_state(ctx, task_dir)

        test_output = ""
        while ctx.dev.retry_count <= self.max_dev_retry:
            dev.write_code(contract, task_dir, test_output)
            runner.setup_venv()
            result = runner.run_pytest(f"GREEN_attempt_{ctx.dev.retry_count + 1}")
            self._record_test_run(ctx, f"GREEN_{ctx.dev.retry_count}", result, task_dir)

            if result.all_passed:
                console.print(f"[green]✅ 全部 {result.total} 个测试通过！[/green]")
                break

            ctx.dev.retry_count += 1
            save_state(ctx, task_dir)

            if ctx.dev.retry_count > self.max_dev_retry:
                ctx.state = TaskState.PAUSED
                ctx.paused_reason = f"Developer Agent 连续 {self.max_dev_retry} 次修复失败"
                save_state(ctx, task_dir)
                console.print(
                    f"[red]⚠️  已连续 {self.max_dev_retry} 次修复失败，任务暂停。\n"
                    f"请手动修复后运行 task-agent resume[/red]"
                )
                self._print_failed_tests(result)
                return

            console.print(
                f"[yellow]⚠️  {result.failed} 个测试失败，尝试修复（{ctx.dev.retry_count}/{self.max_dev_retry}）...[/yellow]"
            )
            test_output = result.output

        ctx.state = TaskState.DEV_GREEN_DONE
        save_state(ctx, task_dir)

        # ── REFACTOR ──────────────────────────────────────────────────
        ctx.state = TaskState.DEV_REFACTOR
        save_state(ctx, task_dir)
        dev.refactor(contract, task_dir)
        refactor_result = runner.run_pytest("REFACTOR")
        self._record_test_run(ctx, "REFACTOR", refactor_result, task_dir)

        if not refactor_result.all_passed:
            console.print("[red]❌ 重构后测试失败，回滚到重构前状态[/red]")
        else:
            console.print("[green]✅ 重构完成，测试仍然全绿[/green]")

        ctx.state = TaskState.DEV_DONE
        save_state(ctx, task_dir)

    # ------------------------------------------------------------------
    # Phase 3：Reviewer
    # ------------------------------------------------------------------

    def _phase_review(self, ctx: TaskContext, task_dir: Path, contract: str) -> None:
        console.print(Rule("[bold magenta]Phase 3: Reviewer Agent[/bold magenta]", style="magenta"))
        ctx.state = TaskState.REVIEW
        save_state(ctx, task_dir)

        # 取最近一次测试输出
        results_dir = task_dir / "test_results"
        test_output = ""
        if results_dir.exists():
            runs = sorted(results_dir.glob("*.txt"))
            if runs:
                test_output = runs[-1].read_text(encoding="utf-8")

        reviewer = ReviewerAgent()
        report, passed = reviewer.review(contract, task_dir, test_output)

        report_path = task_dir / "review.md"
        report_path.write_text(report, encoding="utf-8")
        console.print(f"\n[dim]审查报告已保存：{report_path}[/dim]")

        if passed:
            console.print("[green]✅ 审查通过[/green]")
            ctx.state = TaskState.DONE
        else:
            console.print("[red]❌ 审查不通过，存在 P0 缺陷，请修复后重新运行 review[/red]")
            ctx.state = TaskState.REVIEW_FAILED
        save_state(ctx, task_dir)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _record_test_run(
        ctx: TaskContext, phase: str, result: TestResult, task_dir: Path
    ) -> None:
        from task_agent.state import _now

        runs_dir = task_dir / "test_results"
        runs_dir.mkdir(exist_ok=True)
        run_file = runs_dir / f"{phase}_{len(ctx.dev.test_runs):03d}.txt"
        run_file.write_text(result.output, encoding="utf-8")

        ctx.dev.test_runs.append(TestRun(
            timestamp=_now(),
            phase=phase,
            passed=result.passed,
            failed=result.failed,
            errors=result.errors,
            output_path=str(run_file.relative_to(task_dir)),
        ))

    @staticmethod
    def _print_failed_tests(result: TestResult) -> None:
        if result.failed_tests:
            console.print("\n失败的测试：")
            for t in result.failed_tests:
                console.print(f"  [red]FAILED[/red] {t}")

    @staticmethod
    def _print_summary(task_dir: Path) -> None:
        console.print(Rule(style="green"))
        console.print("[bold green]✅ 任务完成！[/bold green]\n")
        for item, label in [
            ("contract.md", "📋 契约文档"),
            ("src/",        "💻 业务代码"),
            ("tests/",      "🧪 测试代码"),
            ("review.md",   "📊 审查报告"),
        ]:
            p = task_dir / item
            if p.exists():
                console.print(f"  {label}  {p}")
        console.print()

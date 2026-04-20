"""DeveloperAgent：唯一编码 Agent，完成所有代码产出"""

from pathlib import Path

from rich.console import Console

from task_agent.agents.base import BaseAgent
from task_agent.utils.file_writer import collect_src_files, parse_agent_files, write_files

console = Console()


class DeveloperAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("developer")

    def _build_message(
        self,
        contract: str,
        instruction: str,
        task_dir: Path,
        test_output: str = "",
    ) -> list[dict]:
        current_files = collect_src_files(task_dir)
        parts = [
            f"<contract>\n{contract}\n</contract>",
            f"<instruction>\n{instruction}\n</instruction>",
        ]
        if current_files:
            parts.append(f"<current_files>\n{current_files}\n</current_files>")
        if test_output:
            parts.append(f"<test_results>\n{test_output}\n</test_results>")

        return [{"role": "user", "content": "\n\n".join(parts)}]

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def write_tests(self, contract: str, task_dir: Path) -> list[Path]:
        """Phase RED：生成测试套件"""
        console.print("[cyan]📝 [RED] 生成测试用例...[/cyan]")
        msgs = self._build_message(contract, "write_tests", task_dir)
        response = self._stream_with_header(msgs, "Developer → 测试代码")
        files = parse_agent_files(response)
        if not files:
            raise RuntimeError("Developer Agent 未输出任何文件，请检查响应格式")
        written = write_files(files, task_dir)
        console.print(f"[green]  写入 {len(written)} 个文件[/green]")
        return written

    def write_code(self, contract: str, task_dir: Path, test_output: str = "") -> list[Path]:
        """Phase GREEN：生成业务代码"""
        if test_output:
            instruction = "fix_code"
            console.print("[cyan]💻 [GREEN] 修复业务代码...[/cyan]")
        else:
            instruction = "write_code"
            console.print("[cyan]💻 [GREEN] 生成业务代码...[/cyan]")
        msgs = self._build_message(contract, instruction, task_dir, test_output)
        response = self._stream_with_header(msgs, "Developer → 业务代码")
        files = parse_agent_files(response)
        if not files:
            raise RuntimeError("Developer Agent 未输出任何文件")
        written = write_files(files, task_dir)
        console.print(f"[green]  写入 {len(written)} 个文件[/green]")
        return written

    def refactor(self, contract: str, task_dir: Path) -> list[Path]:
        """Phase REFACTOR：重构代码"""
        console.print("[cyan]🔨 [REFACTOR] 重构代码...[/cyan]")
        msgs = self._build_message(contract, "refactor", task_dir)
        response = self._stream_with_header(msgs, "Developer → 重构")
        files = parse_agent_files(response)
        written = write_files(files, task_dir) if files else []
        console.print(f"[green]  重构完成，更新 {len(written)} 个文件[/green]")
        return written

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _stream_with_header(self, messages: list[dict], header: str) -> str:
        console.print(f"\n[dim]{header}[/dim]")
        full = ""
        for chunk in self.stream_call(messages):
            print(chunk, end="", flush=True)
            full += chunk
        print()
        return full

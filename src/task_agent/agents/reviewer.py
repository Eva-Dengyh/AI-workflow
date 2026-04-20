"""ReviewerAgent：契约式代码审查"""

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from task_agent.agents.base import BaseAgent
from task_agent.utils.file_writer import collect_src_files

console = Console()


class ReviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("reviewer")

    def review(self, contract: str, task_dir: Path, test_output: str) -> tuple[str, bool]:
        """
        执行审查，返回 (审查报告内容, 是否通过)
        通过标准：审查报告中不含 P0 缺陷（即结论为 ✅ 或 ⚠️）
        """
        console.print("\n[cyan]🔍 开始代码审查...[/cyan]")

        src_files = collect_src_files(task_dir)
        user_content = "\n\n".join([
            f"<contract>\n{contract}\n</contract>",
            f"<source_files>\n{src_files}\n</source_files>",
            f"<test_results>\n{test_output}\n</test_results>",
        ])

        messages = [{"role": "user", "content": user_content}]
        report = ""
        for chunk in self.stream_call(messages):
            print(chunk, end="", flush=True)
            report += chunk
        print()

        passed = self._is_passed(report)
        return report, passed

    @staticmethod
    def _is_passed(report: str) -> bool:
        """❌ 不通过 → False，其余 → True"""
        # 查找结论行
        for line in report.splitlines():
            if "审查结论" in line or "结论" in line:
                if "❌" in line:
                    return False
        # 备用：全文搜索 P0 缺陷
        if "P0" in report and ("缺失" in report or "缺少" in report):
            lower = report.lower()
            if "不通过" in lower or "❌" in lower:
                return False
        return True

"""ArchitectAgent：交互式需求梳理，产出《开发契约文档》"""

import json
from pathlib import Path
from typing import Iterator

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from task_agent.agents.base import BaseAgent

console = Console()

_HISTORY_FILE = "architect_history.json"


class ArchitectAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("architect")
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    # 断点续跑支持
    # ------------------------------------------------------------------

    def load_history(self, task_dir: Path) -> None:
        f = task_dir / _HISTORY_FILE
        if f.exists():
            self.history = json.loads(f.read_text(encoding="utf-8"))

    def save_history(self, task_dir: Path) -> None:
        (task_dir / _HISTORY_FILE).write_text(
            json.dumps(self.history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run(self, task_description: str, task_dir: Path) -> str:
        """
        交互式对话，直到用户确认契约。
        返回 contract.md 的内容。
        """
        console.print(Panel(
            f"[bold cyan]Architect Agent[/bold cyan]\n任务：{task_description}",
            border_style="cyan",
        ))

        # 若有历史记录（断点续跑），加载后继续
        self.load_history(task_dir)

        if not self.history:
            # 首次启动，把任务描述作为第一条用户消息
            self.history.append({"role": "user", "content": task_description})

        max_turns = 20
        turns = len([m for m in self.history if m["role"] == "user"])

        while turns < max_turns:
            # Agent 回复（流式输出）
            reply = self._stream_reply(task_dir)

            # 检查是否已产出契约文档
            if "# 开发契约文档" in reply and "## 6." in reply:
                contract = self._extract_contract(reply)
                console.print("\n[bold green]✅ 契约文档已生成[/bold green]")
                confirmed = self._ask_confirmation()
                if confirmed:
                    return contract
                else:
                    # 用户要求修改
                    correction = console.input("\n[bold]请描述需要修改的内容：[/bold] ")
                    self.history.append({"role": "user", "content": correction})
                    self.save_history(task_dir)
                    turns += 1
                    continue

            # 追问用户
            user_input = console.input("\n[bold yellow]你[/bold yellow] > ")
            if not user_input.strip():
                continue
            self.history.append({"role": "user", "content": user_input})
            self.save_history(task_dir)
            turns += 1

        # 超过最大轮数，强制输出当前最佳版本
        console.print("[yellow]⚠️  已达到最大对话轮数，强制生成当前契约草稿[/yellow]")
        self.history.append({"role": "user", "content": "请立即输出当前收集到的信息作为契约文档，即使信息不完整也要输出。"})
        reply = self.call(self.history)
        self.history.append({"role": "assistant", "content": reply})
        self.save_history(task_dir)
        return self._extract_contract(reply)

    def _stream_reply(self, task_dir: Path) -> str:
        """流式输出 Agent 回复，返回完整文本"""
        console.print("\n[bold cyan]Architect[/bold cyan] > ", end="")
        full_reply = ""
        for chunk in self.stream_call(self.history):
            print(chunk, end="", flush=True)
            full_reply += chunk
        print()
        self.history.append({"role": "assistant", "content": full_reply})
        self.save_history(task_dir)
        return full_reply

    @staticmethod
    def _extract_contract(reply: str) -> str:
        """从回复中提取 # 开发契约文档 ... 部分"""
        idx = reply.find("# 开发契约文档")
        if idx != -1:
            return reply[idx:]
        return reply

    @staticmethod
    def _ask_confirmation() -> bool:
        while True:
            ans = console.input(
                "\n[bold]请确认契约内容（输入 '确认' 继续，或描述需要修改的地方）：[/bold] "
            ).strip()
            if ans in ("确认", "confirm", "yes", "y", "ok", "OK"):
                return True
            if ans:
                return False

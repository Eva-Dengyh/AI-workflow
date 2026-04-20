"""测试执行器：在任务目录的隔离虚拟环境中执行 pytest"""

import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    output: str = ""
    failed_tests: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errors == 0

    @property
    def all_failed(self) -> bool:
        return self.passed == 0 and (self.failed + self.errors) > 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors


class TestRunner:
    def __init__(self, task_dir: Path) -> None:
        self.task_dir = task_dir
        self.venv_dir = task_dir / ".venv"
        self.results_dir = task_dir / "test_results"
        self.results_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # 环境准备
    # ------------------------------------------------------------------

    def setup_venv(self) -> None:
        """创建虚拟环境并安装依赖"""
        if not self.venv_dir.exists():
            subprocess.run(
                ["uv", "venv", str(self.venv_dir)],
                cwd=self.task_dir, check=True, capture_output=True,
            )
        self._install_deps()

    def _install_deps(self) -> None:
        pip = self._pip()
        for req in ["src/requirements.txt", "tests/requirements.txt"]:
            req_path = self.task_dir / req
            if req_path.exists():
                subprocess.run(
                    [pip, "install", "-r", str(req_path)],
                    cwd=self.task_dir, check=True, capture_output=True,
                )

    def _pip(self) -> str:
        if sys.platform == "win32":
            return str(self.venv_dir / "Scripts" / "pip")
        return str(self.venv_dir / "bin" / "pip")

    def _python(self) -> str:
        if sys.platform == "win32":
            return str(self.venv_dir / "Scripts" / "python")
        return str(self.venv_dir / "bin" / "python")

    # ------------------------------------------------------------------
    # 测试执行
    # ------------------------------------------------------------------

    def run_pytest(self, phase: str = "") -> TestResult:
        """执行 pytest，返回解析后的结果，并把输出持久化"""
        python = self._python()
        proc = subprocess.run(
            [python, "-m", "pytest", "tests/", "-v", "--tb=short", "--no-header"],
            cwd=self.task_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = proc.stdout + proc.stderr
        result = self._parse_output(output)

        # 持久化输出
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        label = f"_{phase}" if phase else ""
        out_file = self.results_dir / f"run{label}_{ts}.txt"
        out_file.write_text(output, encoding="utf-8")
        result.output = output

        return result

    @staticmethod
    def _parse_output(output: str) -> TestResult:
        result = TestResult()
        failed_tests: list[str] = []

        for line in output.splitlines():
            # 统计行："5 passed, 2 failed, 1 error in 0.30s"
            if " passed" in line or " failed" in line or " error" in line:
                import re
                p = re.search(r"(\d+) passed", line)
                f = re.search(r"(\d+) failed", line)
                e = re.search(r"(\d+) error", line)
                if p:
                    result.passed = int(p.group(1))
                if f:
                    result.failed = int(f.group(1))
                if e:
                    result.errors = int(e.group(1))

            # 收集失败的测试名
            if line.startswith("FAILED "):
                test_name = line.split("FAILED ", 1)[1].split(" ")[0]
                failed_tests.append(test_name)

        result.failed_tests = failed_tests
        return result

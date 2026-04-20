"""解析 Developer Agent 输出的多文件格式，安全写入磁盘"""

import re
from pathlib import Path


_FILE_PATTERN = re.compile(
    r"={3,}\s*FILE:\s*(.+?)\s*={3,}\n(.*?)(?=={3,}\s*(?:FILE:|END FILE)|$)",
    re.DOTALL,
)


def parse_agent_files(response: str) -> dict[str, str]:
    """
    解析格式：
      === FILE: src/service.py ===
      {内容}
      === END FILE ===
    返回 {相对路径: 内容} 字典
    """
    result: dict[str, str] = {}
    for m in _FILE_PATTERN.finditer(response):
        path = m.group(1).strip()
        content = m.group(2).rstrip()
        if path and content:
            result[path] = content
    return result


def write_files(files: dict[str, str], task_dir: Path) -> list[Path]:
    """把解析出的文件写入 task_dir，返回写入的路径列表"""
    written: list[Path] = []
    for rel_path, content in files.items():
        dest = (task_dir / rel_path).resolve()
        # 安全检查：禁止写到任务目录之外
        dest.relative_to(task_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(dest)
    return written


def collect_src_files(task_dir: Path) -> str:
    """把 src/ 和 tests/ 下所有 .py 文件收集成字符串，供 Agent 读取"""
    parts: list[str] = []
    for pattern in ["src/**/*.py", "tests/**/*.py",
                    "src/requirements.txt", "tests/requirements.txt"]:
        for f in sorted(task_dir.glob(pattern)):
            rel = f.relative_to(task_dir)
            parts.append(f"=== FILE: {rel} ===\n{f.read_text(encoding='utf-8')}\n=== END FILE ===")
    return "\n\n".join(parts)

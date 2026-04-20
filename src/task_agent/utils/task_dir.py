import re
from datetime import datetime, timezone
from pathlib import Path

from task_agent.settings import settings


def make_task_id(description: str) -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", description.strip())[:30].strip("_")
    return f"{date}_{slug}"


def create_task_dir(task_id: str) -> Path:
    task_dir = settings.task_agent_tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "src").mkdir(exist_ok=True)
    (task_dir / "tests").mkdir(exist_ok=True)
    (task_dir / "test_results").mkdir(exist_ok=True)
    return task_dir


def find_latest_active_task() -> Path | None:
    """找到最近一个未完成的任务目录"""
    import json
    tasks_dir = settings.task_agent_tasks_dir
    if not tasks_dir.exists():
        return None
    candidates = []
    for d in tasks_dir.iterdir():
        sf = d / "state.json"
        if sf.exists():
            data = json.loads(sf.read_text())
            state = data.get("state", "")
            if state not in ("DONE", "ERROR"):
                candidates.append((data.get("updated_at", ""), d))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def find_task_dir(task_id: str | None) -> Path:
    if task_id:
        d = settings.task_agent_tasks_dir / task_id
        if not d.exists():
            raise FileNotFoundError(f"任务目录不存在：{d}")
        return d
    latest = find_latest_active_task()
    if not latest:
        raise RuntimeError("没有找到活跃中的任务，请先运行 task-agent run")
    return latest

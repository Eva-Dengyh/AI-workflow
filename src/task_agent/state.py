import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class TaskState(str, Enum):
    INIT            = "INIT"
    ARCHITECT       = "ARCHITECT"
    ARCHITECT_DONE  = "ARCHITECT_DONE"
    DEV_RED         = "DEV_RED"
    DEV_RED_DONE    = "DEV_RED_DONE"
    DEV_GREEN       = "DEV_GREEN"
    DEV_GREEN_DONE  = "DEV_GREEN_DONE"
    DEV_REFACTOR    = "DEV_REFACTOR"
    DEV_DONE        = "DEV_DONE"
    REVIEW          = "REVIEW"
    REVIEW_FAILED   = "REVIEW_FAILED"
    DONE            = "DONE"
    PAUSED          = "PAUSED"
    ERROR           = "ERROR"


@dataclass
class TestRun:
    timestamp: str
    phase: str
    passed: int
    failed: int
    errors: int
    output_path: str


@dataclass
class DevPhaseData:
    started_at: str = ""
    current_phase: str = "RED"
    retry_count: int = 0
    max_retries: int = 5
    test_runs: list[TestRun] = field(default_factory=list)


@dataclass
class ArchitectPhaseData:
    started_at: str = ""
    completed_at: str = ""
    conversation_turns: int = 0
    contract_path: str = "contract.md"
    user_confirmed: bool = False


@dataclass
class TaskContext:
    task_id: str
    task_description: str
    state: TaskState = TaskState.INIT
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    architect: ArchitectPhaseData = field(default_factory=ArchitectPhaseData)
    dev: DevPhaseData = field(default_factory=DevPhaseData)
    review: dict = field(default_factory=dict)
    paused_reason: str | None = None
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_file(task_dir: Path) -> Path:
    return task_dir / "state.json"


def load_state(task_dir: Path) -> TaskContext:
    sf = _state_file(task_dir)
    if not sf.exists():
        raise FileNotFoundError(f"state.json not found in {task_dir}")
    data = json.loads(sf.read_text(encoding="utf-8"))
    data["state"] = TaskState(data["state"])
    ctx = TaskContext(**{k: v for k, v in data.items()
                         if k not in ("architect", "dev", "review")})
    ctx.architect = ArchitectPhaseData(**data.get("architect", {}))
    dev_raw = data.get("dev", {})
    ctx.dev = DevPhaseData(
        started_at=dev_raw.get("started_at", ""),
        current_phase=dev_raw.get("current_phase", "RED"),
        retry_count=dev_raw.get("retry_count", 0),
        max_retries=dev_raw.get("max_retries", 5),
        test_runs=[TestRun(**r) for r in dev_raw.get("test_runs", [])],
    )
    ctx.review = data.get("review", {})
    return ctx


def save_state(ctx: TaskContext, task_dir: Path) -> None:
    ctx.updated_at = _now()
    data = asdict(ctx)
    data["state"] = ctx.state.value
    _state_file(task_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def new_context(task_id: str, description: str) -> TaskContext:
    return TaskContext(task_id=task_id, task_description=description)

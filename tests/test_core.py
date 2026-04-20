"""核心模块的基础测试"""

import json
from pathlib import Path

import pytest


def test_settings_load(tmp_path, monkeypatch):
    """Settings 能从环境变量加载"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TASK_AGENT_TASKS_DIR", str(tmp_path))
    # 重新加载 settings（避免模块级缓存影响）
    import importlib
    import task_agent.settings as s_mod
    importlib.reload(s_mod)
    assert s_mod.settings.anthropic_api_key == "test-key"


def test_state_save_and_load(tmp_path):
    """state.json 能正确序列化和反序列化"""
    from task_agent.state import TaskState, new_context, save_state, load_state

    ctx = new_context("test-task", "测试任务描述")
    ctx.state = TaskState.DEV_RED
    save_state(ctx, tmp_path)

    loaded = load_state(tmp_path)
    assert loaded.task_id == "test-task"
    assert loaded.state == TaskState.DEV_RED
    assert loaded.task_description == "测试任务描述"


def test_task_dir_creation(tmp_path, monkeypatch):
    """任务目录正确创建子目录"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TASK_AGENT_TASKS_DIR", str(tmp_path))
    import importlib
    import task_agent.settings as s_mod
    importlib.reload(s_mod)

    from task_agent.utils import task_dir as td_mod
    importlib.reload(td_mod)

    task_dir = td_mod.create_task_dir("2026-04-20_test")
    assert (task_dir / "src").exists()
    assert (task_dir / "tests").exists()
    assert (task_dir / "test_results").exists()


def test_parse_agent_files():
    """文件解析器正确提取多文件"""
    from task_agent.utils.file_writer import parse_agent_files

    response = """\
=== FILE: src/service.py ===
def hello():
    return "world"
=== END FILE ===

=== FILE: tests/test_service.py ===
def test_hello():
    assert True
=== END FILE ===
"""
    result = parse_agent_files(response)
    assert "src/service.py" in result
    assert "tests/test_service.py" in result
    assert 'def hello():' in result["src/service.py"]


def test_contract_validator_passes():
    """有效契约通过校验"""
    from task_agent.utils.contract_validator import validate

    contract = """
## 1. 任务背景
背景内容

## 2. 核心业务数据流
数据流

## 3. 接口规范
接口

## 4. 异常场景与期望行为

| # | 场景 | 触发条件 | 期望行为 | 监控 |
|---|------|----------|----------|------|
| 1 | 超时 | 响应>3s | 降级 | cnt |
| 2 | 重复 | 相同ID | 幂等 | cnt |
| 3 | 断网 | 无网络 | 失败 | cnt |

## 5. 非功能性要求
要求

## 6. 开发检查清单
清单
"""
    errors = validate(contract)
    assert errors == []


def test_runner_parse_output():
    """pytest 输出解析正确"""
    from task_agent.runner import TestRunner

    output = """\
FAILED tests/test_foo.py::test_a - AssertionError
FAILED tests/test_foo.py::test_b - AssertionError
3 passed, 2 failed in 0.31s
"""
    result = TestRunner._parse_output(output)
    assert result.passed == 3
    assert result.failed == 2
    assert len(result.failed_tests) == 2

"""中转站连通性诊断"""

import httpx
from rich.console import Console

from task_agent.settings import settings

console = Console()

CANDIDATE_MODELS = [
    settings.task_agent_model,
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]


def _make_headers(auth_style: str) -> dict:
    key = settings.anthropic_api_key
    ver = settings.claude_code_version
    base = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "User-Agent": f"claude-code/{ver}",
    }
    if auth_style == "bearer":
        base["Authorization"] = f"Bearer {key}"
    else:
        base["x-api-key"] = key
    return base


def _test_model(model: str, headers: dict) -> tuple[bool, str]:
    base = (settings.anthropic_base_url or "https://api.anthropic.com").rstrip("/")
    payload = {
        "model": model,
        "max_tokens": 30,
        "messages": [{"role": "user", "content": "reply with: ok"}],
    }
    try:
        r = httpx.post(f"{base}/v1/messages", headers=headers, json=payload, timeout=15)
        body = r.text
        if r.status_code == 200 and '"type":"message"' in body or '"content"' in body:
            return True, body[:120]
        return False, f"HTTP {r.status_code}: {body[:200]}"
    except Exception as e:
        return False, str(e)


def run_diagnosis() -> None:
    base = (settings.anthropic_base_url or "https://api.anthropic.com").rstrip("/")
    console.print(f"\n[bold cyan]🔍 中转站诊断[/bold cyan]")
    console.print(f"  URL  : {base}/v1/messages")
    console.print(f"  UA   : claude-code/{settings.claude_code_version}\n")

    # Step 1: 确认正确的认证方式
    working_auth = None
    for style in ("bearer", "x-api-key"):
        console.print(f"[dim]▶ 认证方式：{style}[/dim]")
        headers = _make_headers(style)
        # 用当前配置的模型快速探测
        ok, msg = _test_model(settings.task_agent_model, headers)
        if ok:
            console.print(f"  [green]✅ 认证成功[/green]")
            working_auth = style
            break
        # 422 missing authorization → 这种认证方式完全不行
        if "missing" in msg.lower() or "422" in msg:
            console.print(f"  [red]❌ 不支持[/red]  {msg[:80]}")
            continue
        # 其他错误可能是模型问题，但认证本身通了
        if "200" in msg or "error" in msg.lower():
            console.print(f"  [yellow]⚠️  认证通过但有错误（可能是模型问题）[/yellow]  {msg[:80]}")
            working_auth = style
            break
        console.print(f"  [red]❌[/red]  {msg[:80]}")

    if working_auth is None:
        console.print("\n[red]❌ 两种认证方式均失败，请检查 API Key 和 BASE_URL[/red]")
        return

    console.print(f"\n[green]✅ 认证方式：{working_auth}[/green]")

    # Step 2: 找到可用的模型名
    console.print(f"\n[dim]▶ 测试可用模型...[/dim]")
    headers = _make_headers(working_auth)
    found_model = None
    for model in CANDIDATE_MODELS:
        ok, msg = _test_model(model, headers)
        if ok:
            console.print(f"  [green]✅ {model}[/green]")
            found_model = model
            break
        else:
            console.print(f"  [red]❌ {model}[/red]  {msg[:80]}")

    # 结论
    console.print()
    if found_model:
        console.print(Panel(
            f"认证方式：[bold]{working_auth}[/bold]\n"
            f"可用模型：[bold]{found_model}[/bold]\n\n"
            + (
                f"[yellow]→ 请在 .env 设置：TASK_AGENT_MODEL={found_model}[/yellow]"
                if found_model != settings.task_agent_model else
                "[green]当前配置正确[/green]"
            ),
            title="诊断结果",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"认证方式 [bold]{working_auth}[/bold] 通过，但所有模型均失败。\n"
            "请联系中转站确认支持的模型列表。",
            title="诊断结果",
            border_style="yellow",
        ))


from rich.panel import Panel

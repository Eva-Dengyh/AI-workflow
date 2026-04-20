"""校验 contract.md 是否包含必要的章节和内容"""

REQUIRED_SECTIONS = [
    "## 1.",
    "## 2.",
    "## 3.",
    "## 4.",
    "## 5.",
    "## 6.",
]

MIN_EXCEPTION_ROWS = 3  # 异常场景表格至少 3 行


def validate(content: str) -> list[str]:
    """返回错误列表，空列表表示通过"""
    errors: list[str] = []
    for section in REQUIRED_SECTIONS:
        if section not in content:
            errors.append(f"契约文档缺少章节（含 '{section}'）")

    # 粗略统计异常场景表格行数（含 | # | 的行）
    rows = [ln for ln in content.splitlines()
            if ln.strip().startswith("|") and not ln.strip().startswith("| #") and "---" not in ln]
    exception_section_start = content.find("## 4.")
    if exception_section_start != -1:
        section_content = content[exception_section_start:]
        section_rows = [ln for ln in section_content.splitlines()
                        if ln.strip().startswith("|") and "---" not in ln
                        and not set(ln.strip("| ")).issubset({" ", ""})]
        # 减去表头行
        data_rows = max(0, len(section_rows) - 1)
        if data_rows < MIN_EXCEPTION_ROWS:
            errors.append(f"异常场景至少需要 {MIN_EXCEPTION_ROWS} 个，当前只有 {data_rows} 个")

    return errors

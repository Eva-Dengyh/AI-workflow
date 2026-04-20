# 《开发契约文档》格式规范

契约文档是本系统的核心产物，是 Developer Agent 和 Reviewer Agent 的唯一参照基准。

---

## 文件位置

```
tasks/{task_id}/contract.md
```

## 版本控制

每次修改契约时，版本号递增（v1.0 → v1.1）。
Developer Agent 和 Reviewer Agent 的调用记录中必须包含契约版本号，便于追溯。

---

## 完整格式模板

```markdown
# 开发契约文档

**任务名称**：{任务名称}
**任务 ID**：{task_id}
**版本**：v1.0
**生成时间**：{ISO 8601 时间}
**状态**：草稿 / 已确认

---

## 1. 任务背景

{用 2-4 句话描述业务背景和目标。说明为什么需要做这个，而不是做什么。}

示例：
> 用户中心系统（UC）需要将新注册用户数据实时同步到营销系统（CRM），
> 以便营销系统及时触发新用户激活流程。当前靠人工导出，延迟约 2 小时，
> 需要改为接口调用实现秒级同步。

---

## 2. 核心业务数据流

```
[来源] → [处理] → [目标]
```

示例：
```
用户中心（POST /internal/user/created 事件）
  → 用户同步服务（接收事件 → 数据校验 → 格式转换）
  → 营销系统 CRM（POST /api/crm/users）
  → 同步结果写回 MySQL sync_log 表
```

数据流要点：
- **触发方式**：{事件驱动 / 定时轮询 / 接口调用}
- **数据来源**：{系统名 + 具体表/接口}
- **数据目标**：{系统名 + 具体表/接口}
- **数据量级**：{预计 QPS / 日均量}

---

## 3. 接口规范

### 3.1 接口基本信息

| 项目 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | /api/v1/users/sync |
| 认证 | Bearer Token（内部服务间 token） |
| 内容类型 | application/json |
| 幂等性 | 是，幂等键：requestId（有效期 10min） |

### 3.2 请求格式

```json
{
  "requestId": "string, 必填, 全局唯一请求ID, UUID v4格式",
  "userId": "string, 必填, 用户中心的用户ID",
  "userInfo": {
    "nickname": "string, 必填, 用户昵称",
    "phone": "string, 必填, 手机号（脱敏传输：138****8888）",
    "registeredAt": "string, 必填, 注册时间 ISO 8601"
  },
  "sourceSystem": "string, 必填, enum: [UC, ADMIN]"
}
```

### 3.3 响应格式

**成功（200）**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "syncId": "string, 本次同步记录ID",
    "crmUserId": "string, CRM系统中的用户ID",
    "syncedAt": "string, 同步完成时间 ISO 8601"
  }
}
```

**参数错误（422）**：
```json
{
  "code": 4220,
  "message": "参数校验失败",
  "data": {
    "field": "userId",
    "reason": "不能为空"
  }
}
```

**幂等重复（200，返回首次结果）**：
```json
{
  "code": 0,
  "message": "success (idempotent)",
  "data": {
    "syncId": "首次同步的 syncId",
    "crmUserId": "首次同步的 crmUserId",
    "syncedAt": "首次同步时间"
  }
}
```

**服务降级（200，返回降级响应）**：
```json
{
  "code": 2001,
  "message": "CRM服务暂时不可用，已加入重试队列",
  "data": {
    "retryId": "string, 重试任务ID",
    "estimatedRetryAt": "string, 预计重试时间"
  }
}
```

**系统错误（500，非正常情况）**：
```json
{
  "code": 5000,
  "message": "内部错误",
  "data": null
}
```

### 3.4 错误码枚举

| 错误码 | 含义 | HTTP 状态码 |
|--------|------|-------------|
| 0      | 成功 | 200 |
| 2001   | CRM 服务降级 | 200 |
| 4001   | requestId 格式错误 | 422 |
| 4220   | 参数校验失败 | 422 |
| 4030   | 认证失败 | 401 |
| 5000   | 内部错误 | 500 |

---

## 4. 异常场景与期望行为

| # | 场景 | 触发条件 | 期望行为 | 监控指标 |
|---|------|----------|----------|----------|
| 1 | CRM 接口超时 | CRM 响应 > 3s | 返回降级响应（code=2001），将任务加入 Redis 重试队列，记录 WARNING 日志 | crm_timeout_count |
| 2 | 重复请求（幂等） | 相同 requestId 在 10min 内再次请求 | 直接返回首次成功响应，不重复调用 CRM | idempotent_hit_count |
| 3 | 并发写入同一用户 | 同一 userId 100ms 内收到 2 个请求 | 分布式锁保证只有一个请求写入 CRM，另一个等待后返回幂等结果 | concurrent_lock_count |
| 4 | CRM 完全不可用 | CRM 连续 5 次超时 | 触发熔断，后续请求直接返回降级响应，不再尝试 CRM | circuit_breaker_open |
| 5 | 手机号格式异常 | phone 字段不符合脱敏格式 | 返回 4220 参数错误，不调用 CRM | validation_error_count |

---

## 5. 非功能性要求

| 项目 | 要求 |
|------|------|
| 响应时间 P99 | < 500ms（正常情况）/ < 100ms（降级情况） |
| 并发量 | 100 QPS |
| 可用性 | 99.9%（允许降级，不允许报错） |
| CRM 调用超时 | 3s |
| 整体接口超时 | 5s |
| 重试策略 | 指数退避，最多 3 次，retry 间隔：1s/2s/4s |
| 日志要求 | requestId 全链路贯穿；关键节点 INFO；异常 ERROR + 完整堆栈 |
| 数据安全 | 手机号不得在日志中明文记录 |

---

## 6. 开发检查清单

**Reviewer Agent 将逐项核查以下内容：**

- [ ] 所有请求字段均有类型和必填校验
- [ ] 响应结构与本文档第 3.3 节完全一致（字段名区分大小写）
- [ ] 幂等键 requestId 的有效期实现（10min TTL）
- [ ] CRM 调用设置 timeout=3s，且 timeout 来自配置，非硬编码
- [ ] 重试使用指数退避（tenacity 库或等效实现）
- [ ] 重试区分可重试错误（TimeoutError, ConnectionError）和不可重试错误（4xx）
- [ ] CRM 不可用时有明确的降级响应（非 500）
- [ ] 日志包含 requestId，且不记录明文手机号
- [ ] 异常日志使用 exc_info=True 记录完整堆栈
- [ ] 单元测试覆盖第 4 节所有 5 个异常场景

---

## 7. 变更记录

| 版本 | 时间 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-04-20 10:15 | 初始版本 |
```

---

## 格式校验规则

Workflow Engine 在 Architect Agent 完成后，对 contract.md 进行自动校验：

```python
REQUIRED_SECTIONS = [
    "## 1. 任务背景",
    "## 2. 核心业务数据流",
    "## 3. 接口规范",
    "### 3.2 请求格式",
    "### 3.3 响应格式",
    "## 4. 异常场景与期望行为",
    "## 5. 非功能性要求",
    "## 6. 开发检查清单",
]

REQUIRED_EXCEPTION_COUNT = 3  # 最少 3 个异常场景

def validate_contract(content: str) -> list[str]:
    """返回缺失项列表，空列表表示通过"""
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in content:
            errors.append(f"缺少章节：{section}")
    # 检查异常场景表格行数
    ...
    return errors
```

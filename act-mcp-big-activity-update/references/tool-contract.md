# act-mcp 编辑大活动 —— 接口契约

## 1. 读取当前值

MCP：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_big_activity","arguments":{"id":9}}}
```

REST：

```
GET /api/big-activities/9
```

只读资源（MCP 支持资源时）：

```
resources/read → activity://big-activities/9
```

返回对象字段：`id`、`name`、`actType`、`startTime`、`endTime`、`audienceScope`、`budget`、`collectionDiscountJson`、`createdBy`、`createdAt`、`updatedBy`、`updatedAt`、`productCount`。

## 2. 提交更新

### 2.1 MCP（支持部分更新）

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "update_big_activity",
    "arguments": {
      "id": 9,
      "endTime": "2026-09-01T23:59",
      "budget": 2000,
      "operator": "mcp-agent"
    }
  }
}
```

只传需要修改的字段；服务端用库中现存值补齐其余字段，再按合并后的完整对象校验。
成功返回更新后的 `BigActivity`（含刷新后的 `updatedBy` / `updatedAt` 与 `productCount`）。

### 2.2 REST（要求完整请求体）

```
PUT /api/big-activities
Content-Type: application/json
```

```json
{
  "id": 9,
  "name": "中秋节4",
  "actType": 2,
  "startTime": "2026-08-20T00:00",
  "endTime": "2026-09-01T23:59",
  "audienceScope": "ALL",
  "budget": 2000,
  "collectionDiscountJson": "{}",
  "operator": "mcp-agent"
}
```

差异要点：REST 的 `PUT` 不接受部分字段（`@Valid` 要求必填字段齐全），必须用当前值补齐未修改字段；MCP 工具则支持部分更新。

## 3. 校验更新结果

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"get_big_activity","arguments":{"id":9}}}
```

逐项核对：

- 修改字段 = 预览中的“修改后”；
- 未修改字段 = 原值；
- `updatedBy` = 本次 `operator`，`updatedAt` 已刷新；
- `productCount` 不因本次编辑变化。

## 4. HITL 通道

### 4.1 MCP elicitation（支持时优先）

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "确认修改大活动 中秋节4（ID 9）？结束时间 2026-08-25 23:59 → 2026-09-01 23:59，预算 1212 → 2000。",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "confirm": {"type": "boolean", "title": "确认修改", "default": false}
      },
      "required": ["confirm"]
    }
  }
}
```

未返回 `confirm = true` 视为取消。

### 4.2 文本确认（通用回退）

同时满足：

1. 出现在差异预览之后的新一轮消息；
2. 含明确修改语义（确认修改 / 确认更新 / yes, update）；
3. 指向预览过的目标（名称或 ID 至少一项）。

## 5. 错误映射

| 返回 | 含义 | 处理 |
| --- | --- | --- |
| `大活动不存在：<id>` / HTTP 404 | 目标不存在或已被删除 | 不重试，询问是否选错目标 |
| `大活动 id 不能为空` | 未传 ID | 回到目标解析 |
| `结束时间必须晚于开始时间` | 合并后时间区间非法 | 指出与当前另一侧时间的冲突，请用户调整 |
| `活动名称不能为空` / `不能超过 100 个字符` | 名称非法 | 请用户修正 |
| `活动类型必须是 1-5 的整数` | 类型非法 | 用映射表转换 |
| `活动人群只能是 ALL（所有用户）或 NEW（新客）` | 人群非法 | 映射“全部/新客” |
| `预算不能小于 0` / `预算最多 12 位整数和 2 位小数` | 预算非法 | 请用户修正 |
| `集合优惠 JSON 不是合法的 JSON` | JSON 语法错误 | 修正或传 `{}` |
| `操作人名称不能超过 50 个字符` | operator 过长 | 缩短 |
| 无权限 / 401 / 403 | 无权限 | 如实反馈，不绕过 |
| HTTP 500 | 未预期错误 | 说明未发生部分更新，建议重试 |

## 6. 行为边界

- 编辑大活动**不会**修改已有商品活动的 `actType`。商品活动在创建时已固化自己的类型，修改大活动类型不会级联。
- 编辑不会增删商品活动；需要增删请使用 `create_product_activity` / `delete_product_activity`。
- 删除大活动是独立操作，走删除 skill（带 HITL）。
- `collectionDiscountJson` 传空字符串会被归一化为 `{}`。
- 时间为分钟精度：`yyyy-MM-ddTHH:mm`，库中以 `yyyy-MM-dd HH:mm:ss` 存储。

# act-mcp 组合创建 —— 接口契约与错误映射

## 1. MCP 报文

### 1.1 发现工具

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

确认存在 `create_big_activity_with_products`。

### 1.2 读取 Schema 资源（可选）

```json
{"jsonrpc":"2.0","id":2,"method":"resources/read",
 "params":{"uri":"activity://schemas/create-big-activity-with-products"}}
```

资源内容为 JSON Schema 2020-12，重点节点：

- `properties`：扁平入参约束（对应工具参数）
- `$defs.productActivityItem`：`productActivitiesJson` 数组条目的结构
- `x-form`：表单渲染提示
- `x-business-rules`：跨字段规则
- `examples`：可直接调用的完整入参

### 1.3 调用（确认预览之后）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "create_big_activity_with_products",
    "arguments": {
      "name": "中秋节4",
      "actType": 2,
      "startTime": "2026-08-20T00:00",
      "endTime": "2026-08-25T23:59",
      "audienceScope": "ALL",
      "budget": 1212,
      "collectionDiscountJson": "{}",
      "productActivitiesJson": "[{\"poiId\":\"10003\",\"skuId\":\"3333\",\"upc\":\"xxxx33\",\"productDiscountJson\":\"{\\\"price\\\":0.7}\"}]",
      "operator": "mcp-agent"
    }
  }
}
```

注意：

| 容易错的地方 | 正确做法 |
| --- | --- |
| `productActivitiesJson` 传数组 | 传 **JSON 数组的字符串** |
| 工具参数包一层 `bigActivity` | MCP 工具参数是**扁平**的 |
| `poiId` 传数字 | 传字符串（64 位精度） |
| `budget` 传字符串 | 传数字 |
| 商品条目带 `actId` / `actType` | 不传，服务端自动绑定/继承 |

### 1.4 返回结构

```json
{
  "bigActivity": {
    "id": 9, "name": "中秋节4", "actType": 2,
    "startTime": "2026-08-20 00:00:00", "endTime": "2026-08-25 23:59:00",
    "audienceScope": "ALL", "budget": 1212, "collectionDiscountJson": "{}",
    "createdBy": "mcp-agent", "createdAt": "...", "updatedBy": "mcp-agent",
    "updatedAt": "...", "productCount": 1
  },
  "productActivities": [
    {
      "id": 14, "actId": 9, "actName": "中秋节4", "actType": 2,
      "poiId": "10003", "skuId": "3333", "upc": "xxxx33",
      "productDiscountJson": "{\"price\":0.7}",
      "createdBy": "mcp-agent", "createdAt": "...", "updatedBy": "mcp-agent", "updatedAt": "..."
    }
  ]
}
```

## 2. HITL 确认（调用前置条件）

调用 `create_big_activity_with_products` 前必须完成一次预览确认，且确认发生在预览之后的独立一轮。

### 2.1 预览内容

至少包含：名称、类型、起止时间、人群、预算、集合优惠 JSON、操作人、商品活动条数与逐条明细，以及“整体事务、失败回滚”的说明。

### 2.2 MCP elicitation（支持时优先）

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "确认创建大活动 中秋节4？包含 1 个商品活动，整体事务创建。",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "confirm": {"type": "boolean", "title": "确认创建", "default": false}
      },
      "required": ["confirm"]
    }
  }
}
```

未返回 `confirm = true` 视为取消。

### 2.3 文本确认（通用回退）

同时满足：

1. 出现在预览之后的用户消息；
2. 含明确的创建确认语义（确认创建 / yes, create）；
3. 目标与预览一致（活动名称）。

仅“好”“可以”“嗯”不满足条件。确认时附带参数修改的，按新参数重新预览并重新确认。

## 3. REST 回退（无 MCP 时）

```
POST /api/big-activities/with-products
Content-Type: application/json
```

报文是**嵌套结构**，与 MCP 的扁平参数不同：

```json
{
  "bigActivity": {
    "name": "中秋节4",
    "actType": 2,
    "startTime": "2026-08-20T00:00",
    "endTime": "2026-08-25T23:59",
    "audienceScope": "ALL",
    "budget": 1212,
    "collectionDiscountJson": "{\"price\":0.7}",
    "operator": "mcp-agent"
  },
  "productActivities": [
    {"poiId": "10003", "skuId": "3333", "upc": "xxxx33",
     "productDiscountJson": "{\"price\":0.7}"}
  ]
}
```

成功返回 `201` 与同样的 `{bigActivity, productActivities}` 结构；校验失败返回 `400`，错误体形如：

```json
{"message": "结束时间必须晚于开始时间"}
{"fieldErrors": {"productActivities[1].poiId": "POI ID 不能为空"}}
```

## 4. 常见错误 → 修复动作

| 服务端错误 | 原因 | 修复 |
| --- | --- | --- |
| `活动名称不能为空` | `name` 缺失/空白 | 追问活动名称 |
| `活动名称不能超过 100 个字符` | 名称过长 | 请用户缩短 |
| `活动类型不能为空` / `活动类型必须是 1-5 的整数` | 未给或不在枚举 | 用中文映射表转换 |
| `开始时间不能为空` / `结束时间不能为空` | 缺时间 | 追问，按 `yyyy-MM-ddTHH:mm` |
| `结束时间必须晚于开始时间` | 区间颠倒 | 指出冲突，请用户给出新的结束时间 |
| `活动人群只能是 ALL（所有用户）或 NEW（新客）` | 人群值非法 | 映射“全部/新客” |
| `预算不能为空` / `预算不能小于 0` / `预算最多 12 位整数和 2 位小数` | 预算缺失或超范围 | 请用户修正 |
| `集合优惠 JSON 不是合法的 JSON` | JSON 字符串语法错误 | 修正 JSON 或省略用 `{}` |
| `商品活动列表不能为空` | `productActivitiesJson` 为空 | 至少收集 1 条商品 |
| `商品活动列表不是合法的 JSON 数组` | 传了对象或非法 JSON | 传 JSON 数组字符串 |
| `至少需要创建一个商品活动` | 数组为空 | 追问商品列表 |
| `POI ID 不能为空` / `POI ID 必须是有效的 64 位整数` | 条目缺 POI 或非法 | 追问门店 ID |
| `SKU ID 必须是有效的 64 位整数` | SKU 非数字 | 修正或省略 |
| `UPC 不能超过 64 个字符` | UPC 过长 | 请用户缩短 |
| `操作人名称不能超过 50 个字符` | operator 过长 | 缩短操作人 |

成功与否都以服务端返回为准；这些文案用于把错误翻译成用户能执行的下一步。

## 5. 字段映射速查

```
actType:     1 满减 | 2 折扣 | 3 秒杀 | 4 优惠券 | 5 组合优惠
audience:    ALL 所有用户 | NEW 新客
time:        yyyy-MM-ddTHH:mm（服务端也接受 yyyy-MM-dd HH:mm[:ss]）
budget:      单位元，≥0，≤ 999999999999.99，2 位小数
poiId/skuId: 64 位正整数，字符串传递
operator:    ≤50 字符，默认 mcp-agent
```

`actType` 由大活动决定，商品活动自动继承；`actId` 由服务端自动指向新建的大活动。

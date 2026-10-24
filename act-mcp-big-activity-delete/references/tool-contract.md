# act-mcp 删除大活动 —— 接口契约

## 1. 目标解析

### 1.1 按 ID 读取

MCP：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_big_activity","arguments":{"id":9}}}
```

REST：

```
GET /api/big-activities/9
```

### 1.2 按名称搜索

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call",
 "params":{"name":"list_big_activities",
           "arguments":{"page":1,"size":20,"keyword":"中秋节"}}}
```

返回 `PageResult`，每项含 `id`、`name`、`actType`、`startTime`、`endTime`、`audienceScope`、`productCount`。

REST：

```
GET /api/big-activities?page=1&size=20&keyword=中秋节
```

### 1.3 只读资源（可选）

客户端支持 MCP 资源时，可直接读取：

```
resources/read → activity://big-activities/9
```

内容字段与 `get_big_activity` 一致。

## 2. 删除

MCP：

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"delete_big_activity","arguments":{"id":9}}}
```

成功返回：

```json
{"success": true, "message": "大活动及其关联商品活动已删除", "id": 9}
```

REST：

```
DELETE /api/big-activities/9
```

成功：`204 No Content`，无响应体。

服务端行为：同一事务内先删除该 `actId` 下的商品活动，再删除大活动。任一步失败整体回滚。

## 3. 校验删除结果

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call",
 "params":{"name":"get_big_activity","arguments":{"id":9}}}
```

预期错误：`大活动不存在：9`（REST `404`，响应体 `{"message":"大活动不存在：9"}`）。

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call",
 "params":{"name":"list_product_activities","arguments":{"actId":9}}}
```

预期 `total = 0`。

## 4. 错误映射

| 返回 | 含义 | 处理 |
| --- | --- | --- |
| `大活动不存在：<id>` / HTTP 404 | 目标已被删除或 ID 错误 | 报告，不重试删除；询问是否选错目标 |
| `大活动 id 不能为空` | 未传 ID | 回到目标解析，不要用名称直接删 |
| `商品活动不存在：<id>` | 误用了商品活动 ID | 确认用户是否想删商品活动，改用 `delete_product_activity` |
| HTTP 409 / 数据冲突 | 关联数据约束冲突 | 说明删除失败且已回滚，建议先检查关联数据 |
| HTTP 500 / 服务端异常 | 未预期错误 | 说明删除未成功，建议稍后重试；不要声称已删除 |
| 无权限 / 401 / 403 | 调用方无权限 | 如实反馈，不尝试绕过 |

## 5. HITL 通道

### 5.1 MCP elicitation（支持时优先）

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "确认删除大活动 中秋节4（ID 9）？将级联删除 1 个商品活动，且不可恢复。",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "confirm": {"type": "boolean", "title": "确认删除", "default": false}
      },
      "required": ["confirm"]
    }
  }
}
```

只有返回 `confirm = true` 才继续；拒绝、超时、字段缺失都按取消处理。

### 5.2 文本确认（通用回退）

必须满足全部条件：

1. 发生在预览之后的新一轮用户消息；
2. 包含明确的删除确认语义（确认删除 / 确认 / yes, delete）；
3. 引用的目标与预览一致（名称或 ID 至少一项）。

仅“好”“可以”“嗯”不满足条件。

## 6. 边界

- 本契约只覆盖大活动删除；商品活动删除使用 `delete_product_activity`，接口为 `DELETE /api/product-activities/{id}`。
- 删除接口无软删除、无回收站；任何成功响应都意味着数据已从库中移除。
- `delete_big_activity` 的 `id` 是数字；名称必须先解析为 ID。

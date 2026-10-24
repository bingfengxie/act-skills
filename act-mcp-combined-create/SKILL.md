---
name: act-mcp-combined-create
description: 通过 act-mcp 组合创建活动（一次创建 1 个大活动 + 多个商品活动），并强制经过人工确认（HITL）。当用户说「组合创建活动」「组合新建」「一次性创建活动」「创建大活动和商品」「create big activity with products」「bundled activity creation」时使用。即使用户没有明确说“组合”，只要一次请求同时包含大活动字段和商品列表，也应触发。即使参数齐全，也先预览完整入参、等待明确确认后再创建。DO NOT trigger for 仅创建单个大活动（用 create_big_activity）、给已有大活动追加商品（用 create_product_activity）、查询/更新/删除活动。
---

# 组合创建活动（act-mcp）

把用户口述的活动信息转换为一次原子写入：1 个大活动 + 至少 1 个商品活动。

成功标准：

1. 选对工具，不拆成多次调用；
2. 参数完整、规范，跨字段规则通过；
3. 缺参数时逐轮引导，不重复追问已提供的信息；
4. 写入前展示完整入参，并在独立一轮等待明确确认（HITL）；
5. 调用后用固定结构回显大活动与商品活动结果。

本 skill 不依赖 Claude 专有能力：优先走 MCP，任何 MCP 客户端都可执行；没有 MCP 的 agent 走 REST 回退（见 `references/tool-contract.md`）。

## 状态机

```
收集参数 → 规范化/校验 → 预览（HITL，结束本轮） → 等待用户
                                              ├─ 明确确认 → 调用 → 校验/回显
                                              ├─ 取消/含糊 → 中止或追问一次
                                              └─ 改参数   → 重新校验并预览
```

硬性规则：

- **创建意图不等于创建批准。** 用户说“组合创建活动”只是发起请求。
- **预览与调用不能发生在同一轮。** 发出预览后必须结束回复。
- **批准必须发生在预览之后。** 预览前说过的“直接建”“不用确认”不能当作批准。
- 用户补充或修改参数时，重新校验并重新预览，不复用旧批准。
- 即使用户要求“直接创建，不用确认”，也要完成一次预览 + 明确确认。

## 第 0 步：选择工具

| 用户意图 | 工具 |
| --- | --- |
| 一次创建 1 个大活动 + N 个商品活动 | `create_big_activity_with_products`（本 skill） |
| 只创建大活动 | `create_big_activity` |
| 给已存在的大活动追加商品 | `create_product_activity`（需 `actId`） |
| 查询 / 更新 / 删除 | 对应的 list/get/update/delete 工具 |

用户没有给出 `actId`、且明确要“新活动 + 商品”时，选择组合创建。组合创建在单个事务内完成，失败整体回滚，不会留下孤立大活动，所以只要一次请求同时含大活动和商品，优先用它。

调用前确认工具可用：MCP 客户端先 `tools/list`，存在 `create_big_activity_with_products` 再继续；不存在时改用 REST 回退或告知用户。

## 第 1 步：获取权威 Schema（有资源能力时）

若客户端支持 MCP 资源，先读取：

```
resources/read → activity://schemas/create-big-activity-with-products
```

该资源是 JSON Schema 2020-12，含字段约束、枚举、商品条目结构（`$defs.productActivityItem`）、表单描述（`x-form`）与示例。

客户端不支持资源时，直接使用下文字段表和 `references/tool-contract.md`，规则一致。

## 第 2 步：建立参数草稿，增量合并

维护一份草稿，每收到一条用户消息就合并进去，然后：

1. 回显“已记录”的字段（让用户看到没有丢信息）；
2. 只列出仍然缺失的必填项，编号 + 格式示例；
3. 立即做跨字段校验（如结束时间早于开始时间，当场指出，不等全部收齐）。

不要重复追问已经提供过的字段；不要把草稿丢掉重新开始。用户说“只创建商品1”时，按用户裁剪商品列表，而不是继续追问商品2。

### 字段与校验

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `name` | 是 | 去空格后 1–100 字符 |
| `actType` | 是 | 整数 1–5，见映射表 |
| `startTime` | 是 | 规范化为 `yyyy-MM-ddTHH:mm` |
| `endTime` | 是 | 规范化同上，且必须晚于 `startTime` |
| `audienceScope` | 是 | `ALL` / `NEW`，见映射表 |
| `budget` | 是 | ≥ 0，最多 12 位整数 + 2 位小数，单位元 |
| `collectionDiscountJson` | 否 | 合法 JSON，缺省 `{}` |
| `productActivities` | 是 | 至少 1 条，条目见下 |
| `operator` | 否 | ≤ 50 字符，缺省 `mcp-agent` |

商品活动条目：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `poiId` | 是 | 64 位正整数，用字符串传递避免精度丢失 |
| `skuId` | 否 | 64 位正整数，用字符串传递 |
| `upc` | 否 | ≤ 64 字符 |
| `productDiscountJson` | 否 | 合法 JSON，缺省 `{}` |

条目不接受 `actId` / `actType`：所属大活动和类型由服务端自动绑定/继承。用户填了也要忽略并说明。

### 中文值映射

| 用户说法 | 规范化值 |
| --- | --- |
| 满减、满减活动 | `actType = 1` |
| 折扣、折扣活动 | `actType = 2` |
| 秒杀、秒杀活动 | `actType = 3` |
| 优惠券、优惠券活动 | `actType = 4` |
| 组合、组合优惠、叠加 | `actType = 5` |
| 全部、所有用户、全量、ALL | `audienceScope = "ALL"` |
| 新客、仅新客、新人、NEW | `audienceScope = "NEW"` |

### 时间规范化

接受 `2026-8-10 00:00`、`2026-08-10T00:00`、`2026-08-10 00:00:00`、`2026/8/10 00:00` 等写法，统一补零输出为 `2026-08-10T00:00`。规范化属于机械转换，不需要为补零单独向用户确认；但若用户给的秒数非 0，需说明按分钟精度提交。

## 第 3 步：确定性校验

优先运行脚本（Python 3 标准库，`-I` 隔离执行，不加载本地模块）：

```bash
python3 -I scripts/validate_request.py draft.json
# 或从 stdin
cat draft.json | python3 -I scripts/validate_request.py -
```

草稿格式：

```json
{
  "name": "中秋节4",
  "actType": "折扣",
  "startTime": "2026-8-20 00:00",
  "endTime": "2026-8-25 23:59",
  "audienceScope": "全部",
  "budget": 1212,
  "productActivities": [
    {"poiId": "10003", "skuId": "3333", "upc": "xxxx33", "productDiscountJson": {"price": 0.7}}
  ]
}
```

脚本输出 JSON：`ok`、`missing`、`errors`、`warnings`、`normalized`、`tool_arguments`。

- `ok = false`：把 `missing` 作为缺失项继续引导，把 `errors` 告诉用户并请求修正；不要调用工具。
- `ok = true`：用 `tool_arguments` 生成预览，确认后再原样调用。`warnings` 里的规范化说明可以顺手告诉用户。

脚本不可用时，按第 2 步的字段表逐项人工核对，规则完全相同。脚本只是把校验变成确定性的，不能替代与用户的沟通。

## 第 4 步：预览并请求确认（HITL）

校验通过后，输出完整预览卡片并结束本轮：

```markdown
即将创建以下活动，请确认：

**大活动**

| 字段 | 值 |
| --- | --- |
| 名称 | 中秋节4 |
| 活动类型 | 2（折扣） |
| 开始时间 | 2026-08-20T00:00 |
| 结束时间 | 2026-08-25T23:59 |
| 活动人群 | ALL（所有用户） |
| 预算 | 1212 元 |
| 集合优惠 JSON | {} |
| 操作人 | mcp-agent |

**商品活动（1 条）**

| # | POI | SKU | UPC | 商品优惠 |
| --- | --- | --- | --- | --- |
| 1 | 10003 | 3333 | xxxx33 | `{"price":0.7}` |

大活动与商品活动将在同一事务内创建，任一失败整体回滚。

确认请回复：**确认创建 中秋节4**
回复其他内容将取消本次操作。
```

要求：

- 展示**规范化后的最终值**（时间、枚举、预算），不要展示用户的原始口语；
- 商品列表逐条展示并标注条数，不要只写“若干商品”；
- 缺省值也展示（如 `collectionDiscountJson = {}`、`operator = mcp-agent`）；
- 商品列表为空或必填项缺失时，不进入预览；
- 用户只问“怎么创建 / 演示一下”时，只展示预览或报文，不调用工具。

客户端支持 MCP elicitation 时，优先用布尔表单确认（模板见 `references/tool-contract.md`）；不支持时用上面的文本卡片。

### 什么算明确确认

- ✅ “确认创建 中秋节4”
- ✅ “确认创建”
- ✅ “yes, create it”
- ❌ “好”“嗯”“可以”“行”
- ❌ “看着办”“你决定”

含糊回复只追问一次：请回复“确认创建 <名称>”或“取消”。

### 取消与改口

- “取消”“先不建了” → 明确告知未创建任何数据，停止。
- 用户补充或修改参数 → 回到第 2 步合并，重新校验并重新预览。
- 用户修改活动名称 → 预览与确认语随之更新，旧批准失效。

## 第 5 步：调用工具

MCP 调用（工具参数是扁平的，**不要**包一层 `bigActivity`）：

```
tools/call {
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
```

关键点：

- `productActivitiesJson` 是**字符串**，内容是一个 JSON 数组，不是数组本身；这是最常见的调用错误。
- `poiId` / `skuId` 用字符串，避免超过 `Number.MAX_SAFE_INTEGER` 后丢精度。
- 嵌套的 `productDiscountJson` 也是字符串，内部引号需要转义。用 `tool_arguments` 里的成品，不要手拼。

REST 回退（无 MCP 时）——注意 REST 请求体是**嵌套结构**且商品条目是数组：

```
POST /api/big-activities/with-products
{"bigActivity": {...}, "productActivities": [...]}
```

完整示例见 `references/tool-contract.md`。

## 第 6 步：回显结果

调用成功后固定输出两张表，再补一行事务说明：

```markdown
**大活动**

| 字段 | 值 |
| --- | --- |
| ID | 9 |
| 名称 | 中秋节4 |
| 活动类型 | 2（折扣） |
| 时间 | 2026-08-20 00:00:00 ~ 2026-08-25 23:59:00 |
| 人群 | ALL（所有用户） |
| 预算 | 1212 元 |
| 商品活动数 | 1 |
| 操作人 | mcp-agent |

**商品活动**

| ID | POI | SKU | UPC | 商品优惠 |
| --- | --- | --- | --- | --- |
| 14 | 10003 | 3333 | xxxx33 | `{"price":0.7}` |

说明：大活动与全部商品活动在同一事务内创建完成；商品活动自动继承类型并挂到 actId=9 下。
```

要求：

- 用返回值里的真实 ID、时间、操作人，不臆造；
- 多商品时逐行列出，不省略；
- 明确写出“整体事务成功”，让用户知道不存在部分成功；
- 若用户中途裁剪过商品（如“只创建商品1”），回显时确认最终条数与预期一致。

## 失败处理

- 工具返回 `isError = true` 或 HTTP 4xx：读出错误信息，映射为具体字段与修正建议，只重试修正后的调用。
- 事务回滚时明确告诉用户“没有产生任何数据”，不要让用户担心脏数据。
- 常见错误与修复对照见 `references/tool-contract.md`。

## 附加资源

- `references/tool-contract.md` — MCP/REST 完整报文、Schema 摘要、错误映射。
- `references/examples.md` — 分轮补齐、冲突指出、失败回滚、只演示不写库的对话样例。
- `scripts/validate_request.py` — 参数规范化与校验脚本（按需执行，无需读入上下文）。

#!/usr/bin/env python3
"""校验并规范化 act-mcp 组合创建活动的草稿参数。

用法：
    python3 -I validate_request.py draft.json
    cat draft.json | python3 -I validate_request.py -

草稿示例：
    {
      "name": "中秋节4",
      "actType": "折扣",
      "startTime": "2026-8-20 00:00",
      "endTime": "2026-8-25 23:59",
      "audienceScope": "全部",
      "budget": 1212,
      "productActivities": [
        {"poiId": "10003", "skuId": "3333", "upc": "xxxx33",
         "productDiscountJson": {"price": 0.7}}
      ]
    }

输出 JSON：ok / missing / errors / warnings / normalized / tool_arguments / rest_body。
退出码：0 = 可调用；1 = 缺参数或有错误；2 = 用法或读取失败。

python 3.8+，仅标准库，可用 -I 隔离运行。
"""

import json
import re
import sys
from decimal import Decimal, InvalidOperation

ACT_TYPES = {
    "1": 1, "满减": 1, "满减活动": 1,
    "2": 2, "折扣": 2, "折扣活动": 2,
    "3": 3, "秒杀": 3, "秒杀活动": 3,
    "4": 4, "优惠券": 4, "优惠券活动": 4,
    "5": 5, "组合": 5, "组合优惠": 5, "叠加": 5,
}

AUDIENCE = {
    "ALL": "ALL", "all": "ALL", "全部": "ALL", "所有用户": "ALL",
    "全部用户": "ALL", "全量": "ALL",
    "NEW": "NEW", "new": "NEW", "新客": "NEW", "仅新客": "NEW", "新人": "NEW",
}

ROOT_KEYS = {
    "name", "actType", "startTime", "endTime", "audienceScope", "budget",
    "collectionDiscountJson", "operator", "productActivities", "productActivitiesJson",
}
PRODUCT_KEYS = {"poiId", "skuId", "upc", "productDiscountJson"}
IGNORED_PRODUCT_KEYS = {"actId", "actType"}

TIME_RE = re.compile(
    r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?\s*$"
)
MAX_INT64 = 2 ** 63 - 1
MAX_BUDGET = Decimal("999999999999.99")


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_time(value, field, errors, warnings):
    match = TIME_RE.match(value)
    if not match:
        errors.append(f"{field} 格式不正确，应为 yyyy-MM-ddTHH:mm（也接受 yyyy-MM-dd HH:mm[:ss]）")
        return None
    year, month, day, hour, minute, second = match.groups()
    month, day, hour, minute = int(month), int(day), int(hour), int(minute)
    second = int(second or 0)
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        errors.append(f"{field} 不是有效的日期时间：{value}")
        return None
    normalized = f"{int(year):04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}"
    if second:
        warnings.append(f"{field} 的秒数已按分钟精度忽略：{value} → {normalized}")
    elif value.strip() != normalized:
        warnings.append(f"{field} 已规范化为 {normalized}")
    return normalized


def as_json_string(value, field, errors, warnings, default="{}"):
    if is_blank(value):
        return default
    if isinstance(value, str):
        raw = value.strip()
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{field} 不是合法的 JSON：{exc.msg}")
            return None
        return raw
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    errors.append(f"{field} 必须是 JSON 对象、数组或其字符串形式")
    return None


def normalize_id(value, field, required, errors):
    if is_blank(value):
        if required:
            errors.append(f"{field} 不能为空")
        return None
    text = str(value).strip()
    if isinstance(value, bool) or not text.isdigit():
        errors.append(f"{field} 必须是 64 位正整数")
        return None
    number = int(text)
    if number <= 0 or number > MAX_INT64:
        errors.append(f"{field} 必须是 64 位正整数")
        return None
    return str(number)


def normalize_budget(value, errors):
    try:
        budget = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append("预算必须是数字")
        return None
    if not budget.is_finite():
        errors.append("预算必须是数字")
        return None
    if budget < 0:
        errors.append("预算不能小于 0")
        return None
    if budget > MAX_BUDGET:
        errors.append("预算最多 12 位整数和 2 位小数")
        return None
    if -budget.as_tuple().exponent > 2:
        errors.append("预算最多保留 2 位小数")
        return None
    budget = budget.quantize(Decimal("0.01"))
    return int(budget) if budget == budget.to_integral_value() else float(budget)


def normalize_products(draft, errors, warnings):
    raw = draft.get("productActivities")
    if raw is None and not is_blank(draft.get("productActivitiesJson")):
        raw = draft.get("productActivitiesJson")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"productActivitiesJson 不是合法的 JSON：{exc.msg}")
                return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"productActivitiesJson 不是合法的 JSON：{exc.msg}")
            return None
    if not isinstance(raw, list) or not raw:
        if raw is None:
            return None
        errors.append("商品活动列表至少需要 1 条")
        return None

    items = []
    for index, item in enumerate(raw, start=1):
        label = f"商品{index}"
        if not isinstance(item, dict):
            errors.append(f"{label} 必须是对象")
            continue
        for key in item:
            if key in IGNORED_PRODUCT_KEYS:
                warnings.append(f"{label} 的 {key} 已忽略：由大活动自动继承/绑定")
            elif key not in PRODUCT_KEYS:
                errors.append(f"{label} 包含不支持的字段 {key}")
        poi_id = normalize_id(item.get("poiId"), f"{label}.poiId", True, errors)
        sku_id = normalize_id(item.get("skuId"), f"{label}.skuId", False, errors)
        upc = item.get("upc")
        if upc is not None and not is_blank(upc):
            upc = str(upc).strip()
            if len(upc) > 64:
                errors.append(f"{label}.upc 不能超过 64 个字符")
        else:
            upc = None
        discount = as_json_string(
            item.get("productDiscountJson"), f"{label}.productDiscountJson", errors, warnings
        )
        if poi_id is None:
            continue
        entry = {"poiId": poi_id}
        if sku_id is not None:
            entry["skuId"] = sku_id
        if upc is not None:
            entry["upc"] = upc
        entry["productDiscountJson"] = discount if discount is not None else "{}"
        items.append(entry)
    return items


def validate(draft):
    missing, errors, warnings = [], [], []
    if not isinstance(draft, dict):
        return {
            "ok": False, "missing": [], "errors": ["草稿必须是 JSON 对象"],
            "warnings": [], "normalized": None, "tool_arguments": None, "rest_body": None,
        }

    for key in draft:
        if key not in ROOT_KEYS:
            warnings.append(f"未知字段 {key} 已忽略")

    name = draft.get("name")
    if is_blank(name):
        missing.append("name")
        name = None
    else:
        name = str(name).strip()
        if len(name) > 100:
            errors.append("活动名称不能超过 100 个字符")
            name = None

    act_type = draft.get("actType")
    if is_blank(act_type):
        missing.append("actType")
        act_type = None
    else:
        normalized_type = ACT_TYPES.get(str(act_type).strip())
        if normalized_type is None:
            errors.append(f"活动类型不支持：{act_type}（应为 1-5 或 满减/折扣/秒杀/优惠券/组合）")
            act_type = None
        else:
            act_type = normalized_type

    start = draft.get("startTime")
    start_time = None
    if is_blank(start):
        missing.append("startTime")
    else:
        start_time = normalize_time(str(start), "startTime", errors, warnings)

    end = draft.get("endTime")
    end_time = None
    if is_blank(end):
        missing.append("endTime")
    else:
        end_time = normalize_time(str(end), "endTime", errors, warnings)

    if start_time and end_time and end_time <= start_time:
        errors.append("endTime 必须晚于 startTime")

    audience = draft.get("audienceScope")
    audience_scope = None
    if is_blank(audience):
        missing.append("audienceScope")
    else:
        audience_scope = AUDIENCE.get(str(audience).strip())
        if audience_scope is None:
            errors.append(f"活动人群不支持：{audience}（应为 ALL/全部 或 NEW/新客）")

    budget = draft.get("budget")
    normalized_budget = None
    if is_blank(budget):
        missing.append("budget")
    else:
        normalized_budget = normalize_budget(budget, errors)

    collection = as_json_string(
        draft.get("collectionDiscountJson"), "collectionDiscountJson", errors, warnings
    )

    operator = draft.get("operator")
    if is_blank(operator):
        operator = "mcp-agent"
    else:
        operator = str(operator).strip()
        if len(operator) > 50:
            errors.append("操作人名称不能超过 50 个字符")
            operator = None

    products = normalize_products(draft, errors, warnings)
    if products is None and not any(m == "productActivities" for m in missing):
        if is_blank(draft.get("productActivities")) and is_blank(draft.get("productActivitiesJson")):
            missing.append("productActivities")

    ok = not missing and not errors
    normalized = {
        "name": name,
        "actType": act_type,
        "startTime": start_time,
        "endTime": end_time,
        "audienceScope": audience_scope,
        "budget": normalized_budget,
        "collectionDiscountJson": collection,
        "operator": operator,
        "productActivities": products,
    }
    tool_arguments = rest_body = None
    if ok:
        tool_arguments = {
            "name": name,
            "actType": act_type,
            "startTime": start_time,
            "endTime": end_time,
            "audienceScope": audience_scope,
            "budget": normalized_budget,
            "collectionDiscountJson": collection,
            "productActivitiesJson": json.dumps(products, ensure_ascii=False, separators=(",", ":")),
            "operator": operator,
        }
        rest_body = {
            "bigActivity": {
                "name": name,
                "actType": act_type,
                "startTime": start_time,
                "endTime": end_time,
                "audienceScope": audience_scope,
                "budget": normalized_budget,
                "collectionDiscountJson": collection,
                "operator": operator,
            },
            "productActivities": products,
        }

    return {
        "ok": ok,
        "missing": missing,
        "errors": errors,
        "warnings": warnings,
        "normalized": normalized,
        "tool_arguments": tool_arguments,
        "rest_body": rest_body,
    }


def main(argv):
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        if argv[1] == "-":
            text = sys.stdin.read()
        else:
            with open(argv[1], "r", encoding="utf-8") as handle:
                text = handle.read()
    except OSError as exc:
        print(f"读取草稿失败：{exc}", file=sys.stderr)
        return 2
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"草稿不是合法的 JSON：{exc.msg}（第 {exc.lineno} 行）", file=sys.stderr)
        return 2
    result = validate(draft)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

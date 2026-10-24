#!/usr/bin/env python3
"""计算大活动部分更新的差异，并按合并后的最终状态做校验。

用法：
    python3 -I preview_update.py current.json changes.json

current.json：get_big_activity 的返回对象。
changes.json：用户要求修改的字段，可继续使用中文值，例如：
    {"endTime": "2026-9-1 23:59", "budget": 2000}

输出 JSON：ok / no_changes / id / errors / warnings / diff / tool_arguments。
退出码：0 = 可以提交；1 = 有错误或无实际变化；2 = 用法或读取失败。

python 3.8+，仅标准库，可用 -I 隔离运行。
"""

import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

ACT_TYPES = {
    "1": 1, "满减": 1, "满减活动": 1,
    "2": 2, "折扣": 2, "折扣活动": 2,
    "3": 3, "秒杀": 3, "秒杀活动": 3,
    "4": 4, "优惠券": 4, "优惠券活动": 4,
    "5": 5, "组合": 5, "组合优惠": 5, "叠加": 5,
}
ACT_TYPE_LABELS = {1: "满减活动", 2: "折扣活动", 3: "秒杀活动", 4: "优惠券活动", 5: "组合优惠"}

AUDIENCE = {
    "ALL": "ALL", "all": "ALL", "全部": "ALL", "所有用户": "ALL",
    "全部用户": "ALL", "全量": "ALL",
    "NEW": "NEW", "new": "NEW", "新客": "NEW", "仅新客": "NEW", "新人": "NEW",
}
AUDIENCE_LABELS = {"ALL": "所有用户", "NEW": "新客"}

EDITABLE = {
    "name": "名称",
    "actType": "活动类型",
    "startTime": "开始时间",
    "endTime": "结束时间",
    "audienceScope": "活动人群",
    "budget": "预算",
    "collectionDiscountJson": "集合优惠 JSON",
    "operator": "操作人",
}

TIME_RE = re.compile(
    r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?\s*$"
)
MAX_INT64 = 2 ** 63 - 1
MAX_BUDGET = Decimal("999999999999.99")


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def parse_time(value, field, errors, warnings, label="修改后"):
    match = TIME_RE.match(str(value))
    if not match:
        errors.append(f"{field} 格式不正确，应为 yyyy-MM-ddTHH:mm（也接受 yyyy-MM-dd HH:mm[:ss]）")
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        moment = datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second or 0),
        )
    except ValueError:
        errors.append(f"{field} 不是有效的日期时间：{value}")
        return None
    if moment.second:
        warnings.append(f"{field}（{label}）的秒数将按分钟精度提交")
    return moment


def format_time(moment):
    return moment.strftime("%Y-%m-%dT%H:%M")


def normalize_act_type(value, field, errors):
    normalized = ACT_TYPES.get(str(value).strip())
    if normalized is None:
        errors.append(f"{field} 不支持：{value}（应为 1-5 或 满减/折扣/秒杀/优惠券/组合）")
    return normalized


def normalize_audience(value, field, errors):
    normalized = AUDIENCE.get(str(value).strip())
    if normalized is None:
        errors.append(f"{field} 不支持：{value}（应为 ALL/全部 或 NEW/新客）")
    return normalized


def normalize_budget(value, field, errors):
    try:
        budget = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{field} 必须是数字")
        return None
    if not budget.is_finite() or budget < 0:
        errors.append(f"{field} 不能小于 0")
        return None
    if budget > MAX_BUDGET:
        errors.append(f"{field} 最多 12 位整数和 2 位小数")
        return None
    if -budget.as_tuple().exponent > 2:
        errors.append(f"{field} 最多保留 2 位小数")
        return None
    quantized = budget.quantize(Decimal("0.01"))
    return int(quantized) if quantized == quantized.to_integral_value() else float(quantized)


def normalize_json(value, field, errors):
    if is_blank(value):
        return "{}"
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


def canonical_json(raw):
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        return raw


def display(field, value):
    if field == "actType":
        return f"{value}（{ACT_TYPE_LABELS.get(value, '未知')}）" if value is not None else ""
    if field == "audienceScope":
        return f"{value}（{AUDIENCE_LABELS.get(value, '未知')}）" if value else ""
    if field == "budget":
        return f"{value} 元" if value is not None else ""
    return "" if value is None else str(value)


def build_diff(current, changes, errors, warnings):
    diff = []
    tool_arguments = {}

    # ---- name ----
    if "name" in changes:
        name = changes["name"]
        if is_blank(name):
            errors.append("name 不能为空")
        else:
            name = str(name).strip()
            if len(name) > 100:
                errors.append("活动名称不能超过 100 个字符")
            elif name == str(current.get("name", "")).strip():
                warnings.append("name 与当前值相同，已忽略")
            else:
                diff.append(("name", current.get("name"), name))
                tool_arguments["name"] = name

    # ---- actType ----
    if "actType" in changes:
        act_type = normalize_act_type(changes["actType"], "actType", errors)
        if act_type is not None:
            if act_type == current.get("actType"):
                warnings.append("actType 与当前值相同，已忽略")
            else:
                diff.append(("actType", current.get("actType"), act_type))
                tool_arguments["actType"] = act_type

    # ---- startTime / endTime ----
    current_times = {}
    for field in ("startTime", "endTime"):
        moment = parse_time(current.get(field), field, errors, warnings, label="当前值")
        current_times[field] = moment

    changed_times = {}
    for field in ("startTime", "endTime"):
        if field not in changes:
            continue
        moment = parse_time(changes[field], field, errors, warnings)
        if moment is None:
            continue
        changed_times[field] = moment
        if moment == current_times[field]:
            warnings.append(f"{field} 与当前值相同，已忽略")
        else:
            diff.append((field, current.get(field), format_time(moment)))
            tool_arguments[field] = format_time(moment)

    final_start = changed_times.get("startTime", current_times.get("startTime"))
    final_end = changed_times.get("endTime", current_times.get("endTime"))
    if final_start and final_end and final_end <= final_start:
        errors.append("结束时间必须晚于开始时间（按合并后的最终状态校验）")

    # ---- audienceScope ----
    if "audienceScope" in changes:
        audience = normalize_audience(changes["audienceScope"], "audienceScope", errors)
        if audience is not None:
            if audience == current.get("audienceScope"):
                warnings.append("audienceScope 与当前值相同，已忽略")
            else:
                diff.append(("audienceScope", current.get("audienceScope"), audience))
                tool_arguments["audienceScope"] = audience

    # ---- budget ----
    if "budget" in changes:
        budget = normalize_budget(changes["budget"], "budget", errors)
        if budget is not None:
            current_budget = Decimal(str(current.get("budget", 0)))
            if Decimal(str(budget)) == current_budget:
                warnings.append("budget 与当前值相同，已忽略")
            else:
                diff.append(("budget", current.get("budget"), budget))
                tool_arguments["budget"] = budget

    # ---- collectionDiscountJson ----
    if "collectionDiscountJson" in changes:
        collection = normalize_json(changes["collectionDiscountJson"], "collectionDiscountJson", errors)
        if collection is not None:
            if canonical_json(collection) == canonical_json(str(current.get("collectionDiscountJson", "{}"))):
                warnings.append("collectionDiscountJson 与当前值相同，已忽略")
            else:
                diff.append(("collectionDiscountJson", current.get("collectionDiscountJson"), collection))
                tool_arguments["collectionDiscountJson"] = collection

    # ---- operator（审计字段，不参与业务校验）----
    operator = "mcp-agent"
    if "operator" in changes:
        operator = str(changes["operator"]).strip()
        if not operator:
            errors.append("operator 不能为空")
        elif len(operator) > 50:
            errors.append("操作人名称不能超过 50 个字符")
        else:
            current_operator = current.get("updatedBy") or current.get("createdBy") or ""
            if operator != current_operator:
                diff.append(("operator", current_operator, operator))

    return diff, tool_arguments, operator


def main(argv):
    if len(argv) != 3 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        with open(argv[1], "r", encoding="utf-8") as handle:
            current = json.load(handle)
        with open(argv[2], "r", encoding="utf-8") as handle:
            changes = json.load(handle)
    except OSError as exc:
        print(f"读取文件失败：{exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行）", file=sys.stderr)
        return 2

    errors, warnings = [], []
    if not isinstance(current, dict) or not isinstance(changes, dict):
        print("current 与 changes 都必须是 JSON 对象", file=sys.stderr)
        return 2

    activity_id = current.get("id")
    if not isinstance(activity_id, int) or activity_id <= 0:
        print("current.id 缺失或不是有效的 64 位正整数", file=sys.stderr)
        return 2

    for key in changes:
        if key == "id":
            if changes[key] != activity_id:
                errors.append(f"changes 中的 id 与当前目标不一致：{changes[key]} != {activity_id}")
            continue
        if key not in EDITABLE:
            errors.append(f"不支持修改字段 {key}")

    diff, tool_arguments, operator = build_diff(current, changes, errors, warnings)
    no_changes = not errors and not diff

    if not errors and not changes:
        errors.append("没有提供任何修改字段")
        no_changes = True
    elif no_changes and not any("相同" in w for w in warnings):
        errors.append("没有检测到任何修改")

    ok = not errors and not no_changes
    result = {
        "ok": ok,
        "no_changes": no_changes,
        "id": activity_id,
        "errors": errors,
        "warnings": warnings,
        "diff": [
            {
                "field": field,
                "label": EDITABLE[field],
                "current": display(field, old),
                "next": display(field, new),
            }
            for field, old, new in diff
        ],
        "tool_arguments": None,
    }
    if ok:
        arguments = {"id": activity_id}
        arguments.update(tool_arguments)
        arguments["operator"] = operator
        result["tool_arguments"] = arguments

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

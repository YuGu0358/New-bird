from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from app.models import QuantBrainFactorAnalysis

_ALLOWED_EXTENSIONS = {".py", ".txt", ".md", ".markdown"}
_MAX_ATTACHMENTS = 5
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_CODE_CHARS = 30_000

_KNOWN_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "turnover",
    "amount",
    "vwap",
    "returns",
    "return",
    "ret",
    "market_cap",
    "pe",
    "pb",
    "roe",
    "eps",
}
_RISKY_IMPORTS = {"os", "sys", "subprocess", "socket", "requests", "urllib", "httpx", "yfinance"}
_RISKY_CALLS = {"eval", "exec", "open", "compile", "__import__", "input"}
_WINDOW_FUNCTIONS = {"rolling", "ts_mean", "ts_std", "ts_rank", "sma", "ema", "ma", "mean", "std", "delay", "shift"}


def extract_factor_code_files(files: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    """Decode uploaded QuantBrain factor files without executing any code."""

    if len(files) > _MAX_ATTACHMENTS:
        raise ValueError(f"一次最多只能上传 {_MAX_ATTACHMENTS} 个因子代码文件。")

    documents: list[dict[str, str]] = []
    for file_name, payload in files:
        normalized_name = Path(str(file_name or "quantbrain-factor.py")).name
        suffix = Path(normalized_name).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise ValueError("QuantBrain 因子导入目前仅支持 .py、.txt 或 Markdown 文件。")
        if len(payload) > _MAX_FILE_BYTES:
            raise ValueError(f"{normalized_name} 超过 2MB，请精简后再上传。")

        text = _decode_text_bytes(payload)
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ValueError(f"{normalized_name} 当前没有可识别的因子代码。")

        documents.append(
            {
                "name": normalized_name,
                "code": normalized_text[:_MAX_CODE_CHARS],
            }
        )

    return documents


def analyze_factor_code(code: str, *, source_name: str = "pasted-factor.py") -> QuantBrainFactorAnalysis:
    """Statically inspect QuantBrain-style factor code and summarize convertible signals."""

    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise ValueError("请先粘贴或上传 QuantBrain 因子代码。")

    truncated_code = normalized_code[:_MAX_CODE_CHARS]
    visitor = _FactorVisitor(truncated_code)
    parse_warning = ""
    try:
        visitor.visit(ast.parse(truncated_code))
    except SyntaxError as exc:
        parse_warning = f"Python AST 解析失败：第 {exc.lineno or '?'} 行附近存在语法问题，已改用文本规则做保守识别。"

    regex_result = _regex_scan(truncated_code)
    factor_names = _dedupe([*visitor.factor_names, *regex_result["factor_names"]])
    input_fields = _dedupe([*visitor.input_fields, *regex_result["input_fields"]])
    windows = sorted(set([*visitor.windows, *regex_result["windows"]]))
    buy_conditions = _dedupe([*visitor.buy_conditions, *regex_result["buy_conditions"]])
    sell_conditions = _dedupe([*visitor.sell_conditions, *regex_result["sell_conditions"]])
    unsupported_features = _dedupe([*visitor.unsupported_features, *regex_result["unsupported_features"]])
    risk_flags = _dedupe([*visitor.risk_flags, *regex_result["risk_flags"]])

    if parse_warning:
        unsupported_features.insert(0, parse_warning)
    if _looks_cross_sectional(truncated_code):
        unsupported_features.append("检测到横截面排序/分组逻辑；当前 Strategy B 执行器不能真实运行横截面因子，只能近似转换。")
    if _looks_intraday(truncated_code):
        unsupported_features.append("检测到分钟级或日内字段；当前执行器按日线/昨收逻辑近似表达。")

    sort_direction = _infer_sort_direction(truncated_code)
    signal_summary = _build_signal_summary(
        factor_names=factor_names,
        input_fields=input_fields,
        windows=windows,
        sort_direction=sort_direction,
        buy_conditions=buy_conditions,
        sell_conditions=sell_conditions,
    )

    return QuantBrainFactorAnalysis(
        source_name=source_name,
        factor_names=factor_names[:12],
        input_fields=input_fields[:20],
        windows=windows[:12],
        buy_conditions=buy_conditions[:10],
        sell_conditions=sell_conditions[:10],
        sort_direction=sort_direction,
        signal_summary=signal_summary,
        unsupported_features=_dedupe(unsupported_features)[:20],
        risk_flags=risk_flags[:20],
        safe_static_analysis=True,
        raw_code_chars=len(normalized_code),
    )


def build_factor_strategy_input(
    factor_analysis: QuantBrainFactorAnalysis,
    *,
    code: str,
    user_notes: str = "",
) -> str:
    """Compose a bounded prompt section for strategy normalization."""

    code_excerpt = str(code or "").strip()[:8000]
    notes = str(user_notes or "").strip()
    return (
        "这是一次 QuantBrain 因子代码导入。请基于静态解析结果和代码片段，"
        "把因子想法转换成当前交易机器人能预览、保存并激活的 Strategy B 参数。\n\n"
        "重要约束：\n"
        "- 后端不会执行用户代码，只能静态理解因子逻辑。\n"
        "- 当前执行器不能真正运行横截面因子、分钟级因子或外部数据依赖；这些只能近似表达，并必须写进风险提醒。\n"
        "- 如果因子偏向动量/高分排序，可映射为更偏趋势跟随的股票池与较小回撤入场阈值。\n"
        "- 如果因子偏向反转/低分回归，可映射为回撤买入和更严格止损。\n\n"
        f"用户补充说明：\n{notes or '无'}\n\n"
        f"静态解析结果：\n{json.dumps(factor_analysis.model_dump(), ensure_ascii=False)}\n\n"
        f"因子代码片段：\n```python\n{code_excerpt}\n```"
    )


def _decode_text_bytes(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("因子代码文件无法解码，请改用 UTF-8 文本。")


class _FactorVisitor(ast.NodeVisitor):
    def __init__(self, code: str) -> None:
        self.code = code
        self.factor_names: list[str] = []
        self.input_fields: list[str] = []
        self.windows: list[int] = []
        self.buy_conditions: list[str] = []
        self.sell_conditions: list[str] = []
        self.unsupported_features: list[str] = []
        self.risk_flags: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.factor_names.append(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.factor_names.append(node.name)
        self.unsupported_features.append("检测到 async 函数；当前因子导入只做静态解析，不执行异步代码。")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.factor_names.append(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _RISKY_IMPORTS:
                self.unsupported_features.append(f"检测到外部/系统依赖 import {alias.name}，不会执行该依赖。")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        root = (node.module or "").split(".")[0]
        if root in _RISKY_IMPORTS:
            self.unsupported_features.append(f"检测到外部/系统依赖 from {node.module} import ...，不会执行该依赖。")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        target_names = [_node_name(target) for target in node.targets]
        for name in target_names:
            lowered = name.lower()
            if "factor" in lowered and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                self.factor_names.append(node.value.value)
            if any(token in lowered for token in ("buy", "entry", "long")):
                self.buy_conditions.append(_safe_unparse(node.value))
            if any(token in lowered for token in ("sell", "exit", "short")):
                self.sell_conditions.append(_safe_unparse(node.value))
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> Any:
        condition = _safe_unparse(node.test)
        lowered = condition.lower()
        if any(token in lowered for token in ("buy", "entry", "long", "score >")):
            self.buy_conditions.append(condition)
        elif any(token in lowered for token in ("sell", "exit", "short", "score <")):
            self.sell_conditions.append(condition)
        else:
            self.buy_conditions.append(condition)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        call_name = _call_name(node.func)
        lowered = call_name.lower()
        if lowered in _RISKY_CALLS:
            self.unsupported_features.append(f"检测到危险调用 {call_name}，系统不会执行该代码。")
        if lowered in {"read_csv", "read_excel", "to_csv", "to_excel"}:
            self.unsupported_features.append(f"检测到文件数据调用 {call_name}，当前导入不会读取外部文件。")
        if lowered in _WINDOW_FUNCTIONS:
            self.windows.extend(_extract_window_numbers(node))
        if lowered in {"shift", "lead"} and _has_negative_numeric_arg(node):
            self.risk_flags.append("检测到负向 shift/lead，可能存在未来函数或前视偏差。")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        field = _subscript_field(node)
        if field:
            self.input_fields.append(field)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr.lower() in _KNOWN_FIELDS:
            self.input_fields.append(node.attr.lower())
        self.generic_visit(node)


def _regex_scan(code: str) -> dict[str, list[Any]]:
    lowered = code.lower()
    factor_names = re.findall(r"(?:factor_name|name)\s*=\s*['\"]([^'\"]+)['\"]", code, flags=re.I)
    input_fields = [
        match.lower()
        for match in re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", code)
        if match.lower() in _KNOWN_FIELDS
    ]
    windows = [int(value) for value in re.findall(r"(?:rolling|window|period|lookback|ma|sma|ema)\s*[\(=]\s*(\d{1,4})", lowered)]
    buy_conditions = re.findall(r"(?:buy|entry|long)[A-Za-z0-9_]*\s*=\s*([^\n]+)", code, flags=re.I)
    sell_conditions = re.findall(r"(?:sell|exit|short)[A-Za-z0-9_]*\s*=\s*([^\n]+)", code, flags=re.I)

    unsupported: list[str] = []
    risk_flags: list[str] = []
    if re.search(r"\b(eval|exec|open|__import__|compile)\s*\(", lowered):
        unsupported.append("检测到 eval/exec/open 等危险调用，系统不会执行该代码。")
    if re.search(r"\b(os|subprocess|socket|requests|urllib|httpx)\b", lowered):
        unsupported.append("检测到系统、网络或外部请求依赖，当前导入只做静态解析。")
    if re.search(r"shift\s*\(\s*-\d+|lead\s*\(", lowered):
        risk_flags.append("检测到未来数据引用特征，可能造成回测前视偏差。")

    return {
        "factor_names": factor_names,
        "input_fields": input_fields,
        "windows": windows,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions,
        "unsupported_features": unsupported,
        "risk_flags": risk_flags,
    }


def _extract_window_numbers(node: ast.Call) -> list[int]:
    values: list[int] = []
    for arg in node.args[:2]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            values.append(arg.value)
    for keyword in node.keywords:
        if keyword.arg in {"window", "period", "lookback", "n"} and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, int):
                values.append(keyword.value.value)
    return [value for value in values if 0 < value <= 1000]


def _subscript_field(node: ast.Subscript) -> str:
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        value = slice_node.value.lower()
        return value if value in _KNOWN_FIELDS else ""
    return ""


def _has_negative_numeric_arg(node: ast.Call) -> bool:
    for arg in node.args:
        if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
            return True
        if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)) and arg.value < 0:
            return True
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _node_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return _safe_unparse(node)


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        if value in ("", None):
            continue
        key = str(value).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _looks_cross_sectional(code: str) -> bool:
    lowered = code.lower()
    return any(token in lowered for token in ("rank(", "quantile", "groupby", "top_n", "nlargest", "nsmallest", "cross_section"))


def _looks_intraday(code: str) -> bool:
    lowered = code.lower()
    return any(token in lowered for token in ("minute", "intraday", "1m", "5m", "15m", "bar_time", "timestamp"))


def _infer_sort_direction(code: str) -> str:
    lowered = code.lower()
    if any(token in lowered for token in ("ascending=false", "nlargest", "top_n", "high score", "score >")):
        return "higher_is_better"
    if any(token in lowered for token in ("ascending=true", "nsmallest", "low score", "score <")):
        return "lower_is_better"
    if "momentum" in lowered or "returns" in lowered:
        return "higher_is_better"
    if "mean_reversion" in lowered or "reversal" in lowered:
        return "lower_is_better"
    return "unknown"


def _build_signal_summary(
    *,
    factor_names: list[str],
    input_fields: list[str],
    windows: list[int],
    sort_direction: str,
    buy_conditions: list[str],
    sell_conditions: list[str],
) -> str:
    factor_label = ", ".join(factor_names[:3]) if factor_names else "未命名因子"
    field_label = ", ".join(input_fields[:6]) if input_fields else "未明确识别字段"
    window_label = ", ".join(str(item) for item in windows[:4]) if windows else "未明确识别窗口"
    direction_label = {
        "higher_is_better": "高分偏多",
        "lower_is_better": "低分偏多/反转",
        "unknown": "方向待确认",
    }.get(sort_direction, "方向待确认")
    condition_bits = []
    if buy_conditions:
        condition_bits.append(f"买入条件：{buy_conditions[0]}")
    if sell_conditions:
        condition_bits.append(f"卖出条件：{sell_conditions[0]}")
    condition_label = "；".join(condition_bits) if condition_bits else "未识别到明确买卖条件"
    return f"{factor_label} 使用 {field_label}，窗口 {window_label}，信号方向为{direction_label}；{condition_label}。"

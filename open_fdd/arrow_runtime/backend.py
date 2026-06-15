"""Arrow-native rule execution backend."""

from __future__ import annotations

import ast
import builtins as _builtins
import datetime
import math
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

import pyarrow as pa
import pyarrow.compute as pc

from .config import configure_arrow_runtime
from .pyarrow_policy import FORBIDDEN_IMPORT_ROOTS, NO_PANDAS_AGENT_MSG, lint_pyarrow_only
from .summary import preview_fault_rows, summarize_arrow_run

ALLOWED_ARROW_IMPORT_ROOTS = frozenset(
    {"datetime", "math", "pyarrow", "open_fdd", "openfdd"}
)


@dataclass
class ArrowRuleResult:
    rule_id: str
    backend: str
    row_count: int
    true_count: int
    false_count: int
    null_count: int
    duration_ms: float
    fault_mask: pa.Array | pa.ChunkedArray
    output_table: pa.Table | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    preview: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self, *, include_preview: bool = True) -> dict[str, Any]:
        out = {
            "rule_id": self.rule_id,
            "backend": self.backend,
            "row_count": self.row_count,
            "true_count": self.true_count,
            "false_count": self.false_count,
            "null_count": self.null_count,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
            "errors": self.errors,
            "summary": self.summary,
            "fully_arrow_native": not self.errors,
        }
        if include_preview:
            out["preview"] = self.preview
        return out


def lint_arrow_rule(code: str, *, strict_imports: bool = True) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not code.strip():
        return {"ok": False, "issues": [{"line": 1, "message": "empty rule", "severity": "error"}]}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "ok": False,
            "issues": [
                {
                    "line": exc.lineno or 1,
                    "message": exc.msg or "invalid syntax",
                    "severity": "error",
                }
            ],
        }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_ARROW_IMPORT_ROOTS:
                    msg = (
                        f"import '{alias.name}' forbidden — {NO_PANDAS_AGENT_MSG}"
                        if root in FORBIDDEN_IMPORT_ROOTS
                        else f"import '{alias.name}' not allowed in Arrow rules"
                    )
                    issues.append(
                        {
                            "line": node.lineno,
                            "message": msg,
                            "severity": "error" if strict_imports else "warning",
                        }
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root not in ALLOWED_ARROW_IMPORT_ROOTS:
                msg = (
                    f"import from '{node.module}' forbidden — {NO_PANDAS_AGENT_MSG}"
                    if root in FORBIDDEN_IMPORT_ROOTS
                    else f"import from '{node.module}' not allowed"
                )
                issues.append(
                    {
                        "line": node.lineno,
                        "message": msg,
                        "severity": "error" if strict_imports else "warning",
                    }
                )
    entrypoint: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "apply_faults_arrow":
            entrypoint = node
            break
    if entrypoint is None:
        issues.append(
            {
                "line": 1,
                "message": "rule must define apply_faults_arrow(table, cfg, context=None)",
                "severity": "error",
            }
        )
    else:
        arg_names = [a.arg for a in entrypoint.args.args]
        if len(arg_names) < 2 or arg_names[0] != "table" or arg_names[1] != "cfg":
            issues.append(
                {
                    "line": entrypoint.lineno,
                    "message": "apply_faults_arrow must accept (table, cfg, context=None)",
                    "severity": "error",
                }
            )
        elif len(arg_names) > 2 and arg_names[2] != "context":
            issues.append(
                {
                    "line": entrypoint.lineno,
                    "message": "third parameter should be named context",
                    "severity": "warning",
                }
            )
    issues.extend(lint_pyarrow_only(tree, script_mode=False))
    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


def _arrow_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    root = name.split(".")[0]
    if root not in ALLOWED_ARROW_IMPORT_ROOTS:
        raise ImportError(f"import of '{name}' not allowed in Arrow rules")
    return _builtins.__import__(name, globals_, locals_, fromlist, level)


def _arrow_rule_globals() -> dict[str, Any]:
    return {
        "__builtins__": {
            "print": print,
            "range": range,
            "len": len,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "round": round,
            "float": float,
            "int": int,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "__import__": _arrow_import,
        },
        "datetime": datetime,
        "math": math,
        "pa": pa,
        "pyarrow": pa,
        "pc": pc,
    }


def compile_apply_faults_arrow(code: str) -> Callable[..., Any]:
    lint = lint_arrow_rule(code, strict_imports=True)
    if not lint["ok"]:
        msgs = [i["message"] for i in lint["issues"] if i["severity"] == "error"]
        raise ValueError("Arrow rule invalid:\n" + "\n".join(msgs))
    g = _arrow_rule_globals()
    exec(compile(code, "<arrow_rule>", "exec"), g, g)  # noqa: S102
    fn = g.get("apply_faults_arrow")
    if not callable(fn):
        raise ValueError("rule must define apply_faults_arrow(table, cfg, context=None)")
    return fn


def normalize_fault_mask(
    raw: Any,
    *,
    expected_len: int,
) -> pa.ChunkedArray:
    if isinstance(raw, (pa.Array, pa.ChunkedArray)):
        from .arrays import as_array

        mask = as_array(raw)
    else:
        raise TypeError(f"apply_faults_arrow must return BooleanArray/ChunkedArray, got {type(raw).__name__}")
    if not pa.types.is_boolean(mask.type):
        mask = pc.cast(mask, pa.bool_())
    if len(mask) != expected_len:
        raise ValueError(f"fault mask length {len(mask)} != table rows {expected_len}")
    return mask


def run_arrow_rule(
    rule_code_or_fn: str | Callable[..., Any],
    table: pa.Table,
    cfg: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
    rule_id: str = "",
    include_output_table: bool = False,
    preview_columns: list[str] | None = None,
    preview_limit: int = 20,
) -> ArrowRuleResult:
    configure_arrow_runtime()
    started = time.perf_counter()
    cfg = dict(cfg or {})
    ctx = dict(context or {})
    warnings: list[str] = []
    errors: list[str] = []
    try:
        fn = (
            compile_apply_faults_arrow(rule_code_or_fn)
            if isinstance(rule_code_or_fn, str)
            else rule_code_or_fn
        )
        raw = fn(table, cfg, ctx)
        mask = normalize_fault_mask(raw, expected_len=table.num_rows)
        from .confirmation import apply_fault_confirmation_from_cfg

        mask, confirm_warnings = apply_fault_confirmation_from_cfg(mask, table, cfg)
        warnings.extend(confirm_warnings)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        mask = pa.array([False] * table.num_rows, type=pa.bool_())
        duration_ms = (time.perf_counter() - started) * 1000
        return ArrowRuleResult(
            rule_id=rule_id,
            backend="arrow",
            row_count=table.num_rows,
            true_count=0,
            false_count=table.num_rows,
            null_count=0,
            duration_ms=duration_ms,
            fault_mask=mask,
            errors=errors,
            warnings=warnings,
            summary={"error": str(exc), "trace": traceback.format_exc(limit=6)},
        )

    from .events import count_mask_values

    counts = count_mask_values(mask)
    duration_ms = (time.perf_counter() - started) * 1000
    out_table = None
    if include_output_table:
        from .features import arrow_fault_mask_to_column

        out_table = table.append_column("fault", arrow_fault_mask_to_column(mask))
    summary = summarize_arrow_run(
        table,
        mask,
        rule_id=rule_id,
        site_id=str(cfg.get("site_id") or ""),
        duration_ms=duration_ms,
        backend="arrow",
        warnings=warnings,
    )
    from .execution_evidence import COMPUTATION_PATH_ARROW, build_execution_evidence

    summary["execution_evidence"] = build_execution_evidence(
        table=table,
        mask=mask,
        backend="arrow",
        computation_path=COMPUTATION_PATH_ARROW,
        confirmation_applied=bool(cfg.get("min_true_rows") or cfg.get("min_elapsed_minutes")),
    )
    preview = preview_fault_rows(table, mask, columns=preview_columns, limit=preview_limit)
    return ArrowRuleResult(
        rule_id=rule_id,
        backend="arrow",
        row_count=counts["row_count"],
        true_count=counts["true_count"],
        false_count=counts["false_count"],
        null_count=counts["null_count"],
        duration_ms=duration_ms,
        fault_mask=mask,
        output_table=out_table,
        warnings=warnings,
        errors=errors,
        summary=summary,
        preview=preview,
    )


def iter_record_batches(table: pa.Table, batch_rows: int) -> list[pa.RecordBatch]:
    if table.num_rows <= batch_rows:
        return table.to_batches()
    batches: list[pa.RecordBatch] = []
    for offset in range(0, table.num_rows, batch_rows):
        batches.append(table.slice(offset, min(batch_rows, table.num_rows - offset)).to_batches()[0])
    return batches


def run_arrow_rule_chunked(
    rule_code: str,
    table: pa.Table,
    cfg: dict[str, Any] | None = None,
    *,
    rule_id: str = "",
    batch_rows: int | None = None,
) -> ArrowRuleResult:
    from .config import get_arrow_runtime_config

    cfg = dict(cfg or {})
    rt = get_arrow_runtime_config()
    size = batch_rows or rt.batch_rows
    if table.num_rows <= size:
        return run_arrow_rule(rule_code, table, cfg, rule_id=rule_id)
    from .arrays import as_array

    fn = compile_apply_faults_arrow(rule_code)
    masks: list[pa.Array] = []
    started = time.perf_counter()
    for batch in iter_record_batches(table, size):
        sub = pa.Table.from_batches([batch])
        part = run_arrow_rule(fn, sub, cfg, rule_id=rule_id)
        masks.append(as_array(part.fault_mask))
    combined = pa.chunked_array(masks)
    duration_ms = (time.perf_counter() - started) * 1000
    from .events import count_mask_values

    counts = count_mask_values(combined)
    summary = summarize_arrow_run(table, combined, rule_id=rule_id, duration_ms=duration_ms)
    return ArrowRuleResult(
        rule_id=rule_id,
        backend="arrow",
        row_count=counts["row_count"],
        true_count=counts["true_count"],
        false_count=counts["false_count"],
        null_count=counts["null_count"],
        duration_ms=duration_ms,
        fault_mask=combined,
        summary=summary,
        preview=preview_fault_rows(table, combined, limit=20),
    )

"""AST-based whitelist validator for user-supplied strategy source.

Walks the AST and rejects:
- Imports outside the allow-list
- Calls to dangerous builtins (eval / exec / compile / __import__ / open ...)
- Attribute access to introspection dunders (__class__ / __globals__ / __code__ ...)
- Files larger than MAX_CODE_BYTES

This is a TRUST-BUT-VERIFY guard. A determined attacker who can write
Python COULD probably escape these rules; we're protecting against
accidents and casual misuse, not adversarial multi-tenant isolation.
For full sandboxing (subprocess + seccomp / firejail) defer to a future
phase.
"""
from __future__ import annotations

import ast


class ValidationError(ValueError):
    """User code failed AST validation."""


# ---------------------------------------------------------------------------
# Allow / deny lists
# ---------------------------------------------------------------------------

# Top-level package prefixes that are allowed in `import X` / `from X import Y`.
ALLOWED_IMPORT_PREFIXES: tuple[str, ...] = (
    "core.strategy",
    "core.broker",
    "app.models",
    "numpy",
    "pandas",
    "math",
    "statistics",
    "datetime",
    "typing",
    "dataclasses",
    "decimal",
    "enum",
    "re",
    "__future__",
    "collections",
    "collections.abc",
    "itertools",
    "functools",
    "operator",
)

# Builtins that, when CALLED, are denied.
FORBIDDEN_BUILTIN_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "vars",
    "globals",
    "locals",
    "delattr",
    "setattr",
})

# Attribute names that are flat-out forbidden anywhere.
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset({
    "__class__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "__builtins__",
    "__dict__",
    "__loader__",
    "__spec__",
    "__import__",
    "mro",
    "f_globals",
    "f_locals",
    "func_globals",
    "func_code",
    "im_func",
    "im_class",
})

MAX_CODE_BYTES = 100_000
STRATEGY_BASE_NAME = "Strategy"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_strategy_source(code: str) -> ast.Module:
    """Validate the source string. Returns the parsed AST on success.

    Raises ValidationError with a human-readable message on the first
    detected issue.
    """
    if len(code) > MAX_CODE_BYTES:
        raise ValidationError(
            f"source is too large ({len(code)} bytes > {MAX_CODE_BYTES})"
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValidationError(f"syntax error: {exc.msg} at line {exc.lineno}") from exc

    walker = _AstGuard()
    walker.visit(tree)

    if not walker.has_strategy_subclass:
        raise ValidationError(
            f"source must define a class that subclasses {STRATEGY_BASE_NAME!r}"
        )

    return tree


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


def _is_allowed_import(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in ALLOWED_IMPORT_PREFIXES
    )


class _AstGuard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_strategy_subclass = False

    # -- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not _is_allowed_import(alias.name):
                raise ValidationError(f"forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level and node.level > 0:
            raise ValidationError("relative imports are not allowed")
        if not _is_allowed_import(module):
            raise ValidationError(f"forbidden import: {module}")
        self.generic_visit(node)

    # -- calls / names ------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTIN_CALLS:
            raise ValidationError(f"forbidden builtin: {node.func.id}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Flag references to forbidden builtins even outside calls
        # (e.g. `f = eval; f('x')`).
        if isinstance(node.ctx, ast.Load) and node.id in FORBIDDEN_BUILTIN_CALLS:
            raise ValidationError(f"forbidden builtin: {node.id}")
        self.generic_visit(node)

    # -- attributes ---------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTRIBUTES:
            raise ValidationError(f"forbidden attribute: {node.attr}")
        self.generic_visit(node)

    # -- class definitions --------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == STRATEGY_BASE_NAME:
                self.has_strategy_subclass = True
                break
            if isinstance(base, ast.Attribute) and base.attr == STRATEGY_BASE_NAME:
                self.has_strategy_subclass = True
                break
        self.generic_visit(node)

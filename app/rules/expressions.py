from __future__ import annotations

import ast
import math
from collections.abc import Callable

Numeric = float | int | bool

_ALLOWED_FUNCS: dict[str, Callable[..., Numeric]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
    "cos": math.cos,
    "sin": math.sin,
    "radians": math.radians,
    "clamp": lambda x, lo, hi: max(lo, min(hi, x)),
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.BinOp,
    ast.UnaryOp,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
)


class ExpressionError(ValueError):
    pass


def _check_nodes(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"disallowed expression element: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise ExpressionError("only whitelisted functions may be called")


def safe_eval(expr: str, context: dict[str, Numeric]) -> Numeric:
    """Pure. Restricted AST evaluator — never eval()/exec(). No I/O, no clock."""
    tree = ast.parse(expr, mode="eval")
    _check_nodes(tree)

    def _ev(node: ast.AST) -> Numeric:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int | float | bool):
                return node.value
            raise ExpressionError("only numeric/boolean constants are allowed")
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ExpressionError(f"unknown name: {node.id}")
            return context[node.id]
        if isinstance(node, ast.BoolOp):
            values = [_ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            val = _ev(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +val
            if isinstance(node.op, ast.USub):
                return -val
            if isinstance(node.op, ast.Not):
                return not val
        if isinstance(node, ast.BinOp):
            left, right = _ev(node.left), _ev(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
        if isinstance(node, ast.Compare):
            left = _ev(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _ev(comparator)
                if isinstance(op, ast.Eq):
                    ok = left == right
                elif isinstance(op, ast.NotEq):
                    ok = left != right
                elif isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                elif isinstance(op, ast.GtE):
                    ok = left >= right
                else:
                    raise ExpressionError("unsupported comparison")
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            fn = _ALLOWED_FUNCS[node.func.id]
            args = [_ev(a) for a in node.args]
            return fn(*args)
        raise ExpressionError(f"unsupported expression node: {type(node).__name__}")

    return _ev(tree)

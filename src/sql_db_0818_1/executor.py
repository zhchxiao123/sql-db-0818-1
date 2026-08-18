"""语句执行器:把 AST 变为对内存表的操作。

支持:
- CREATE TABLE:建表(不建索引;PRIMARY KEY 等约束本子集不建模)
- INSERT:追加行(按列亲和做存储类转换;整行/列清单/多行)
- SELECT:投影(常量与列引用)/ WHERE 过滤(比较 + AND/OR/NOT)/
  ORDER BY 排序(列名或序号)/ LIMIT 截断;无 FROM 时投影常量

表达式求值遵循 SQLite 语义:
- 存储类:NULL < INTEGER/REAL < TEXT < BLOB;数值按数值比较,文本按字节序
- 比较:先按操作数亲和做转换,再按存储类比较;NULL 参与比较结果 NULL
- 逻辑:三元逻辑(AND/OR/NOT)

范围外(不实现):连接、聚合、子查询、函数、索引、事务、视图、触发器、DISTINCT。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import List, Optional

from . import ast
from .storage import (
    AFF_INTEGER,
    AFF_NUMERIC,
    AFF_REAL,
    AFF_TEXT,
    Column,
    Database,
    SqlError,
    Value,
    apply_affinity,
    compare_values,
    numeric_value,
)

# 数值亲和集合(用于比较规则)
_NUMERIC_AFFS = {AFF_INTEGER, AFF_REAL, AFF_NUMERIC}


@dataclass
class QueryResult:
    """SELECT 的执行结果:行(每行是原始值列表)。"""

    rows: List[List[Value]] = field(default_factory=list)


def execute(db: Database, stmt: ast.Statement):
    """执行一条语句。

    Returns:
        QueryResult(SELECT)或 None(CREATE/INSERT)。

    Raises:
        SqlError: 执行失败(语句级错误)。
    """
    if isinstance(stmt, ast.CreateTable):
        _exec_create(db, stmt)
        return None
    if isinstance(stmt, ast.Insert):
        _exec_insert(db, stmt)
        return None
    if isinstance(stmt, ast.Select):
        return _exec_select(db, stmt)
    raise SqlError(f"不支持的语句类型 {type(stmt).__name__}")


def _exec_create(db: Database, stmt: ast.CreateTable) -> None:
    columns = [
        Column(name=c.name, type_name=c.type_name, affinity=c.affinity)
        for c in stmt.columns
    ]
    db.create_table(stmt.table, columns)


def _exec_insert(db: Database, stmt: ast.Insert) -> None:
    rows: List[List[Value]] = []
    for row in stmt.rows:
        values: List[Value] = [_eval_expr(None, [], e) for e in row]
        rows.append(values)
    db.insert(stmt.table, stmt.columns, rows)


# ---------------------------------------------------------------- 求值上下文
# cols: 列定义列表(大写归一化);row: 当前行值;None 表示常量语境(无 FROM)。


def _eval_expr(
    cols: Optional[List[Column]],
    row: Optional[List[Value]],
    expr: ast.Expr,
) -> Value:
    if isinstance(expr, ast.Literal):
        return expr.value
    if isinstance(expr, ast.ColumnRef):
        if cols is None:
            raise SqlError(f"未知列 {expr.name}")
        for i, col in enumerate(cols):
            if col.name == expr.name:
                assert row is not None
                return row[i]
        raise SqlError(f"未知列 {expr.name}")
    if isinstance(expr, ast.UnaryOp):
        return _eval_unary(cols, row, expr)
    if isinstance(expr, ast.BinaryOp):
        return _eval_binary(cols, row, expr)
    raise SqlError(f"未知表达式类型 {type(expr).__name__}")


def _eval_unary(cols, row, expr: ast.UnaryOp) -> Value:
    operand = _eval_expr(cols, row, expr.operand)
    if expr.op == "NOT":
        return _not(operand)
    if expr.op == "-":
        if operand is None:
            return None
        num = numeric_value(operand)
        return -num
    if expr.op == "+":
        return operand
    raise SqlError(f"未知一元运算符 {expr.op}")


def _eval_binary(cols, row, expr: ast.BinaryOp) -> Value:
    op = expr.op
    if op == "AND":
        left = _eval_expr(cols, row, expr.left)
        if _is_false(left):
            return 0
        right = _eval_expr(cols, row, expr.right)
        if _is_false(right):
            return 0
        if left is None or right is None:
            return None
        return 1
    if op == "OR":
        left = _eval_expr(cols, row, expr.left)
        if _is_true(left):
            return 1
        right = _eval_expr(cols, row, expr.right)
        if _is_true(right):
            return 1
        if left is None or right is None:
            return None
        return 0

    left = _eval_expr(cols, row, expr.left)
    right = _eval_expr(cols, row, expr.right)

    if op in ("=", "!=", "<>", "<", "<=", ">", ">="):
        return _compare_op(cols, expr, left, right)
    raise SqlError(f"未知二元运算符 {op}")


# ---------------------------------------------------------------- 比较
def _expr_affinity(cols, expr: ast.Expr) -> str:
    """表达式的亲和(用于比较转换规则)。"""
    if isinstance(expr, ast.ColumnRef) and cols is not None:
        for col in cols:
            if col.name == expr.name:
                return col.affinity
        return "NONE"
    return "NONE"


def _compare_op(cols, expr: ast.BinaryOp, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    aff_a = _expr_affinity(cols, expr.left)
    aff_b = _expr_affinity(cols, expr.right)
    a2, b2 = _apply_cmp_affinity(a, aff_a, b, aff_b)
    r = compare_values(a2, b2)
    op = expr.op
    if op == "=":
        return 1 if r == 0 else 0
    if op in ("!=", "<>"):
        return 1 if r != 0 else 0
    if op == "<":
        return 1 if r < 0 else 0
    if op == "<=":
        return 1 if r <= 0 else 0
    if op == ">":
        return 1 if r > 0 else 0
    if op == ">=":
        return 1 if r >= 0 else 0
    raise SqlError(f"未知比较运算符 {op}")


def _apply_cmp_affinity(a: Value, aff_a: str, b: Value, aff_b: str):
    """SQLite 比较前的亲和转换规则。"""
    if aff_a in _NUMERIC_AFFS and aff_b not in _NUMERIC_AFFS:
        return a, apply_affinity(b, AFF_NUMERIC)
    if aff_b in _NUMERIC_AFFS and aff_a not in _NUMERIC_AFFS:
        return apply_affinity(a, AFF_NUMERIC), b
    if aff_a == AFF_TEXT and aff_b == "NONE":
        return a, apply_affinity(b, AFF_TEXT)
    if aff_b == AFF_TEXT and aff_a == "NONE":
        return apply_affinity(a, AFF_TEXT), b
    return a, b


def _is_true(a: Value) -> bool:
    """SQLite 真值:NULL 未知;文本按数字前缀转数值;非零即真。"""
    if a is None:
        return False
    n = numeric_value(a)
    return n != 0


def _is_false(a: Value) -> bool:
    if a is None:
        return False
    n = numeric_value(a)
    return n == 0


def _not(a: Value) -> Value:
    if a is None:
        return None
    return 1 if _is_false(a) else 0


# ---------------------------------------------------------------- SELECT
def _exec_select(db: Database, stmt: ast.Select) -> QueryResult:
    # 无 FROM:常量投影,单行
    if stmt.table is None:
        row = [_eval_expr(None, [], p) for p in stmt.projections]
        return QueryResult(rows=[row])

    table = db.get_table(stmt.table)
    cols = table.columns

    # 过滤 + 投影;保留原始行以便 ORDER BY 引用未投影列
    matched: List[tuple] = []  # (raw_row, projected_row)
    for raw in table.rows:
        if stmt.where is not None:
            cond = _eval_expr(cols, raw, stmt.where)
            if not _is_true(cond):
                continue
        projected = [_eval_expr(cols, raw, p) for p in stmt.projections]
        matched.append((raw, projected))

    if stmt.order_by:
        matched = _sort_rows(matched, stmt.order_by, cols)

    rows = [proj for _raw, proj in matched]

    if stmt.limit is not None:
        if stmt.limit < 0:
            # SQLite:LIMIT -1 表示不限制
            pass
        else:
            rows = rows[: stmt.limit]

    return QueryResult(rows=rows)


def _sort_rows(
    matched: List[tuple],
    order_by: List[ast.OrderItem],
    cols: List[Column],
) -> List[tuple]:
    """按 ORDER BY 项排序。

    序号(字面量整数)指向投影列位置;列引用指向表列(ORDER BY 可引用未投影列)。
    """
    nproj = len(matched[0][1]) if matched else 0

    def _key(item: ast.OrderItem, raw, proj):
        expr = item.expr
        if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
            idx = expr.value
            if idx < 1 or idx > nproj:
                raise SqlError(f"ORDER BY 序号 {idx} 超出投影列数 {nproj}")
            return proj[idx - 1]
        if isinstance(expr, ast.ColumnRef):
            for i, col in enumerate(cols):
                if col.name == expr.name:
                    return raw[i]
            raise SqlError(f"ORDER BY 未知列 {expr.name}")
        raise SqlError("ORDER BY 只支持列名或列序号")

    # 生成排序键;用 cmp_to_key 保持 SQLite 存储类顺序(NULL<数值<文本<BLOB)
    def _make_key(item: ast.OrderItem):
        def _k(pair):
            raw, proj = pair
            return _key(item, raw, proj)
        return _k

    result = matched
    for item in reversed(order_by):
        kfn = _make_key(item)

        def _cmp(a, b, _kfn=kfn, _desc=item.desc):
            va, vb = _kfn(a), _kfn(b)
            r = compare_values(va, vb)
            return -r if _desc else r

        result = sorted(result, key=functools.cmp_to_key(_cmp))
    return result

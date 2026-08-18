"""语句执行器:把 AST 变为对内存表的操作。

子需求 1 支持:
- CREATE TABLE:建表(含列级 COLLATE;不建索引;约束不建模)
- INSERT:追加行(按列亲和做存储类转换;整行/列清单/多行;值可为表达式)
- SELECT:投影(常量/列引用/算术/函数/CASE/CAST 等表达式)、WHERE(三值逻辑)、
  ORDER BY(任意表达式 + COLLATE,列名或序号)、LIMIT 截断;无 FROM 时投影常量

表达式求值遵循 SQLite 语义(以 sqlite3 3.46.1 实测为准):
- 存储类:NULL < INTEGER/REAL < TEXT < BLOB;数值按数值比较,文本按 collation
- 算术:NULL 传播;int+int→int(int64 溢出转 REAL),任一 real→real;
  / 整数除法(向零截断),1/0→NULL;% 两个操作数先截断为 int64,C 风格取模
- ||:转文本连接(含 BLOB→TEXT),NULL 传播
- 比较:先按操作数亲和做转换,再按存储类比较;IS/IS NOT 为 NULL 安全等值
- LIKE/GLOB:通配符、ASCII 大小写(仅 LIKE 不敏感)、ESCAPE;任一操作数为
  BLOB 时 LIKE 恒为 false
- IN/BETWEEN/CASE:NULL 语义与亲和规则与 sqlite 一致
- CAST:INTEGER/REAL/TEXT/BLOB/NUMERIC 转换(前缀解析、int64 截断)
- 标量函数:abs/length/substr/coalesce/ifnull/nullif/typeof/upper/lower/hex/
  quote/round/min/max/sign/unicode/char/replace/instr/trim/ltrim/rtrim/
  like/glob/printf
- collation:BINARY/NOCASE/RTRIM 影响文本比较与 ORDER BY

范围外(不实现):连接、聚合、子查询、索引、事务、视图、触发器、DISTINCT。
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import ast
from .storage import (
    AFF_BLOB,
    AFF_INTEGER,
    AFF_NONE,
    AFF_NUMERIC,
    AFF_REAL,
    AFF_TEXT,
    COLL_BINARY,
    COLL_NOCASE,
    COLL_RTRIM,
    INT64_MAX,
    INT64_MIN,
    Column,
    Database,
    SqlError,
    SqlFunctionError,
    Value,
    apply_affinity,
    ascii_lower,
    ascii_upper,
    cast_value,
    clamp_int64,
    compare_values,
    glob_match,
    is_numeric_text,
    like_match,
    numeric_value,
    parse_int_prefix,
    parse_numeric_prefix,
    sqlite_round,
    sqlite_substr,
    text_of_value,
)

# 数值亲和集合(用于比较规则)
_NUMERIC_AFFS = {AFF_INTEGER, AFF_REAL, AFF_NUMERIC}

_CMP_OPS = {"=", "!=", "<>", "<", "<=", ">", ">="}
_ARITH = {"+", "-", "*", "/", "%", "||"}

# 函数参数省略哨兵(区分「未传参」与「传了 NULL」)
_OMITTED = object()


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
    if isinstance(stmt, ast.Update):
        _exec_update(db, stmt)
        return None
    if isinstance(stmt, ast.Delete):
        _exec_delete(db, stmt)
        return None
    if isinstance(stmt, ast.Select):
        return _exec_select(db, stmt)
    raise SqlError(f"unsupported statement {type(stmt).__name__}")


def _exec_create(db: Database, stmt: ast.CreateTable) -> None:
    columns = []
    for c in stmt.columns:
        coll = c.collation
        if coll not in (COLL_BINARY, COLL_NOCASE, COLL_RTRIM):
            raise SqlError(f"no such collation sequence: {coll}")
        columns.append(
            Column(
                name=c.name,
                type_name=c.type_name,
                affinity=c.affinity,
                collation=coll,
                default=c.default,
            )
        )
    db.create_table(stmt.table, columns)


def _exec_insert(db: Database, stmt: ast.Insert) -> None:
    if stmt.default_values:
        # INSERT INTO t DEFAULT VALUES → 单行,所有列取 DEFAULT/NULL
        db.insert(stmt.table, [], [[]])
        return
    rows: List[List[Value]] = []
    for row in stmt.rows:
        values: List[Value] = [_eval_expr(None, [], e) for e in row]
        rows.append(values)
    db.insert(stmt.table, stmt.columns, rows)


def _exec_update(db: Database, stmt: ast.Update) -> None:
    """UPDATE t SET col=expr, ... WHERE cond。

    SQLite 语义:所有 SET 表达式对【原行】求值,然后再统一应用(交换赋值
    SET a=b, b=a 成立);WHERE 过滤原行。
    """
    table = db.get_table(stmt.table)
    cols = table.columns
    # 先解析目标列,确保列存在
    target_indexes = [table.column_index(col) for col, _ in stmt.assignments]
    new_rows: List[List[Value]] = []
    for raw in table.rows:
        if stmt.where is not None:
            cond = _eval_expr(cols, raw, stmt.where)
            if not _is_true(cond):
                new_rows.append(raw)
                continue
        updated = list(raw)
        # 所有表达式对原行求值
        new_values = [_eval_expr(cols, raw, expr) for _col, expr in stmt.assignments]
        for idx, val in zip(target_indexes, new_values):
            updated[idx] = apply_affinity(val, cols[idx].affinity)
        new_rows.append(updated)
    table.rows = new_rows


def _exec_delete(db: Database, stmt: ast.Delete) -> None:
    """DELETE FROM t WHERE cond;无 WHERE → 全删。"""
    table = db.get_table(stmt.table)
    cols = table.columns
    if stmt.where is None:
        table.rows = []
        return
    table.rows = [
        raw for raw in table.rows if not _is_true(_eval_expr(cols, raw, stmt.where))
    ]


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
            raise SqlError(f"no such column: {expr.name}")
        for i, col in enumerate(cols):
            if col.name == expr.name:
                assert row is not None
                return row[i]
        raise SqlError(f"no such column: {expr.name}")
    if isinstance(expr, ast.UnaryOp):
        return _eval_unary(cols, row, expr)
    if isinstance(expr, ast.BinaryOp):
        return _eval_binary(cols, row, expr)
    if isinstance(expr, ast.Cast):
        v = _eval_expr(cols, row, expr.expr)
        return cast_value(v, expr.affinity)
    if isinstance(expr, ast.FuncCall):
        return _eval_func(cols, row, expr)
    if isinstance(expr, ast.Like):
        return _eval_like(cols, row, expr)
    if isinstance(expr, ast.Glob):
        return _eval_glob(cols, row, expr)
    if isinstance(expr, ast.InList):
        return _eval_in(cols, row, expr)
    if isinstance(expr, ast.Between):
        return _eval_between(cols, row, expr)
    if isinstance(expr, ast.Case):
        return _eval_case(cols, row, expr)
    if isinstance(expr, ast.Collate):
        return _eval_expr(cols, row, expr.expr)
    raise SqlError(f"unknown expression {type(expr).__name__}")


def _eval_unary(cols, row, expr: ast.UnaryOp) -> Value:
    operand = _eval_expr(cols, row, expr.operand)
    if expr.op == "NOT":
        return _not(operand)
    if expr.op == "-":
        if operand is None:
            return None
        num = numeric_value(operand)
        assert num is not None
        if isinstance(num, int):
            r = -num
            if r < INT64_MIN or r > INT64_MAX:
                return float(r)
            return r
        return -num
    if expr.op == "+":
        # SQLite 一元加号是 no-op(返回原值,'+' '5' → '5')
        return operand
    raise SqlError(f"unknown unary operator {expr.op}")


# ---------------------------------------------------------------- 二元运算
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
    if op in _ARITH:
        return _eval_arith(cols, row, expr)
    if op in ("IS", "IS NOT"):
        return _eval_is(cols, row, expr, op)
    if op in _CMP_OPS:
        left = _eval_expr(cols, row, expr.left)
        right = _eval_expr(cols, row, expr.right)
        return _compare_op(cols, expr, left, right)
    raise SqlError(f"unknown binary operator {op}")


def _eval_is(cols, row, expr: ast.BinaryOp, op: str) -> Value:
    left = _eval_expr(cols, row, expr.left)
    right = _eval_expr(cols, row, expr.right)
    if left is None and right is None:
        # NULL IS NULL → 1;NULL IS NOT NULL → 0
        return 1 if op == "IS" else 0
    if left is None or right is None:
        return 0 if op == "IS" else 1
    r = compare_values(left, right, COLL_BINARY)
    eq = r == 0
    if op == "IS":
        return 1 if eq else 0
    return 0 if eq else 1


def _eval_arith(cols, row, expr: ast.BinaryOp) -> Value:
    op = expr.op
    left = _eval_expr(cols, row, expr.left)
    right = _eval_expr(cols, row, expr.right)
    if op == "||":
        if left is None or right is None:
            return None
        # SQLite 3.46 实测:|| 对任何操作数都返回 TEXT(含 BLOB||BLOB → TEXT)
        return text_of_value(left) + text_of_value(right)
    if left is None or right is None:
        return None
    a = numeric_value(left)
    b = numeric_value(right)
    assert a is not None and b is not None

    if op == "+":
        return _arith_result(a, b, a + b)
    if op == "-":
        return _arith_result(a, b, a - b)
    if op == "*":
        return _arith_result(a, b, a * b)
    if op == "/":
        if _is_zero(b):
            return None  # 1/0 → NULL(SQLite 3.46 实测)
        if isinstance(a, int) and isinstance(b, int):
            return _int_div(a, b)
        return a / b
    if op == "%":
        if _is_zero(b):
            return None
        # SQLite %:两个操作数都先截断为 int64,C 风格取模,结果为 real 若任一操作数为 real
        ia = int(a)
        ib = int(b)
        if ib == 0:
            return None
        if ib == -1:
            r = 0
        else:
            r = _c_mod(ia, ib)
        if isinstance(a, float) or isinstance(b, float):
            return float(r)
        return clamp_int64(r)
    raise SqlError(f"unknown arithmetic operator {op}")


def _c_mod(a: int, b: int) -> int:
    """C 风格取模(向零截断):-10 % 3 = -1;10 % -3 = 1。"""
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return a - q * b


def _is_zero(v) -> bool:
    if isinstance(v, int):
        return v == 0
    if isinstance(v, float):
        return v == 0.0
    return False


def _int_div(a: int, b: int) -> Value:
    """整数除法(向零截断):-7/2 = -3。"""
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return clamp_int64(q)


def _arith_result(a, b, r) -> Value:
    """算术结果:int 运算在 int64 内保持 int,溢出转 REAL。"""
    if isinstance(a, int) and isinstance(b, int) and isinstance(r, int):
        if r < INT64_MIN or r > INT64_MAX:
            return float(r)
        return r
    return float(r)


# ---------------------------------------------------------------- 比较
def _expr_affinity(cols, expr: ast.Expr) -> str:
    """表达式的亲和(用于比较转换规则)。"""
    if isinstance(expr, ast.ColumnRef) and cols is not None:
        for col in cols:
            if col.name == expr.name:
                return col.affinity
        return AFF_NONE
    if isinstance(expr, ast.Cast):
        return expr.affinity
    return AFF_NONE


def _expr_explicit_collation(expr: ast.Expr) -> Optional[str]:
    """表达式中显式 COLLATE(运算符优先于隐式列 collation)。"""
    if isinstance(expr, ast.Collate):
        return expr.collation
    if isinstance(expr, ast.BinaryOp) and expr.op == "||":
        lc = _expr_explicit_collation(expr.left)
        if lc is not None:
            return lc
        return _expr_explicit_collation(expr.right)
    return None


def _expr_column_collation(cols, expr: ast.Expr) -> Optional[str]:
    """表达式的列 collation(列引用;|| 传播左操作数,否则右操作数)。"""
    if isinstance(expr, ast.ColumnRef) and cols is not None:
        for col in cols:
            if col.name == expr.name:
                return col.collation
        return None
    if isinstance(expr, ast.BinaryOp) and expr.op == "||":
        lc = _expr_column_collation(cols, expr.left)
        if lc is not None:
            return lc
        return _expr_column_collation(cols, expr.right)
    return None


def _cmp_collation(cols, left: ast.Expr, right: ast.Expr) -> str:
    """比较运算符的 collation 解析(SQLite 规则)。

    1. 任一操作数显式 COLLATE → 用它(左右都显式且不同 → 报错,本子集不构造);
    2. 否则左操作数是列 → 用其 collation(即使 BINARY);
    3. 否则右操作数是列 → 用其 collation;
    4. 否则 BINARY。
    """
    le = _expr_explicit_collation(left)
    if le is not None:
        return le
    re = _expr_explicit_collation(right)
    if re is not None:
        return re
    lc = _expr_column_collation(cols, left)
    if lc is not None:
        return lc
    rc = _expr_column_collation(cols, right)
    if rc is not None:
        return rc
    return COLL_BINARY


def _order_collation(cols, expr: ast.Expr) -> str:
    """ORDER BY 项的 collation:显式 COLLATE > 列 collation > BINARY。"""
    c = _expr_explicit_collation(expr)
    if c is not None:
        return c
    c = _expr_column_collation(cols, expr)
    if c is not None:
        return c
    return COLL_BINARY


def _compare_op(cols, expr: ast.BinaryOp, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    aff_a = _expr_affinity(cols, expr.left)
    aff_b = _expr_affinity(cols, expr.right)
    a2, b2 = _apply_cmp_affinity(a, aff_a, b, aff_b)
    coll = _cmp_collation(cols, expr.left, expr.right)
    r = compare_values(a2, b2, coll)
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
    raise SqlError(f"unknown comparison operator {op}")


def _apply_cmp_affinity(a: Value, aff_a: str, b: Value, aff_b: str):
    """SQLite 比较前的亲和转换规则。"""
    if aff_a in _NUMERIC_AFFS and aff_b not in _NUMERIC_AFFS:
        return a, apply_affinity(b, AFF_NUMERIC)
    if aff_b in _NUMERIC_AFFS and aff_a not in _NUMERIC_AFFS:
        return apply_affinity(a, AFF_NUMERIC), b
    if aff_a == AFF_TEXT and aff_b == AFF_NONE:
        return a, apply_affinity(b, AFF_TEXT)
    if aff_b == AFF_TEXT and aff_a == AFF_NONE:
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


# ---------------------------------------------------------------- LIKE / GLOB
def _eval_like(cols, row, expr: ast.Like) -> Value:
    v = _eval_expr(cols, row, expr.expr)
    p = _eval_expr(cols, row, expr.pattern)
    esc = _eval_expr(cols, row, expr.escape) if expr.escape is not None else None
    if v is None or p is None or (expr.escape is not None and esc is None):
        return None
    r = like_match(v, p, esc)
    if r is None:
        return None
    if expr.negated:
        return 1 - r
    return r


def _eval_glob(cols, row, expr: ast.Glob) -> Value:
    v = _eval_expr(cols, row, expr.expr)
    p = _eval_expr(cols, row, expr.pattern)
    if v is None or p is None:
        return None
    r = glob_match(v, p)
    if r is None:
        return None
    return 0 if expr.negated else r


# ---------------------------------------------------------------- IN / BETWEEN / CASE
def _eval_in(cols, row, expr: ast.InList) -> Value:
    v = _eval_expr(cols, row, expr.expr)
    aff = _expr_affinity(cols, expr.expr)
    if v is None:
        return None
    saw_null = False
    for item_expr in expr.items:
        item = _eval_expr(cols, row, item_expr)
        if item is None:
            saw_null = True
            continue
        # IN 只应用左操作数的亲和(与 = 不同:'2' IN (a) 不匹配 INTEGER 列)
        item2 = apply_affinity(item, aff) if aff != AFF_NONE else item
        if compare_values(v, item2, COLL_BINARY) == 0:
            return 0 if expr.negated else 1
    if saw_null:
        return None
    return 1 if expr.negated else 0


def _eval_between(cols, row, expr: ast.Between) -> Value:
    v = _eval_expr(cols, row, expr.expr)
    if v is None:
        return None
    low = _eval_expr(cols, row, expr.low)
    high = _eval_expr(cols, row, expr.high)
    aff = _expr_affinity(cols, expr.expr)
    # 边界应用主体表达式的亲和
    l2 = apply_affinity(low, aff) if low is not None and aff != AFF_NONE else low
    h2 = apply_affinity(high, aff) if high is not None and aff != AFF_NONE else high
    r1 = compare_values(v, l2, _cmp_collation(cols, expr.expr, expr.low)) if l2 is not None else None
    r2 = compare_values(v, h2, _cmp_collation(cols, expr.expr, expr.high)) if h2 is not None else None
    if r1 is None or r2 is None:
        return None
    ok = (r1 >= 0) and (r2 <= 0)
    return 0 if expr.negated else (1 if ok else 0)


def _eval_case(cols, row, expr: ast.Case) -> Value:
    base = _eval_expr(cols, row, expr.base) if expr.base is not None else None
    for cond_expr, result_expr in expr.whens:
        if expr.base is not None:
            # 简单 CASE:CASE base WHEN v — 用 = 语义(NULL 永不匹配)
            cond = _eval_expr(cols, row, cond_expr)
            if base is not None and cond is not None:
                tmp = ast.BinaryOp("=", expr.base, cond_expr)
                if _compare_op(cols, tmp, base, cond) == 1:
                    return _eval_expr(cols, row, result_expr)
        else:
            cond = _eval_expr(cols, row, cond_expr)
            if _is_true(cond):
                return _eval_expr(cols, row, result_expr)
    if expr.else_expr is not None:
        return _eval_expr(cols, row, expr.else_expr)
    return None


# ---------------------------------------------------------------- 标量函数
_FUNCS = {
    "ABS",
    "LENGTH",
    "SUBSTR",
    "COALESCE",
    "IFNULL",
    "NULLIF",
    "TYPEOF",
    "UPPER",
    "LOWER",
    "HEX",
    "QUOTE",
    "ROUND",
    "MIN",
    "MAX",
    "SIGN",
    "UNICODE",
    "CHAR",
    "REPLACE",
    "INSTR",
    "TRIM",
    "LTRIM",
    "RTRIM",
    "LIKE",
    "GLOB",
    "PRINTF",
}


def _eval_func(cols, row, expr: ast.FuncCall) -> Value:
    name = expr.name
    if name not in _FUNCS:
        raise SqlError(f"no such function: {name}")
    args = [_eval_expr(cols, row, a) for a in expr.args]
    n = len(args)
    try:
        if name == "ABS":
            _need(name, n, 1, 1)
            return _fn_abs(args[0])
        if name == "LENGTH":
            _need(name, n, 1, 1)
            return _fn_length(args[0])
        if name == "SUBSTR":
            _need(name, n, 2, 3)
            return _fn_substr(args[0], args[1], args[2] if n >= 3 else _OMITTED)
        if name == "COALESCE":
            # SQLite 实测:coalesce(NULL) → wrong number of arguments(至少 2 参)
            _need(name, n, 2, None)
            for a in args:
                if a is not None:
                    return a
            return None
        if name == "IFNULL":
            _need(name, n, 2, 2)
            return args[0] if args[0] is not None else args[1]
        if name == "NULLIF":
            _need(name, n, 2, 2)
            if args[0] is None or args[1] is None:
                return args[0]
            return None if compare_values(args[0], args[1], COLL_BINARY) == 0 else args[0]
        if name == "TYPEOF":
            _need(name, n, 1, 1)
            v = args[0]
            if v is None:
                return "null"
            if isinstance(v, int):
                return "integer"
            if isinstance(v, float):
                return "real"
            if isinstance(v, str):
                return "text"
            return "blob"
        if name == "UPPER":
            _need(name, n, 1, 1)
            return _fn_upper(args[0])
        if name == "LOWER":
            _need(name, n, 1, 1)
            return _fn_lower(args[0])
        if name == "HEX":
            _need(name, n, 1, 1)
            return _fn_hex(args[0])
        if name == "QUOTE":
            _need(name, n, 1, 1)
            return _fn_quote(args[0])
        if name == "ROUND":
            _need(name, n, 1, 2)
            return _fn_round(args[0], args[1] if n >= 2 else None)
        if name in ("MIN", "MAX"):
            _need(name, n, 1, None)
            return _fn_minmax(name, args)
        if name == "SIGN":
            _need(name, n, 1, 1)
            return _fn_sign(args[0])
        if name == "UNICODE":
            _need(name, n, 1, 1)
            return _fn_unicode(args[0])
        if name == "CHAR":
            _need(name, n, 0, None)
            return _fn_char(args)
        if name == "REPLACE":
            _need(name, n, 3, 3)
            return _fn_replace(args[0], args[1], args[2])
        if name == "INSTR":
            _need(name, n, 2, 2)
            return _fn_instr(args[0], args[1])
        if name in ("TRIM", "LTRIM", "RTRIM"):
            _need(name, n, 1, 2)
            return _fn_trim(name, args[0], args[1] if n >= 2 else None)
        if name == "LIKE":
            _need(name, n, 2, 3)
            esc = args[2] if n >= 3 else None
            return like_match(args[1], args[0], esc)
        if name == "GLOB":
            _need(name, n, 2, 2)
            return glob_match(args[1], args[0])
        if name == "PRINTF":
            _need(name, n, 1, None)
            return _fn_printf(args)
    except SqlFunctionError as exc:
        raise SqlError(str(exc)) from None
    raise SqlError(f"unknown function {name}")


def _need(name: str, n: int, lo: int, hi: Optional[int]) -> None:
    if n < lo or (hi is not None and n > hi):
        if lo == hi:
            raise SqlFunctionError(
                f"wrong number of arguments to function {name.lower()}()"
            )
        raise SqlFunctionError(
            f"wrong number of arguments to function {name.lower()}()"
        )


def _fn_abs(v: Value) -> Value:
    if v is None:
        return None
    if isinstance(v, int):
        return abs(v)
    if isinstance(v, float):
        return abs(v)
    # 文本/BLOB → REAL(abs('abc')=0.0,abs('-3')=3.0)
    n = parse_numeric_prefix(text_of_value(v))
    return abs(0.0 if n is None else float(n))


def _fn_length(v: Value) -> Value:
    if v is None:
        return None
    if isinstance(v, str):
        return len(v)
    if isinstance(v, bytes):
        return len(v)
    return len(text_of_value(v))


def _fn_substr(v: Value, y: Value, z: Value = _OMITTED) -> Value:
    if v is None or y is None:
        return None
    n = numeric_value(y)
    if n is None:
        return None
    y_int = int(n)
    if z is _OMITTED:
        z_int = None
    else:
        if z is None:
            return None  # substr(X,Y,NULL) → NULL(实测)
        nz = numeric_value(z)
        if nz is None:
            return None
        z_int = int(nz)
    if isinstance(v, bytes):
        return sqlite_substr(v, y_int, z_int)
    return sqlite_substr(text_of_value(v), y_int, z_int)


def _fn_upper(v: Value) -> Value:
    if v is None:
        return None
    return ascii_upper(text_of_value(v))


def _fn_lower(v: Value) -> Value:
    if v is None:
        return None
    return ascii_lower(text_of_value(v))


def _fn_hex(v: Value) -> Value:
    # SQLite 实测:hex(NULL) → ''(空串,不是 NULL);输出大写十六进制
    if v is None:
        return ""
    b = v if isinstance(v, bytes) else text_of_value(v).encode("utf-8")
    return b.hex().upper()


def _fn_quote(v: Value) -> Value:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return text_of_value(v)
    if isinstance(v, bytes):
        return "X'" + v.hex().upper() + "'"
    return "'" + v.replace("'", "''") + "'"


def _fn_round(v: Value, n: Optional[Value]) -> Value:
    if v is None:
        return None
    try:
        x = float(numeric_value(v))
    except (TypeError, ValueError):
        x = 0.0
    if n is None:
        nd = 0
    else:
        nd = int(numeric_value(n))
    return sqlite_round(x, nd)


def _fn_minmax(name: str, args: List[Value]) -> Value:
    # 单参数:恒等
    if len(args) == 1:
        return args[0]
    best = args[0]
    for a in args[1:]:
        if a is None or best is None:
            return None
        r = compare_values(a, best, COLL_BINARY)
        if (name == "MIN" and r < 0) or (name == "MAX" and r > 0):
            best = a
    return best


def _fn_sign(v: Value) -> Value:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v > 0:
            return 1 if isinstance(v, int) else 1.0
        if v < 0:
            return -1 if isinstance(v, int) else -1.0
        return 0 if isinstance(v, int) else 0.0
    if not is_numeric_text(v):
        return None  # sign('abc') → NULL
    n = parse_numeric_prefix(text_of_value(v))
    if n is None:
        return None
    if isinstance(n, float):
        return 1.0 if n > 0 else (-1.0 if n < 0 else 0.0)
    return 1 if n > 0 else (-1 if n < 0 else 0)


def _fn_unicode(v: Value) -> Value:
    if v is None:
        return None
    s = text_of_value(v)
    if s == "":
        return None
    return ord(s[0])


def _fn_char(args: List[Value]) -> Value:
    out = []
    for a in args:
        if a is None:
            out.append("\x00")
            continue
        n = int(numeric_value(a))
        out.append(chr(n & 0xFFFF))
    return "".join(out)


def _fn_replace(s: Value, f: Value, r: Value) -> Value:
    if s is None or f is None or r is None:
        return None
    sv = text_of_value(s)
    fv = text_of_value(f)
    rv = text_of_value(r)
    if fv == "":
        return sv  # replace('abc','','x') → 'abc'(实测)
    return sv.replace(fv, rv)


def _fn_instr(s: Value, sub: Value) -> Value:
    if s is None or sub is None:
        return None
    sv = text_of_value(s)
    subv = text_of_value(sub)
    if subv == "":
        return 1
    idx = sv.find(subv)
    return idx + 1 if idx >= 0 else 0


def _fn_trim(name: str, s: Value, chars: Optional[Value]) -> Value:
    if s is None:
        return None
    sv = text_of_value(s)
    if chars is None:
        cset = " "
    else:
        cset = text_of_value(chars)
    if name == "LTRIM":
        return sv.lstrip(cset)
    if name == "RTRIM":
        return sv.rstrip(cset)
    return sv.strip(cset)


# ---------------------------------------------------------------- printf
def _fn_printf(args: List[Value]) -> Value:
    fmt = text_of_value(args[0]) if args[0] is not None else ""
    vals = args[1:]
    out: List[str] = []
    vi = 0
    i = 0
    n = len(fmt)
    while i < n:
        c = fmt[i]
        if c != "%":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            out.append("%")
            break
        if fmt[i] == "%":
            out.append("%")
            i += 1
            continue
        # 宽度/精度/标志(最小实现)
        flags = ""
        while i < n and fmt[i] in "-+ #0":
            flags += fmt[i]
            i += 1
        width = ""
        while i < n and fmt[i].isdigit():
            width += fmt[i]
            i += 1
        prec = ""
        if i < n and fmt[i] == ".":
            i += 1
            while i < n and fmt[i].isdigit():
                prec += fmt[i]
                i += 1
        if i >= n:
            out.append("%")
            break
        spec = fmt[i]
        i += 1
        if vi >= len(vals):
            out.append("%" + spec)
            continue
        val = vals[vi]
        vi += 1
        if val is None:
            # SQLite:NULL 参数在 %d/%s 等中输出空串;%Q 输出 NULL
            if spec in ("Q",):
                return None
            out.append("")
            continue
        piece = _printf_one(spec, flags, width, prec, val)
        out.append(piece)
    return "".join(out)


def _printf_one(spec: str, flags: str, width: str, prec: str, val: Value) -> str:
    if spec in ("d", "i", "u"):
        iv = int(float(numeric_value(val)))
        if spec == "u":
            iv = iv & 0xFFFFFFFFFFFFFFFF if iv < 0 else iv
        s = str(iv)
    elif spec in ("x", "X"):
        iv = int(float(numeric_value(val)))
        s = format(iv & 0xFFFFFFFFFFFFFFFF, "x" if spec == "x" else "X")
    elif spec == "o":
        iv = int(float(numeric_value(val)))
        s = format(iv & 0xFFFFFFFFFFFFFFFF, "o")
    elif spec == "c":
        # SQLite 实测:printf('%c', 65) → '6'(取文本表示的首字符,不是 chr(65))
        s = text_of_value(val)
        s = s[:1] if s else ""
    elif spec == "f":
        fv = float(numeric_value(val))
        p = int(prec) if prec else 6
        s = f"{fv:.{p}f}"
    elif spec == "e":
        fv = float(numeric_value(val))
        p = int(prec) if prec else 6
        s = f"{fv:.{p}e}"
    elif spec == "g":
        fv = float(numeric_value(val))
        p = int(prec) if prec else 6
        s = f"{fv:.{p}g}"
    elif spec in ("s", "q", "Q"):
        s = text_of_value(val)
        if spec in ("q", "Q"):
            s = s.replace("'", "''")
        if prec:
            s = s[: int(prec)]
    else:
        return "%" + spec
    # 应用标志与宽度
    if flags and "0" in flags and width and spec not in ("s", "q", "Q"):
        s = s.zfill(int(width)) if not s.startswith("-") else "-" + s[1:].zfill(int(width) - 1)
    if flags and "-" in flags:
        s = s.ljust(int(width)) if width else s
    elif width and len(s) < int(width):
        s = s.rjust(int(width))
    return s


# ---------------------------------------------------------------- SELECT
def _rows_equal(a: List[Value], b: List[Value], colls: List[str]) -> bool:
    """DISTINCT 行相等:逐列比较;NULL==NULL;数值 1 与 1.0 相等;
    文本按表达式 collation(NOCASE 下 'a'=='A')。"""
    if len(a) != len(b):
        return False
    for x, y, coll in zip(a, b, colls):
        if x is None and y is None:
            continue
        if x is None or y is None:
            return False
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if float(x) != float(y):
                return False
            continue
        if compare_values(x, y, coll) != 0:
            return False
    return True


def _dedup_rows(
    matched: List[tuple], cols: List[Column], projections: List[ast.Expr]
) -> List[tuple]:
    """SELECT DISTINCT 去重:保留首个匹配行,文本比较按各投影的 collation。"""
    colls = [_order_collation(cols, p) for p in projections]
    result: List[tuple] = []
    for raw, proj in matched:
        if any(_rows_equal(proj, p2, colls) for _r2, p2 in result):
            continue
        result.append((raw, proj))
    return result


def _exec_select(db: Database, stmt: ast.Select) -> QueryResult:
    # 无 FROM:常量投影,单行;但 WHERE 仍参与过滤(SELECT 1 WHERE 0 → 空)
    if stmt.table is None:
        row = [_eval_expr(None, [], p) for p in stmt.projections]
        if stmt.where is not None:
            cond = _eval_expr(None, [], stmt.where)
            if not _is_true(cond):
                return QueryResult(rows=[])
        rows = [row]
        if stmt.distinct:
            seen: List[List[Value]] = []
            dedup: List[List[Value]] = []
            colls = [COLL_BINARY for _ in stmt.projections]
            for r in rows:
                if any(_rows_equal(r, s, colls) for s in seen):
                    continue
                seen.append(r)
                dedup.append(r)
            rows = dedup
        if stmt.limit is not None or stmt.offset is not None:
            start = stmt.offset if stmt.offset is not None and stmt.offset > 0 else 0
            if stmt.limit is not None and stmt.limit >= 0:
                rows = rows[start : start + stmt.limit]
            else:
                rows = rows[start:]
        return QueryResult(rows=rows)

    table = db.get_table(stmt.table)
    cols = table.columns

    # SELECT * 展开
    projections = stmt.projections
    star_expanded = False
    if any(isinstance(p, ast.Literal) and p.value == "*" for p in projections):
        star_expanded = True
        new_proj = []
        for p in projections:
            if isinstance(p, ast.Literal) and p.value == "*":
                for col in cols:
                    new_proj.append(ast.ColumnRef(col.name))
            else:
                new_proj.append(p)
        projections = new_proj

    # 过滤 + 投影;保留原始行以便 ORDER BY 引用未投影列
    matched: List[tuple] = []  # (raw_row, projected_row)
    for raw in table.rows:
        if stmt.where is not None:
            cond = _eval_expr(cols, raw, stmt.where)
            if not _is_true(cond):
                continue
        projected = [_eval_expr(cols, raw, p) for p in projections]
        matched.append((raw, projected))

    # SELECT DISTINCT:对投影结果去重(NULL 视为相等;文本按 collation);保留首个原始行
    if stmt.distinct:
        matched = _dedup_rows(matched, cols, projections)

    if stmt.order_by:
        matched = _sort_rows(matched, stmt.order_by, cols)

    rows = [proj for _raw, proj in matched]

    # LIMIT n OFFSET m;LIMIT -1 = 不限制;OFFSET 负值按 0
    if stmt.limit is not None or stmt.offset is not None:
        start = stmt.offset if stmt.offset is not None and stmt.offset > 0 else 0
        if stmt.limit is not None and stmt.limit >= 0:
            rows = rows[start : start + stmt.limit]
        else:
            rows = rows[start:]

    return QueryResult(rows=rows)


def _sort_rows(
    matched: List[tuple],
    order_by: List[ast.OrderItem],
    cols: List[Column],
) -> List[tuple]:
    """按 ORDER BY 项排序(任意表达式 + collation)。"""
    nproj = len(matched[0][1]) if matched else 0

    def _key(item: ast.OrderItem, raw, proj):
        expr = item.expr
        if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
            idx = expr.value
            if idx < 1 or idx > nproj:
                raise SqlError(
                    f"{idx} ORDER BY term out of range - should be between 1 and {nproj}"
                )
            return proj[idx - 1]
        return _eval_expr(cols, raw, expr)

    def _make_key(item: ast.OrderItem):
        coll = _order_collation(cols, item.expr)

        def _k(pair):
            raw, proj = pair
            return _key(item, raw, proj)

        def _cmp(a, b, _kfn=_k, _desc=item.desc, _coll=coll):
            va, vb = _kfn(a), _kfn(b)
            if va is None and vb is None:
                r = 0
            elif va is None:
                r = -1
            elif vb is None:
                r = 1
            else:
                r = compare_values(va, vb, _coll)
            return -r if _desc else r

        return _cmp

    result = matched
    for item in reversed(order_by):
        cmpfn = _make_key(item)
        result = sorted(result, key=functools.cmp_to_key(cmpfn))
    return result

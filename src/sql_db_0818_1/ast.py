"""SQL AST 定义。

覆盖 CREATE TABLE / INSERT / UPDATE / DELETE / SELECT 以及子需求 1 的表达式
系统:字面量、列引用、算术(+ - * / % ||)、比较(= != <> < <= > >= IS IS NOT)、
布尔组合(AND/OR/NOT)、ISNULL/NOTNULL、CAST、标量函数、LIKE/GLOB、IN、
BETWEEN、CASE、COLLATE 后缀。SELECT 支持 WHERE/ORDER BY/LIMIT/OFFSET/DISTINCT。

范围外特性(连接、子查询、聚合、索引、事务、视图、触发器)不在此处建模。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

Number = Union[int, float]
Value = Union[Number, str, bytes, None]  # None 表示 NULL;bytes 表示 BLOB


# ---------------------------------------------------------------- 表达式
class Expr:
    """表达式基类。"""


@dataclass
class Literal(Expr):
    value: Optional[Union[Number, str, bytes]]


@dataclass
class ColumnRef(Expr):
    name: str  # 已归一化为大写


@dataclass
class BinaryOp(Expr):
    op: str  # = != <> < <= > >= IS IS NOT + - * / % || AND OR
    left: Expr
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str  # '-' | '+' | 'NOT'
    operand: Expr


@dataclass
class Cast(Expr):
    expr: Expr
    type_name: str  # 原始类型名,如 INTEGER / TEXT
    affinity: str  # 'INTEGER' | 'REAL' | 'TEXT' | 'BLOB' | 'NUMERIC'


@dataclass
class FuncCall(Expr):
    name: str  # 已归一化为大写
    args: List[Expr] = field(default_factory=list)


@dataclass
class Like(Expr):
    expr: Expr
    pattern: Expr
    escape: Optional[Expr] = None
    negated: bool = False  # NOT LIKE


@dataclass
class Glob(Expr):
    expr: Expr
    pattern: Expr
    negated: bool = False  # NOT GLOB


@dataclass
class InList(Expr):
    expr: Expr
    items: List[Expr] = field(default_factory=list)
    negated: bool = False  # NOT IN


@dataclass
class Between(Expr):
    expr: Expr
    low: Expr
    high: Expr
    negated: bool = False  # NOT BETWEEN


@dataclass
class Case(Expr):
    base: Optional[Expr]  # None = 搜索形式(CASE WHEN ...)
    whens: List[Tuple[Expr, Expr]] = field(default_factory=list)  # (条件, 结果)
    else_expr: Optional[Expr] = None


@dataclass
class Collate(Expr):
    expr: Expr
    collation: str  # 已归一化为大写:BINARY / NOCASE / RTRIM / 自定义名


# ---------------------------------------------------------------- 语句
class Statement:
    """语句基类。"""


@dataclass
class ColumnDef:
    name: str  # 已归一化为大写
    type_name: str  # 原始类型名,如 INTEGER / VARCHAR(10)
    affinity: str  # 'INTEGER' | 'REAL' | 'TEXT' | 'BLOB' | 'NUMERIC' | 'NONE'
    collation: str = "BINARY"  # 列级 COLLATE,默认 BINARY
    default: "Optional[Value]" = None  # DEFAULT 字面量(未指定 → None)


@dataclass
class CreateTable(Statement):
    table: str
    columns: List[ColumnDef] = field(default_factory=list)


@dataclass
class Insert(Statement):
    table: str
    columns: Optional[List[str]]  # None = 未指定列清单
    rows: List[List[Expr]] = field(default_factory=list)
    default_values: bool = False  # INSERT ... DEFAULT VALUES


@dataclass
class Update(Statement):
    table: str
    assignments: List[Tuple[str, Expr]]  # (列名, 表达式)
    where: Optional[Expr] = None


@dataclass
class Delete(Statement):
    table: str
    where: Optional[Expr] = None


@dataclass
class OrderItem:
    expr: Expr  # 表达式或序号(ORDINAL 字面量)
    desc: bool = False


@dataclass
class Select(Statement):
    projections: List[Expr] = field(default_factory=list)
    table: Optional[str] = None  # None = 无 FROM(常量投影)
    where: Optional[Expr] = None
    order_by: List[OrderItem] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    distinct: bool = False

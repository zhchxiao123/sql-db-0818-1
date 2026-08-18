"""SQL AST 定义。

覆盖 CREATE TABLE / INSERT / SELECT 以及最小内核需要的表达式:
字面量、列引用、比较(= != <> < <= > >=)、布尔组合(AND/OR/NOT)。

范围外特性(连接、聚合、子查询、函数、索引、事务、视图、触发器、DISTINCT、
CASE、LIKE、IN、BETWEEN、CAST)不在此处建模。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

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
    op: str  # = != <> < <= > >= AND OR
    left: Expr
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str  # '-' | '+' | 'NOT'
    operand: Expr


# ---------------------------------------------------------------- 语句
class Statement:
    """语句基类。"""


@dataclass
class ColumnDef:
    name: str  # 已归一化为大写
    type_name: str  # 原始类型名,如 INTEGER / VARCHAR(10)
    affinity: str  # 'INTEGER' | 'REAL' | 'TEXT' | 'BLOB' | 'NUMERIC' | 'NONE'


@dataclass
class CreateTable(Statement):
    table: str
    columns: List[ColumnDef] = field(default_factory=list)


@dataclass
class Insert(Statement):
    table: str
    columns: Optional[List[str]]  # None = 未指定列清单
    rows: List[List[Expr]] = field(default_factory=list)


@dataclass
class OrderItem:
    expr: Expr  # 列引用或序号(ORDINAL)
    desc: bool = False


@dataclass
class Select(Statement):
    projections: List[Expr] = field(default_factory=list)
    table: Optional[str] = None  # None = 无 FROM(常量投影)
    where: Optional[Expr] = None
    order_by: List[OrderItem] = field(default_factory=list)
    limit: Optional[int] = None

"""SQL AST 定义。

覆盖 CREATE TABLE / INSERT / UPDATE / DELETE / SELECT / CREATE INDEX /
DROP INDEX 以及子需求 1 的表达式系统:字面量、列引用、算术(+ - * / % ||)、
比较(= != <> < <= > >= IS IS NOT)、布尔组合(AND/OR/NOT)、ISNULL/NOTNULL、
CAST、标量函数、LIKE/GLOB、IN、BETWEEN、CASE、COLLATE 后缀。SELECT 支持
WHERE/ORDER BY/LIMIT/OFFSET/DISTINCT。CREATE TABLE 支持列级与表级约束
(PRIMARY KEY / UNIQUE / NOT NULL / CHECK / DEFAULT)。

范围外特性(连接、子查询、聚合、视图、触发器、事务、外键级联)不在此处建模。
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
    orig_name: str = ""  # 声明时的原始大小写(用于错误文本)
    type_name: str = ""  # 原始类型名,如 INTEGER / VARCHAR(10)
    affinity: str = "BLOB"  # 'INTEGER' | 'REAL' | 'TEXT' | 'BLOB' | 'NUMERIC' | 'NONE'
    collation: str = "BINARY"  # 列级 COLLATE,默认 BINARY
    default: "Optional[Value]" = None  # DEFAULT 字面量(未指定 → None)
    not_null: bool = False  # NOT NULL 约束
    primary_key: bool = False  # 列级 PRIMARY KEY
    unique: bool = False  # 列级 UNIQUE
    check: "Optional[Tuple[Expr, str]]" = None  # CHECK 约束:(表达式, 原始文本)


@dataclass
class TableConstraint:
    """表级约束(PRIMARY KEY / UNIQUE / CHECK)。"""

    kind: str  # 'PRIMARY KEY' | 'UNIQUE' | 'CHECK'
    columns: List[str] = field(default_factory=list)  # PK/UNIQUE 的列(大写)
    orig_columns: List[str] = field(default_factory=list)  # 原始大小写
    check_expr: Optional[Expr] = None  # CHECK 表达式
    check_raw: str = ""  # CHECK 原始文本


@dataclass
class CreateTable(Statement):
    table: str
    orig_name: str = ""  # 原始大小写(错误文本用)
    columns: List[ColumnDef] = field(default_factory=list)
    constraints: List[TableConstraint] = field(default_factory=list)


@dataclass
class IndexColumn:
    name: str  # 大写
    orig_name: str = ""  # 原始大小写
    collation: str = "BINARY"


@dataclass
class CreateIndex(Statement):
    name: str
    orig_name: str = ""  # 原始大小写(错误文本用)
    table: str = ""
    columns: List[IndexColumn] = field(default_factory=list)
    unique: bool = False


@dataclass
class DropIndex(Statement):
    name: str


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

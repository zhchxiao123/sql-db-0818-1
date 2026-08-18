"""内存表存储与目录。

Value 表示:
- int    → INTEGER
- float  → REAL
- str    → TEXT
- bytes  → BLOB
- None   → NULL

列类型 → 亲和(affinity)按 SQLite 规则判定;插入时按亲和做存储类转换。
本子集不实现索引(含 PRIMARY KEY 唯一性)、事务与持久化。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

Value = Union[int, float, str, bytes, None]

# 亲和常量
AFF_INTEGER = "INTEGER"
AFF_REAL = "REAL"
AFF_TEXT = "TEXT"
AFF_BLOB = "BLOB"
AFF_NUMERIC = "NUMERIC"
AFF_NONE = "NONE"


class SqlError(Exception):
    """执行期错误(statement error 记录期望的失败类型)。"""


# ---------------------------------------------------------------- 数值文本解析
# SQLite 把文本转数字:解析数字前缀,失败返回 None(调用方按 0 处理)。
_FLOAT_RE = re.compile(r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def parse_numeric_prefix(text: str) -> Optional[Value]:
    """按 SQLite sqlite3AtoF 语义解析文本的数字前缀。"""
    if not isinstance(text, str):
        return None
    m = _FLOAT_RE.match(text)
    if not m:
        return None
    raw = m.group(0)
    if any(c in raw for c in ".eE"):
        try:
            return float(raw)
        except ValueError:
            return None
    try:
        return int(raw)
    except ValueError:
        return None


def numeric_value(value: Value) -> Value:
    """把值转成数值(算术/比较语境)。文本按前缀解析,失败为 0。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        v = parse_numeric_prefix(value.decode("utf-8", "replace"))
        return 0 if v is None else v
    v = parse_numeric_prefix(value)
    return 0 if v is None else v


# ---------------------------------------------------------------- 亲和判定
def affinity_of_type(type_name: str) -> str:
    """根据声明的列类型判定亲和(SQLite 规则)。"""
    t = (type_name or "").upper()
    if "INT" in t:
        return AFF_INTEGER
    if any(k in t for k in ("CHAR", "CLOB", "TEXT")):
        return AFF_TEXT
    if "BLOB" in t or t == "":
        return AFF_BLOB
    if any(k in t for k in ("REAL", "FLOA", "DOUB")):
        return AFF_REAL
    return AFF_NUMERIC


def apply_affinity(value: Value, affinity: str) -> Value:
    """把值按列亲和做存储类转换(SQLite 规则)。NULL/BLOB 原样保留。"""
    if value is None:
        return None
    if affinity in (AFF_NONE, AFF_BLOB):
        return value
    if isinstance(value, bytes):
        return value  # 亲和转换不作用于 BLOB
    if affinity == AFF_TEXT:
        if isinstance(value, str):
            return value
        return text_of_value(value)
    # 数值亲和:INTEGER / REAL / NUMERIC
    if isinstance(value, str):
        num = parse_numeric_prefix(value)
        if num is None:
            return value  # 无法解析的文本保留为 TEXT
        value = num
    if affinity == AFF_REAL:
        return float(value)
    # INTEGER / NUMERIC:整数值 → int,否则保留数值
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def text_of_value(value: Value) -> str:
    """把非文本值转成文本表示(CAST AS TEXT / TEXT 亲和 / || 连接)。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, int):
        return str(value)
    # float → SQLite 的文本表示(%.15g 风格)
    return format_float(value)


def format_float(f: float) -> str:
    """SQLite 浮点转文本:%.15g 风格 + 整数形浮点补 .0。"""
    if f == 0:
        return "0.0" if f == 0 else "-0.0"
    s = "%.15g" % f
    if "e" in s or "E" in s:
        mant, _, exp = s.replace("E", "e").partition("e")
        if "." not in mant:
            mant += ".0"
        exp_sign = "+" if not exp.startswith(("-", "+")) else exp[0]
        exp_digits = exp.lstrip("+-")
        exp_digits = exp_digits.zfill(2) if len(exp_digits) < 2 else exp_digits
        return f"{mant}e{exp_sign}{exp_digits}"
    if "." not in s:
        s += ".0"
    return s


# ---------------------------------------------------------------- 比较
def compare_values(a: Value, b: Value) -> int:
    """SQLite 存储类比较:NULL < 数值 < 文本 < BLOB。

    Args:
        a, b: 待比较值(已按亲和转换过)。

    Returns:
        -1 / 0 / 1。
    """
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    a_num = isinstance(a, (int, float))
    b_num = isinstance(b, (int, float))
    if a_num and b_num:
        return (a > b) - (a < b)
    a_txt = isinstance(a, str)
    b_txt = isinstance(b, str)
    a_blob = isinstance(a, bytes)
    b_blob = isinstance(b, bytes)

    def _class(is_num, is_txt, is_blob):
        return 0 if is_num else (1 if is_txt else 2)

    ca, cb = _class(a_num, a_txt, a_blob), _class(b_num, b_txt, b_blob)
    if ca != cb:
        return (ca > cb) - (ca < cb)
    if a_txt and b_txt:
        return (a > b) - (a < b)
    if a_blob and b_blob:
        return (a > b) - (a < b)
    return (str(a) > str(b)) - (str(a) < str(b))


# ---------------------------------------------------------------- 目录
@dataclass
class Column:
    name: str  # 大写归一化
    type_name: str  # 原始类型名
    affinity: str = AFF_NONE  # 由类型名推导


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    rows: List[List[Value]] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise SqlError(f"未知列 {name}")


@dataclass
class Database:
    """一个数据库实例:持有全部表。每个 sqllogictest 测试文件独立一个实例。"""

    tables: Dict[str, Table] = field(default_factory=dict)

    def create_table(self, name: str, columns: List[Column]) -> None:
        if name in self.tables:
            raise SqlError(f"表 {name} 已存在")
        self.tables[name] = Table(name=name, columns=columns)

    def get_table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            raise SqlError(f"未知表 {name}") from None

    def insert(self, name: str, columns: Optional[List[str]], rows: List[List[Value]]) -> None:
        table = self.get_table(name)
        if columns is None:
            indexes = list(range(len(table.columns)))
        else:
            indexes = [table.column_index(c) for c in columns]
            if len(set(indexes)) != len(indexes):
                raise SqlError("INSERT 列清单存在重复列")
        for row in rows:
            if len(row) != len(indexes):
                raise SqlError(f"INSERT 值数 {len(row)} 与列数 {len(indexes)} 不一致")
            coerced = [None] * len(table.columns)  # 未指定的列填 NULL
            for i, idx in enumerate(indexes):
                coerced[idx] = apply_affinity(row[i], table.columns[idx].affinity)
            table.rows.append(coerced)

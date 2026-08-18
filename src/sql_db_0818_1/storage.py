"""内存表存储与目录。

Value 表示:
- int    → INTEGER
- float  → REAL
- str    → TEXT
- bytes  → BLOB
- None   → NULL

列类型 → 亲和(affinity)按 SQLite 规则判定;插入时按亲和做存储类转换。
本子集不实现索引(含 PRIMARY KEY 唯一性)、事务与持久化。

子需求 1 新增:CAST 语义、collation(排序规则)比较、LIKE/GLOB 匹配、
C 风格取模/整数除法、SQLite 浮点文本格式化(%.15g 后处理)。
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

# int64 边界(SQLite 整数算术溢出转 REAL;CAST 到 INTEGER 时截断)
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

# collation 常量
COLL_BINARY = "BINARY"
COLL_NOCASE = "NOCASE"
COLL_RTRIM = "RTRIM"
_VALID_COLLATIONS = {COLL_BINARY, COLL_NOCASE, COLL_RTRIM}


class SqlError(Exception):
    """执行期错误(statement error 记录期望的失败类型)。"""


class SqlFunctionError(Exception):
    """函数参数错误(与 sqlite 的 wrong number of arguments 对应)。"""


# ---------------------------------------------------------------- 数值文本解析
# SQLite 把文本转数字:解析数字前缀,失败返回 None(调用方按 0 处理)。
# 与 sqlite3AtoF 对齐:可选空白、符号、整数/小数、指数。
_FLOAT_RE = re.compile(r"^[ \t\n\r\f\v]*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# CAST AS INTEGER 用:只解析整数前缀(遇到 . e 或非数字即停),与 sqlite3Atoi64 对齐
_INT_RE = re.compile(r"^[ \t\n\r\f\v]*[+-]?\d+")


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
        v = int(raw)
    except ValueError:
        return None
    return clamp_int64(v)


def parse_int_prefix(text: str) -> int:
    """CAST AS INTEGER 的文本解析:整数前缀,失败返回 0。"""
    if not isinstance(text, str):
        return 0
    m = _INT_RE.match(text)
    if not m:
        return 0
    try:
        return clamp_int64(int(m.group(0)))
    except ValueError:
        return 0


def clamp_int64(v: int) -> int:
    """把整数截断到 int64 范围(SQLite 溢出行为)。"""
    if v < INT64_MIN:
        return INT64_MIN
    if v > INT64_MAX:
        return INT64_MAX
    return v


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


def is_numeric_text(value: Value) -> bool:
    """文本是否可解析为数字(用于 sign() 等函数区分 NULL 与 0)。"""
    if isinstance(value, str):
        return parse_numeric_prefix(value) is not None
    if isinstance(value, bytes):
        return parse_numeric_prefix(value.decode("utf-8", "replace")) is not None
    return True


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


# ---------------------------------------------------------------- CAST 语义
def cast_value(value: Value, affinity: str) -> Value:
    """CAST(expr AS type) 的转换语义(与列亲和不同)。

    - CAST 到 NUMERIC 与列 NUMERIC 亲和不同:不可解析文本 → 0;REAL 保持 REAL。
    - CAST 到 BLOB:数字/文本 → 文本再编码为 bytes(列 BLOB 亲和则原样保留)。
    - CAST 到 INTEGER:整数前缀解析(忽略 . e 与非数字),失败 → 0。
    """
    if value is None:
        return None
    if affinity == AFF_TEXT:
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return text_of_value(value)
    if affinity == AFF_BLOB:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return text_of_value(value).encode("utf-8")
    if affinity == AFF_REAL:
        if isinstance(value, (int, float)):
            return float(value)
        v = parse_numeric_prefix(_as_text(value))
        return 0.0 if v is None else float(v)
    if affinity == AFF_INTEGER:
        if isinstance(value, int):
            return clamp_int64(value)
        if isinstance(value, float):
            return clamp_int64(int(value))
        return parse_int_prefix(_as_text(value))
    # NUMERIC
    if isinstance(value, (int, float)):
        return value  # 已数值:保持不变(2.0 保持 REAL)
    v = parse_numeric_prefix(_as_text(value))
    return 0 if v is None else v


def _as_text(value: Value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, float):
        return format_float(value)
    return str(value)


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
        return "0.0"  # -0.0 也输出 0.0(SQLite CAST(-0.0 AS TEXT) = '0.0')
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
def ascii_fold(c: str) -> str:
    """ASCII 大小写折叠(仅 A-Z → a-z;SQLite NOCASE/LIKE 只折叠 ASCII)。"""
    if "A" <= c <= "Z":
        return chr(ord(c) + 32)
    return c


def ascii_upper(s: str) -> str:
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in s)


def ascii_lower(s: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def compare_text(a: str, b: str, collation: str = COLL_BINARY) -> int:
    """按 collation 比较两个文本。"""
    if collation == COLL_NOCASE:
        a = ascii_lower(a)
        b = ascii_lower(b)
    elif collation == COLL_RTRIM:
        a = a.rstrip(" ")
        b = b.rstrip(" ")
    return (a > b) - (a < b)


def compare_values(a: Value, b: Value, collation: str = COLL_BINARY) -> int:
    """SQLite 存储类比较:NULL < 数值 < 文本 < BLOB。

    Args:
        a, b: 待比较值(已按亲和转换过)。
        collation: 文本-文本比较使用的排序规则(BINARY/NOCASE/RTRIM)。

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
        return compare_text(a, b, collation)
    if a_blob and b_blob:
        return (a > b) - (a < b)
    return (str(a) > str(b)) - (str(a) < str(b))


# ---------------------------------------------------------------- LIKE / GLOB
def _like_match_tokens(pattern: str, escape: Optional[str]):
    """把 LIKE 模式转成 token 序列。

    token: ('%',) 任意序列;('_',) 单字符;('lit', c) 字面字符(已折叠处理)。
    """
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if escape is not None and c == escape:
            # 转义字符后的下一个字符按字面处理;若转义符是模式末尾,SQLite 报错
            if i + 1 >= n:
                raise SqlError("LIKE pattern ends with escape character")
            tokens.append(("lit", pattern[i + 1]))
            i += 2
            continue
        if c == "%":
            tokens.append(("%",))
        elif c == "_":
            tokens.append(("_",))
        else:
            tokens.append(("lit", c))
        i += 1
    return tokens


def _like_match_impl(value: str, pattern: str, escape: Optional[str]) -> bool:
    """LIKE 匹配(ASCII 大小写不敏感;% 任意序列,_ 单字符;支持 ESCAPE)。"""
    tokens = _like_match_tokens(pattern, escape)
    # 迭代 + 回溯,模拟 SQLite patternCompare
    vi = 0
    ti = 0
    star_ti = -1  # 最近一次 % 的位置
    star_vi = 0
    nv = len(value)
    while vi < nv:
        if ti < len(tokens):
            tok = tokens[ti]
            if tok[0] == "%":
                star_ti = ti
                star_vi = vi
                ti += 1
                continue
            if tok[0] == "_":
                vi += 1
                ti += 1
                continue
            # 字面字符:ASCII 折叠后比较
            if ascii_fold(tok[1]) == ascii_fold(value[vi]):
                vi += 1
                ti += 1
                continue
        # 不匹配:若有 % 星号则回溯
        if star_ti >= 0:
            star_vi += 1
            vi = star_vi
            ti = star_ti + 1
            continue
        return False
    # 值已耗尽:模式剩余必须是 % 序列
    while ti < len(tokens) and tokens[ti][0] == "%":
        ti += 1
    return ti == len(tokens)


def like_match(value: Value, pattern: Value, escape: Optional[Value] = None) -> Optional[int]:
    """LIKE 运算符。

    规则(与 sqlite3 3.46.1 实测一致):
    - 任一操作数为 NULL → NULL
    - 任一操作数为 BLOB → 0(SQLite 对 BLOB 操作数恒返回 false)
    - 其余转文本,ASCII 大小写不敏感匹配
    """
    if value is None or pattern is None:
        return None
    if isinstance(value, bytes) or isinstance(pattern, bytes):
        return 0
    esc: Optional[str] = None
    if escape is not None:
        if escape is None:
            return None
        if isinstance(escape, bytes):
            return 0
        esc = text_of_value(escape)
        if len(esc) != 1:
            raise SqlError("ESCAPE expression must be a single character")
    v = text_of_value(value)
    p = text_of_value(pattern)
    return 1 if _like_match_impl(v, p, esc) else 0


def glob_match(value: Value, pattern: Value) -> Optional[int]:
    """GLOB 运算符:大小写敏感;* 任意序列、? 单字符、[...] 字符类。"""
    if value is None or pattern is None:
        return None
    v = text_of_value(value)
    p = text_of_value(pattern)
    return 1 if _glob_match_impl(v, p) else 0


def _glob_class_match(pattern: str, i: int) -> tuple:
    """解析 GLOB 的 [...] 字符类,返回 (predicate, 结束下标)。

    predicate(ch) → bool;失败(未闭合)返回 (None, i)。
    """
    n = len(pattern)
    j = i + 1  # 跳过 '['
    negate = False
    if j < n and pattern[j] in "^!":
        negate = True
        j += 1
    chars: List[str] = []
    ranges: List[tuple] = []
    first = True
    while j < n:
        c = pattern[j]
        if c == "]" and not first:
            break
        first = False
        # 范围:a-z
        if j + 2 < n and pattern[j + 1] == "-" and pattern[j + 2] != "]":
            ranges.append((c, pattern[j + 2]))
            j += 3
            continue
        chars.append(c)
        j += 1
    else:
        return None, i  # 未找到闭合 ']':'[' 按字面处理
    end = j + 1  # 跳过 ']'

    def pred(ch: str) -> bool:
        hit = ch in chars or any(lo <= ch <= hi for lo, hi in ranges)
        return (not hit) if negate else hit

    return pred, end


def _glob_match_impl(value: str, pattern: str) -> bool:
    """GLOB 匹配:大小写敏感;* ? [...] 与 sqlite3_strglob 对齐。"""
    vi = 0
    pi = 0
    star_pi = -1
    star_vi = 0
    nv = len(value)
    np_ = len(pattern)
    while vi < nv:
        if pi < np_:
            c = pattern[pi]
            if c == "*":
                star_pi = pi
                star_vi = vi
                pi += 1
                continue
            if c == "?":
                vi += 1
                pi += 1
                continue
            if c == "[":
                pred, end = _glob_class_match(pattern, pi)
                if pred is not None:
                    if pred(value[vi]):
                        vi += 1
                        pi = end
                        continue
                else:
                    # 未闭合的 '[':按字面比较
                    if value[vi] == "[":
                        vi += 1
                        pi += 1
                        continue
            elif value[vi] == c:
                vi += 1
                pi += 1
                continue
        if star_pi >= 0:
            star_vi += 1
            vi = star_vi
            pi = star_pi + 1
            continue
        return False
    while pi < np_ and pattern[pi] == "*":
        pi += 1
    return pi == np_


# ---------------------------------------------------------------- 圆整 / substr
def sqlite_round(x: float, n: int) -> float:
    """SQLite round():n==0 用 ±0.5 截断(远离零);n!=0 用 %.*f(银行家舍入于二进制值)。

    n < 0 视为 0(SQLite 3.46 实测 round(123.456,-1) = 123.0)。
    """
    if n < 0:
        n = 0
    if n == 0 and -4503599627370496.0 <= x <= 4503599627370496.0:
        return float(int(x + (0.5 if x >= 0 else -0.5)))
    s = "%.*f" % (n, x)
    return float(s)


def sqlite_substr(s, y: int, z: Optional[int]):
    """SQLite substr():1 起始;负 y 从右数;负 z 取 y 之前 |z| 个字符。

    与 sqlite3 3.46.1 实测对齐:
    - substr('abcdef',0,5) = 'abcd'(y<1 时 z 相应缩减)
    - substr('abcdef',0) = 'abcdef'(缺省 z 到末尾)
    - substr('hello',-99,2) = ''(起始越界)
    """
    n = len(s)
    p1 = y
    if p1 < 0:
        p1 = n + p1 + 1
    if z is None:
        # 到末尾
        if p1 < 1:
            p1 = 1
        if p1 > n:
            return s[:0]
        return s[p1 - 1 :]
    p2 = z
    if p2 < 0:
        # y 之前的 |z| 个字符
        k = -p2
        start = p1 - k
        end = p1 - 1
        if start < 1:
            start = 1
        if end < start or start > n:
            return s[:0]
        if end > n:
            end = n
        return s[start - 1 : end]
    if p1 < 1:
        p2 += p1 - 1
        p1 = 1
    if p2 < 0:
        p2 = 0
    if p1 > n:
        return s[:0]
    p2 = min(p2, n - p1 + 1)
    return s[p1 - 1 : p1 - 1 + p2]


# ---------------------------------------------------------------- 目录
@dataclass
class Column:
    name: str  # 大写归一化
    orig_name: str = ""  # 声明时的原始大小写(用于错误文本)
    type_name: str = ""  # 原始类型名
    affinity: str = AFF_NONE  # 由类型名推导
    collation: str = COLL_BINARY  # 列级 COLLATE,默认 BINARY
    default: Optional[Value] = None  # DEFAULT 字面量(未指定 → None)
    not_null: bool = False  # NOT NULL 约束
    primary_key: bool = False  # 列级 PRIMARY KEY
    unique: bool = False  # 列级 UNIQUE
    check_expr: Optional[Any] = None  # CHECK 表达式(AST,惰性求值)
    check_raw: str = ""  # CHECK 原始文本(错误消息用)


@dataclass
class TableConstraintInfo:
    """表级约束(PRIMARY KEY / UNIQUE / CHECK)。"""

    kind: str  # 'PRIMARY KEY' | 'UNIQUE' | 'CHECK'
    columns: List[str] = field(default_factory=list)  # 大写列名
    orig_columns: List[str] = field(default_factory=list)  # 原始大小写
    check_expr: Optional[Any] = None  # CHECK 表达式
    check_raw: str = ""  # CHECK 原始文本


@dataclass
class Index:
    """CREATE INDEX 记录的索引(仅元数据;查询不使用索引加速)。"""

    name: str  # 大写归一化
    table: str
    orig_name: str = ""  # 原始大小写
    columns: List[Column] = field(default_factory=list)
    unique: bool = False


@dataclass
class Table:
    name: str
    orig_name: str = ""  # 原始大小写(错误文本用)
    columns: List[Column] = field(default_factory=list)
    rows: List[List[Value]] = field(default_factory=list)
    constraints: List[TableConstraintInfo] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise SqlError(f"no such column: {name}")


@dataclass
class Database:
    """一个数据库实例:持有全部表与索引。每个 sqllogictest 测试文件独立一个实例。"""

    tables: Dict[str, Table] = field(default_factory=dict)
    indexes: Dict[str, Index] = field(default_factory=dict)

    def create_table(
        self,
        name: str,
        columns: List[Column],
        constraints: Optional[List[TableConstraintInfo]] = None,
        orig_name: str = "",
    ) -> None:
        if name in self.tables:
            raise SqlError(f"table {name} already exists")
        self.tables[name] = Table(
            name=name,
            orig_name=orig_name or name,
            columns=columns,
            constraints=constraints or [],
        )

    def get_table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            raise SqlError(f"no such table: {name}") from None

    # ------------------------------------------------------------ 索引
    def create_index(self, index: Index) -> None:
        if index.name in self.indexes:
            raise SqlError(f"index {index.orig_name} already exists")
        # 表与列必须存在
        table = self.get_table(index.table)
        for col in index.columns:
            table.column_index(col.name)
        # UNIQUE 索引:已有数据不得违反唯一性(SQLite 在创建时即校验)
        if index.unique:
            idx_cols = [c.name for c in index.columns]
            idx_orig = [c.orig_name or c.name for c in index.columns]
            idx_colls = [c.collation for c in index.columns]
            for i, row in enumerate(table.rows):
                if self._unique_conflict(
                    table, row, idx_cols, idx_orig, exclude_idx=i, collations=idx_colls
                ):
                    raise self._unique_error(table, idx_orig)
        self.indexes[index.name] = index

    def get_index(self, name: str) -> Index:
        try:
            return self.indexes[name]
        except KeyError:
            raise SqlError(f"no such index: {name}") from None

    def drop_index(self, name: str) -> None:
        if name not in self.indexes:
            raise SqlError(f"no such index: {name}")
        del self.indexes[name]

    def indexes_for(self, table_name: str) -> List[Index]:
        return [idx for idx in self.indexes.values() if idx.table == table_name]

    # ------------------------------------------------------------ 约束检查
    def _unique_conflict(
        self,
        table: Table,
        row: List[Value],
        col_names: List[str],
        orig_col_names: List[str],
        exclude_idx: Optional[int] = None,
        collations: Optional[List[str]] = None,
    ) -> bool:
        """row 与表内其他行在 (col_names) 上是否唯一冲突(NULL 不参与比较)。

        collations 缺省取表列的 collation;索引可显式传入索引列的 collation
        (如 CREATE UNIQUE INDEX ... ON t(a COLLATE NOCASE))。
        """
        if any(row[table.column_index(c)] is None for c in col_names):
            return False  # UNIQUE 允许任意多 NULL
        if collations is None:
            colls = [table.columns[table.column_index(c)].collation for c in col_names]
        else:
            colls = collations
        for i, other in enumerate(table.rows):
            if exclude_idx is not None and i == exclude_idx:
                continue
            if all(
                compare_values(
                    row[table.column_index(c)], other[table.column_index(c)], coll
                )
                == 0
                for c, coll in zip(col_names, colls)
            ):
                return True
        return False

    def _unique_error(self, table: Table, orig_col_names: List[str]) -> SqlError:
        tname = table.orig_name or table.name
        cols = ", ".join(f"{tname}.{c}" for c in orig_col_names)
        return SqlError(f"UNIQUE constraint failed: {cols}")

    def check_row(
        self,
        table: Table,
        row: List[Value],
        eval_check,
        exclude_idx: Optional[int] = None,
    ) -> None:
        """对一行做约束检查:NOT NULL → CHECK → UNIQUE(列级/表级/唯一索引)。

        eval_check(cols, row, expr) → 值;由 executor 注入(避免循环导入)。
        """
        # 1. NOT NULL(列级)
        for i, col in enumerate(table.columns):
            if col.not_null and row[i] is None:
                tname = table.orig_name or table.name
                raise SqlError(
                    f"NOT NULL constraint failed: {tname}.{col.orig_name or col.name}"
                )
        # 2. CHECK(列级 + 表级),NULL 通过
        for i, col in enumerate(table.columns):
            if col.check_expr is not None and row[i] is not None:
                if not eval_check(table.columns, row, col.check_expr):
                    raise SqlError(f"CHECK constraint failed: {col.check_raw}")
        for tc in table.constraints:
            if tc.kind == "CHECK" and tc.check_expr is not None:
                if not eval_check(table.columns, row, tc.check_expr):
                    raise SqlError(f"CHECK constraint failed: {tc.check_raw}")
        # 3. UNIQUE(列级 PRIMARY KEY/UNIQUE + 表级 + 唯一索引)
        for i, col in enumerate(table.columns):
            if col.unique or col.primary_key:
                if self._unique_conflict(
                    table, row, [col.name], [col.orig_name or col.name], exclude_idx
                ):
                    raise self._unique_error(table, [col.orig_name or col.name])
        for tc in table.constraints:
            if tc.kind in ("PRIMARY KEY", "UNIQUE") and tc.columns:
                if self._unique_conflict(
                    table, row, tc.columns, tc.orig_columns, exclude_idx
                ):
                    raise self._unique_error(table, tc.orig_columns)
        for idx in self.indexes_for(table.name):
            if idx.unique:
                idx_cols = [c.name for c in idx.columns]
                idx_orig = [c.orig_name or c.name for c in idx.columns]
                idx_colls = [c.collation for c in idx.columns]
                if self._unique_conflict(
                    table, row, idx_cols, idx_orig, exclude_idx, collations=idx_colls
                ):
                    raise self._unique_error(table, idx_orig)

    def insert(
        self,
        name: str,
        columns: Optional[List[str]],
        rows: List[List[Value]],
        eval_check=None,
    ) -> None:
        table = self.get_table(name)
        if columns is None:
            indexes = list(range(len(table.columns)))
        else:
            indexes = [table.column_index(c) for c in columns]
            if len(set(indexes)) != len(indexes):
                raise SqlError("INSERT column list contains duplicate column")
        # 先构造并校验全部行,任一行违反则整条失败(SQLite 原子语义)
        prepared: List[List[Value]] = []
        for row in rows:
            if len(row) != len(indexes):
                raise SqlError(
                    f"INSERT has {len(row)} values but {len(indexes)} columns were supplied"
                )
            coerced = [None] * len(table.columns)  # 未指定的列填 DEFAULT/NULL
            for i, idx in enumerate(indexes):
                coerced[idx] = apply_affinity(row[i], table.columns[idx].affinity)
            # 未指定列:有 DEFAULT 则用 DEFAULT(按列亲和转换),否则 NULL
            for idx in range(len(table.columns)):
                if idx not in indexes:
                    col = table.columns[idx]
                    if col.default is not None:
                        coerced[idx] = apply_affinity(col.default, col.affinity)
            # INTEGER PRIMARY KEY:NULL → 自动分配 max+1(SQLite rowid 语义)
            for i, col in enumerate(table.columns):
                if col.primary_key and col.affinity == AFF_INTEGER and coerced[i] is None:
                    vals = [r[i] for r in table.rows if isinstance(r[i], int)]
                    vals += [r[i] for r in prepared if isinstance(r[i], int)]
                    coerced[i] = (max(vals) + 1) if vals else 1
            if eval_check is not None:
                self.check_row(table, coerced, eval_check)
            prepared.append(coerced)
        table.rows.extend(prepared)

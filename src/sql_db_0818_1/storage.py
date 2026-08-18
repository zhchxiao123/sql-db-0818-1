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
    type_name: str  # 原始类型名
    affinity: str = AFF_NONE  # 由类型名推导
    collation: str = COLL_BINARY  # 列级 COLLATE,默认 BINARY


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    rows: List[List[Value]] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise SqlError(f"no such column: {name}")


@dataclass
class Database:
    """一个数据库实例:持有全部表。每个 sqllogictest 测试文件独立一个实例。"""

    tables: Dict[str, Table] = field(default_factory=dict)

    def create_table(self, name: str, columns: List[Column]) -> None:
        if name in self.tables:
            raise SqlError(f"table {name} already exists")
        self.tables[name] = Table(name=name, columns=columns)

    def get_table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            raise SqlError(f"no such table: {name}") from None

    def insert(self, name: str, columns: Optional[List[str]], rows: List[List[Value]]) -> None:
        table = self.get_table(name)
        if columns is None:
            indexes = list(range(len(table.columns)))
        else:
            indexes = [table.column_index(c) for c in columns]
            if len(set(indexes)) != len(indexes):
                raise SqlError("INSERT column list contains duplicate column")
        for row in rows:
            if len(row) != len(indexes):
                raise SqlError(
                    f"INSERT has {len(row)} values but {len(indexes)} columns were supplied"
                )
            coerced = [None] * len(table.columns)  # 未指定的列填 NULL
            for i, idx in enumerate(indexes):
                coerced[idx] = apply_affinity(row[i], table.columns[idx].affinity)
            table.rows.append(coerced)

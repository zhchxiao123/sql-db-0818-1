#!/usr/bin/env python3
"""生成 test/ 下 29 个验收夹具(子需求 1 + 子需求 2 + 子需求 4)。

口径:官方 sqllogictest(与 child[0] 同一 vendor commit)中的场景按本模块支持范围
重构;每条 query 记录的期望值由 sqlite3 3.46.1 实际执行产出;statement error
模式按本引擎的真实报错文本书写(运行器以 re.search 匹配)。

子需求 1:types/cast/expr1-3/func1-5/like/in/null/collate1-5(18 文件)
子需求 2:insert1/update1/delete1/select2-5(7 文件,DML + SELECT 进阶)
子需求 4:index1-2/table1-2(4 文件,索引与约束)

用法:python3 tools/gen_fixtures.py
输出:test/*.test(见上)
同时更新 test/FIXTURES.md。
"""

import hashlib
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST = REPO / "test"


def fmt_value(v, t):
    """把 sqlite3 返回的值按 sqllogictest 列类型格式化为期望文本。"""
    if v is None:
        return "NULL"
    if t in ("I",):
        if isinstance(v, float):
            return str(int(v))
        if isinstance(v, int):
            return str(v)
        return str(int(float(v)))
    if t in ("R", "F"):
        return "%.3f" % float(v)
    # T
    if isinstance(v, bytes):
        s = v.decode("utf-8", "replace")
    elif isinstance(v, float):
        s = format_float(v)
    else:
        s = str(v)
    if s == "":
        return "(empty)"
    return "".join(c if " " <= c <= "~" else "@" for c in s)


def format_float(f):
    if f == 0:
        return "0.0"
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


def run_sqlite(sql):
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


def query_hash(rows, types, sort_mode):
    """按运行器逻辑生成哈希期望。"""
    fmt_rows = [[fmt_value(v, types[i]) for i, v in enumerate(row)] for row in rows]
    if sort_mode == "valuesort":
        flat = sorted(v for row in fmt_rows for v in row)
        ordered = flat
    elif sort_mode == "rowsort":
        ordered = [v for row in sorted(tuple(r) for r in fmt_rows) for v in row]
    else:
        ordered = [v for row in fmt_rows for v in row]
    return hashlib.md5(("\n".join(ordered) + "\n").encode("utf-8")).hexdigest()


class FileBuilder:
    """每个 .test 文件一个持久连接:statement 与 query 共享同一数据库状态。"""

    def __init__(self, name):
        self.name = name
        self.recs = []
        self.conn = sqlite3.connect(":memory:")
        self.cur = self.conn.cursor()

    def stmt_ok(self, sql):
        self.recs.append(f"statement ok\n{sql}\n\n")
        self.cur.execute(sql)
        self.conn.commit()

    def stmt_err(self, sql, pattern):
        self.recs.append(f"statement error {pattern}\n{sql}\n\n")

    def query(self, types, sql, sort_mode="nosort", label=None):
        self.cur.execute(sql)
        rows = self.cur.fetchall()
        header = f"query {types}"
        if sort_mode != "nosort":
            header += f" {sort_mode}"
        if label:
            header += f" {label}"
        self.recs.append(f"{header}\n{sql}\n----\n")
        fmt_rows = [[fmt_value(v, types[i]) for i, v in enumerate(row)] for row in rows]
        for row in fmt_rows:
            for v in row:
                self.recs.append(v + "\n")
        self.recs.append("\n")

    def query_hash_rec(self, types, sql, sort_mode="nosort", label=None):
        self.cur.execute(sql)
        rows = self.cur.fetchall()
        header = f"query {types}"
        if sort_mode != "nosort":
            header += f" {sort_mode}"
        if label:
            header += f" {label}"
        self.recs.append(f"{header}\n{sql}\n----\n")
        nvals = sum(len(r) for r in rows)
        self.recs.append(f"{nvals} values hashing to {query_hash(rows, types, sort_mode)}\n\n")

    def close(self):
        self.conn.close()


def build_records():
    """返回 {文件名: FileBuilder}。"""
    # ---------------- 官方 t1 数据(select1.test 前 31 条,逐字) ----------------
    t1_create = "CREATE TABLE t1(a INTEGER, b INTEGER, c INTEGER, d INTEGER, e INTEGER)"
    t1_inserts = [
        "INSERT INTO t1(e,c,b,d,a) VALUES(103,102,100,101,104)",
        "INSERT INTO t1(a,c,d,e,b) VALUES(107,106,108,109,105)",
        "INSERT INTO t1(e,d,b,a,c) VALUES(110,114,112,111,113)",
        "INSERT INTO t1(d,c,e,a,b) VALUES(116,119,117,115,118)",
        "INSERT INTO t1(c,d,b,e,a) VALUES(123,122,124,120,121)",
        "INSERT INTO t1(a,d,b,e,c) VALUES(127,128,129,126,125)",
        "INSERT INTO t1(e,c,a,d,b) VALUES(132,134,131,133,130)",
        "INSERT INTO t1(a,d,b,e,c) VALUES(138,136,139,135,137)",
        "INSERT INTO t1(e,c,d,a,b) VALUES(144,141,140,142,143)",
        "INSERT INTO t1(b,a,e,d,c) VALUES(145,149,146,148,147)",
        "INSERT INTO t1(b,c,a,d,e) VALUES(151,150,153,154,152)",
        "INSERT INTO t1(c,e,a,d,b) VALUES(155,157,159,156,158)",
        "INSERT INTO t1(c,b,a,d,e) VALUES(161,160,163,164,162)",
        "INSERT INTO t1(b,d,a,e,c) VALUES(167,169,168,165,166)",
        "INSERT INTO t1(d,b,c,e,a) VALUES(171,170,172,173,174)",
        "INSERT INTO t1(e,c,a,d,b) VALUES(177,176,179,178,175)",
        "INSERT INTO t1(b,e,a,d,c) VALUES(181,180,182,183,184)",
        "INSERT INTO t1(c,a,b,e,d) VALUES(187,188,186,189,185)",
        "INSERT INTO t1(d,b,c,e,a) VALUES(190,194,193,192,191)",
        "INSERT INTO t1(a,e,b,d,c) VALUES(199,197,198,196,195)",
        "INSERT INTO t1(b,c,d,a,e) VALUES(200,202,203,201,204)",
        "INSERT INTO t1(c,e,a,b,d) VALUES(208,209,205,206,207)",
        "INSERT INTO t1(c,e,a,d,b) VALUES(214,210,213,212,211)",
        "INSERT INTO t1(b,c,a,d,e) VALUES(218,215,216,217,219)",
        "INSERT INTO t1(b,e,d,a,c) VALUES(223,221,222,220,224)",
        "INSERT INTO t1(d,e,b,a,c) VALUES(226,227,228,229,225)",
        "INSERT INTO t1(a,c,b,e,d) VALUES(234,231,232,230,233)",
        "INSERT INTO t1(e,b,a,c,d) VALUES(237,236,239,235,238)",
        "INSERT INTO t1(e,c,b,a,d) VALUES(242,244,240,243,241)",
        "INSERT INTO t1(e,d,c,b,a) VALUES(246,248,247,249,245)",
    ]

    files = {}

    def new_file(name):
        files[name] = FileBuilder(name)
        return files[name]

    # ================= types.test =================
    r = new_file("types")
    r.stmt_ok("CREATE TABLE t1(a, b, c, d, e)")
    r.stmt_ok("INSERT INTO t1 VALUES(1, 1.5, 'hello', x'414243', NULL)")
    r.stmt_ok("INSERT INTO t1 VALUES(-7, -2.25, '', x'', 0)")
    r.stmt_ok("INSERT INTO t1 VALUES(0, 0.0, '0', x'00', 'x')")
    r.query("TTTTT", "SELECT typeof(a), typeof(b), typeof(c), typeof(d), typeof(e) FROM t1")
    r.query("TITRT", "SELECT typeof(a), a, typeof(b), b, typeof(c) FROM t1 ORDER BY a")
    # 无类型列 → BLOB 亲和:值原样保留
    r.query("T", "SELECT typeof(a) FROM t1 WHERE a=1")
    r.query("T", "SELECT typeof(e) FROM t1 WHERE e IS NULL")
    # 显式类型 + 亲和转换
    r.stmt_ok("CREATE TABLE t2(a INTEGER, b REAL, c TEXT, d NUMERIC, e BLOB)")
    r.stmt_ok("INSERT INTO t2 VALUES('42', '1.5', 42, '3.14', 'abc')")
    r.stmt_ok("INSERT INTO t2 VALUES(3.9, 2, 1.5, 7, x'4142')")
    r.stmt_ok("INSERT INTO t2 VALUES('abc', 'zz', 99, 'no', 123)")
    r.query("TTTTT", "SELECT typeof(a), typeof(b), typeof(c), typeof(d), typeof(e) FROM t2 ORDER BY a")
    r.query("T", "SELECT typeof(a) FROM t2 WHERE a=42")
    r.query("T", "SELECT typeof(a) FROM t2 WHERE a=3")
    r.query("T", "SELECT typeof(c) FROM t2 WHERE c=42")
    r.query("T", "SELECT typeof(b) FROM t2 WHERE b=1.5")
    r.query("T", "SELECT typeof(d) FROM t2 WHERE d=3.14")
    r.query("T", "SELECT typeof(d) FROM t2 WHERE d=7")
    r.query("T", "SELECT typeof(e) FROM t2 WHERE e='abc'")
    # NUMERIC 亲和:可无损转整数的浮点 → 整数
    r.stmt_ok("CREATE TABLE t3(a NUMERIC)")
    r.stmt_ok("INSERT INTO t3 VALUES('1.5'),(2),('abc'),(3.0),('4e2')")
    r.query("TT", "SELECT typeof(a), a FROM t3 ORDER BY a")
    # REAL 亲和
    r.stmt_ok("CREATE TABLE t4(a REAL)")
    r.stmt_ok("INSERT INTO t4 VALUES(1),(2.5),('3.7'),('abc'),(4)")
    r.query("TT", "SELECT typeof(a), a FROM t4 ORDER BY a")
    # INTEGER 亲和:非整数浮点保留 REAL
    r.stmt_ok("CREATE TABLE t5(a INTEGER)")
    r.stmt_ok("INSERT INTO t5 VALUES(1.9),('2.9'),('abc'),(3.0),(4.5)")
    r.query("T", "SELECT typeof(a) FROM t5 ORDER BY a")
    # TEXT 亲和:BLOB 不转换
    r.stmt_ok("CREATE TABLE t6(a TEXT)")
    r.stmt_ok("INSERT INTO t6 VALUES(1),(2.5),(x'41'),('x'),(NULL)")
    r.query("T", "SELECT typeof(a) FROM t6 ORDER BY a")
    # 字面量:十六进制 blob、指数、边界
    r.query("T", "SELECT typeof(x'00')")
    r.query("T", "SELECT typeof(1e10)")
    r.query("R", "SELECT 1e10")
    r.query("T", "SELECT typeof(1.5e-5)")
    r.query("T", "SELECT typeof(9223372036854775807)")
    r.query("I", "SELECT 9223372036854775807")
    r.query("R", "SELECT 1.5e300")
    r.query("I", "SELECT 0")
    r.query("T", "SELECT typeof(NULL)")
    # 跨存储类比较:NULL < 数值 < 文本 < BLOB
    r.query("I", "SELECT 1 < 'a'")
    r.query("I", "SELECT 'a' < x'61'")
    r.query("I", "SELECT x'61' > 'a'")
    r.query("I", "SELECT NULL < 1")
    r.query("I", "SELECT '10' < '9'")
    r.query("I", "SELECT 10 < 9")

    # ================= cast.test =================
    r = new_file("cast")
    r.query("I", "SELECT CAST('123abc' AS INTEGER)")
    r.query("I", "SELECT CAST('abc' AS INTEGER)")
    r.query("I", "SELECT CAST('12.7' AS INTEGER)")
    r.query("I", "SELECT CAST('-42.9' AS INTEGER)")
    r.query("I", "SELECT CAST('+42' AS INTEGER)")
    r.query("I", "SELECT CAST(' 42 ' AS INTEGER)")
    r.query("I", "SELECT CAST('1e3' AS INTEGER)")
    r.query("I", "SELECT CAST('3.5e1' AS INTEGER)")
    r.query("I", "SELECT CAST('0x10' AS INTEGER)")
    r.query("I", "SELECT CAST(12.7 AS INTEGER)")
    r.query("I", "SELECT CAST(-12.7 AS INTEGER)")
    r.query("I", "SELECT CAST(3.99 AS INTEGER)")
    r.query("I", "SELECT CAST('' AS INTEGER)")
    r.query("I", "SELECT CAST(x'313233' AS INTEGER)")
    r.query("I", "SELECT CAST(NULL AS INTEGER)")
    r.query("R", "SELECT CAST('12.7' AS REAL)")
    r.query("R", "SELECT CAST('abc' AS REAL)")
    r.query("R", "SELECT CAST('1e3' AS REAL)")
    r.query("R", "SELECT CAST('' AS REAL)")
    r.query("R", "SELECT CAST(x'313233' AS REAL)")
    r.query("R", "SELECT CAST(12 AS REAL)")
    r.query("R", "SELECT CAST(NULL AS REAL)")
    r.query("T", "SELECT CAST(42 AS TEXT)")
    r.query("T", "SELECT CAST(1.5 AS TEXT)")
    r.query("T", "SELECT CAST(x'4142' AS TEXT)")
    r.query("T", "SELECT CAST(1e10 AS TEXT)")
    r.query("T", "SELECT CAST(1e-10 AS TEXT)")
    r.query("T", "SELECT CAST(-0.0 AS TEXT)")
    r.query("T", "SELECT CAST(NULL AS TEXT)")
    r.query("T", "SELECT typeof(CAST('ab' AS BLOB))")
    r.query("T", "SELECT typeof(CAST(1 AS BLOB))")
    r.query("T", "SELECT hex(CAST(1 AS BLOB))")
    r.query("T", "SELECT typeof(CAST(1.5 AS BLOB))")
    r.query("I", "SELECT CAST(x'01' AS BLOB) = x'01'")
    r.query("I", "SELECT CAST('1.5' AS NUMERIC)")
    r.query("I", "SELECT CAST('2' AS NUMERIC)")
    r.query("I", "SELECT CAST('abc' AS NUMERIC)")
    r.query("I", "SELECT CAST('12abc' AS NUMERIC)")
    r.query("R", "SELECT CAST('1.5' AS NUMERIC)")
    r.query("R", "SELECT CAST(2.0 AS NUMERIC)")
    r.query("R", "SELECT CAST(2.5 AS NUMERIC)")
    r.query("I", "SELECT CAST(x'3132' AS NUMERIC)")
    r.query("T", "SELECT typeof(CAST(NULL AS BLOB))")
    r.query("I", "SELECT CAST(CAST('12.3' AS REAL) AS INTEGER)")
    r.query("R", "SELECT CAST(CAST('12.3' AS TEXT) AS REAL)")
    # CAST 参与比较:CAST 结果亲和
    r.stmt_ok("CREATE TABLE ct(a INTEGER, b TEXT)")
    r.stmt_ok("INSERT INTO ct VALUES(1, '1'),(2, '2'),(3, 'x')")
    r.query("I", "SELECT CAST(b AS INTEGER) FROM ct ORDER BY a")
    r.query("I", "SELECT CAST(b AS INTEGER)=a FROM ct ORDER BY a")
    r.query("I", "SELECT a=CAST(b AS INTEGER) FROM ct ORDER BY a")
    r.query("T", "SELECT CAST(a AS TEXT) FROM ct ORDER BY a")
    # int64 截断
    r.query("I", "SELECT CAST(18446744073709551615 AS INTEGER)")
    r.query("I", "SELECT CAST(9.223372036854776e18 AS INTEGER)")
    r.query("I", "SELECT CAST('9223372036854775808' AS INTEGER)")
    r.query("I", "SELECT CAST('-9223372036854775808' AS INTEGER)")

    # ================= expr1.test(算术) =================
    r = new_file("expr1")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT a+b FROM t1 ORDER BY a")
    r.query("I", "SELECT a-b FROM t1 ORDER BY a")
    r.query("I", "SELECT a*b FROM t1 ORDER BY a")
    r.query("I", "SELECT a/b FROM t1 ORDER BY a")
    r.query("I", "SELECT a%b FROM t1 ORDER BY a")
    r.query("I", "SELECT b%a FROM t1 ORDER BY a")
    r.query("I", "SELECT a+b*2 FROM t1 ORDER BY a")
    r.query("I", "SELECT (a+b)*2 FROM t1 ORDER BY a")
    r.query("I", "SELECT 2*3+4")
    r.query("I", "SELECT 10-2*3")
    r.query("I", "SELECT -a FROM t1 ORDER BY a")
    r.query("I", "SELECT -(a+b) FROM t1 ORDER BY a")
    r.query("I", "SELECT a*a-a FROM t1 ORDER BY a")
    r.query("I", "SELECT c/d FROM t1 ORDER BY c")
    r.query("I", "SELECT d%c FROM t1 ORDER BY c")
    r.query("I", "SELECT 1+2*3")
    r.query("I", "SELECT (1+2)*3")
    r.query("I", "SELECT 7/2")
    r.query("R", "SELECT 7.0/2")
    r.query("R", "SELECT 7/2.0")
    r.query("R", "SELECT 7.5*2")
    r.query("I", "SELECT 10/3")
    r.query("I", "SELECT 10%3")
    r.query("I", "SELECT -10%3")
    r.query("I", "SELECT 10%-3")
    r.query("T", "SELECT typeof(1+2)")
    r.query("T", "SELECT typeof(1+2.0)")
    r.query("T", "SELECT typeof('2'+3)")
    r.query("T", "SELECT typeof('2.5'+1)")
    r.query("T", "SELECT typeof(10/3)")
    r.query("T", "SELECT typeof(10/3.0)")
    r.query("T", "SELECT typeof(1/0)")
    r.query("T", "SELECT typeof(-5)")
    r.query("T", "SELECT typeof(-5.0)")
    r.query("I", "SELECT 1/0")
    r.query("R", "SELECT 5.5%2")
    r.query("R", "SELECT 7.5%2.5")
    r.query("R", "SELECT -7.5%2")
    r.query("T", "SELECT typeof(5.5%2)")
    r.query("T", "SELECT typeof(1%2)")
    # int64 溢出 → REAL
    r.query("R", "SELECT 9223372036854775807 + 1")
    r.query("T", "SELECT typeof(9223372036854775807 + 1)")
    r.query("R", "SELECT 9223372036854775807 * 2")
    r.query("R", "SELECT -9223372036854775808 - 1")
    # 文本运算数 → 数值转换
    r.query("I", "SELECT '2'+3")
    r.query("R", "SELECT '2.5'+1")
    r.query("I", "SELECT 'abc'+1")
    r.query("I", "SELECT '2'*3")
    r.query("I", "SELECT '4'/2")
    r.query("R", "SELECT '4.0'/2")
    r.query("R", "SELECT '2.5'*'2'")
    r.query("I", "SELECT -'5'")
    r.query("R", "SELECT -'5.5'")
    r.query("I", "SELECT -'abc'")
    r.query("T", "SELECT typeof(-'2')")
    r.query("T", "SELECT typeof(-'2.5')")
    r.query("T", "SELECT typeof(-'abc')")
    r.query("I", "SELECT +5")
    r.query("T", "SELECT +'5'")
    r.query("T", "SELECT typeof(1e10)")
    # || 连接
    r.query("T", "SELECT 2||3")
    r.query("T", "SELECT 'a'||1")
    r.query("T", "SELECT 1||'a'")
    r.query("T", "SELECT 1.5||2")
    r.query("T", "SELECT 'a'||'b'||'c'")
    r.query("T", "SELECT x'41'||'b'")
    r.query("T", "SELECT x'41'||x'42'")
    r.query("T", "SELECT typeof(1||2)")
    r.query("T", "SELECT typeof(x'41'||x'42')")
    r.query("T", "SELECT 'a'||NULL")
    r.query("T", "SELECT NULL||'a'")
    r.query("I", "SELECT 1+2||3")
    r.query("I", "SELECT 1||2+3")
    r.query("I", "SELECT 1||2*3")
    r.query("I", "SELECT 1*2||3")
    # 优先级:|| 高于 * / % 高于 + -
    r.query("I", "SELECT 2*3+4")
    r.query("I", "SELECT 2+3*4")
    r.query("I", "SELECT (2+3)*4")
    r.query("T", "SELECT 'x'||1.5")
    r.query("T", "SELECT 'x'||1e10")
    # 边界:除零 → NULL
    r.query("I", "SELECT 5/0")
    r.query("I", "SELECT 5%0")
    r.query("I", "SELECT a/0 FROM t1 ORDER BY a LIMIT 3")
    r.query("I", "SELECT a%0 FROM t1 ORDER BY a LIMIT 3")

    # ================= expr2.test(比较) =================
    r = new_file("expr2")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT a=100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a!=100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a<>100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a<100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a<=100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a>100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a>=100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a==100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a=b FROM t1 ORDER BY a")
    r.query("I", "SELECT a!=b FROM t1 ORDER BY a")
    r.query("I", "SELECT b<c FROM t1 ORDER BY a")
    r.query("I", "SELECT c<=d FROM t1 ORDER BY a")
    r.query("I", "SELECT d>e FROM t1 ORDER BY a")
    r.query("I", "SELECT e>=a FROM t1 ORDER BY a")
    r.query("I", "SELECT a+1=b FROM t1 ORDER BY a")
    r.query("I", "SELECT a<b+1 FROM t1 ORDER BY a")
    r.query("I", "SELECT a*2=b+c FROM t1 ORDER BY a")
    r.query("I", "SELECT 1<2<3")
    r.query("I", "SELECT 3>2>1")
    r.query("I", "SELECT 1=1=1")
    r.query("I", "SELECT 2='2'")
    r.query("I", "SELECT '2'=2")
    r.query("I", "SELECT '2'>10")
    r.query("I", "SELECT '10'<9")
    r.query("I", "SELECT 1<2")
    r.query("I", "SELECT 2<=2")
    r.query("I", "SELECT 3>2")
    r.query("I", "SELECT 3>=3")
    r.query("I", "SELECT 'abc'<'abd'")
    r.query("I", "SELECT 'abc'='abc'")
    r.query("I", "SELECT 'ABC'='abc'")
    r.query("I", "SELECT x'41'='A'")
    r.query("I", "SELECT 1 IS 1")
    r.query("I", "SELECT 1 IS 2")
    r.query("I", "SELECT NULL IS NULL")
    r.query("I", "SELECT 1 IS NULL")
    r.query("I", "SELECT NULL IS NOT NULL")
    r.query("I", "SELECT 1 IS '1'")
    r.query("I", "SELECT 1 IS 1.0")
    r.query("I", "SELECT 'a' IS 'a'")
    r.query("I", "SELECT 1 ISNULL")
    r.query("I", "SELECT NULL ISNULL")
    r.query("I", "SELECT 1 NOTNULL")
    r.query("I", "SELECT NULL NOTNULL")
    # 列亲和参与比较
    r.stmt_ok("CREATE TABLE t2(a INTEGER, b TEXT, c REAL)")
    r.stmt_ok("INSERT INTO t2 VALUES(1,'1',1.0),(2,'2',2.0),(3,'3',3.0)")
    r.query("I", "SELECT a='1' FROM t2 ORDER BY a")
    r.query("I", "SELECT '1'=a FROM t2 ORDER BY a")
    r.query("I", "SELECT b=1 FROM t2 ORDER BY a")
    r.query("I", "SELECT c='2' FROM t2 ORDER BY a")
    r.query("I", "SELECT a=b FROM t2 ORDER BY a")
    r.query("I", "SELECT a=c FROM t2 ORDER BY a")
    r.query("I", "SELECT b=c FROM t2 ORDER BY a")
    r.query("I", "SELECT a<2 FROM t2 ORDER BY a")
    r.query("I", "SELECT b<2 FROM t2 ORDER BY a")
    r.query("I", "SELECT c<2 FROM t2 ORDER BY a")
    # WHERE 中的比较
    r.query("I", "SELECT a FROM t1 WHERE b>100 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE c<=d AND e>=a ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a!=b OR b<c ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE NOT a=100 ORDER BY a LIMIT 5")

    # ================= expr3.test(逻辑/混合/无 FROM) =================
    r = new_file("expr3")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT 1 AND 1")
    r.query("I", "SELECT 1 AND 0")
    r.query("I", "SELECT 1 AND NULL")
    r.query("I", "SELECT 0 AND NULL")
    r.query("I", "SELECT NULL AND NULL")
    r.query("I", "SELECT 1 OR 0")
    r.query("I", "SELECT 0 OR 0")
    r.query("I", "SELECT 0 OR NULL")
    r.query("I", "SELECT NULL OR NULL")
    r.query("I", "SELECT 1 OR NULL")
    r.query("I", "SELECT NOT 1")
    r.query("I", "SELECT NOT 0")
    r.query("I", "SELECT NOT NULL")
    r.query("I", "SELECT NOT NOT 1")
    r.query("I", "SELECT 'abc' AND 1")
    r.query("I", "SELECT 'abc' OR 1")
    r.query("I", "SELECT '' AND 1")
    r.query("I", "SELECT '2' AND 1")
    r.query("I", "SELECT 'abc' AND 0")
    r.query("I", "SELECT NOT 'abc'")
    r.query("I", "SELECT NOT ''")
    r.query("I", "SELECT NOT '2'")
    r.query("I", "SELECT 1 AND 'abc'")
    r.query("I", "SELECT 1 OR 'abc'")
    r.query("I", "SELECT 0 AND 'abc'")
    r.query("I", "SELECT a>100 AND b<200 FROM t1 ORDER BY a")
    r.query("I", "SELECT a>100 OR b<150 FROM t1 ORDER BY a")
    r.query("I", "SELECT NOT a=100 FROM t1 ORDER BY a")
    r.query("I", "SELECT a=100 AND b=102 FROM t1")
    r.query("I", "SELECT a=100 OR a=101 FROM t1")
    # 无 FROM 常量投影
    r.query("I", "SELECT 42")
    r.query("R", "SELECT 3.14")
    r.query("T", "SELECT 'hello'")
    r.query("T", "SELECT x'41'")
    r.query("I", "SELECT 1+1")
    r.query("T", "SELECT NULL")
    r.query("III", "SELECT 1, 2, 3")
    r.query("I", "SELECT 1 WHERE 1")
    r.query("I", "SELECT 1 WHERE 0")
    r.query("I", "SELECT 1 WHERE NULL")
    r.query("I", "SELECT 2+3 AS x WHERE 1")
    # CASE
    r.query("T", "SELECT CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' END")
    r.query("T", "SELECT CASE 3 WHEN 1 THEN 'a' ELSE 'z' END")
    r.query("T", "SELECT CASE WHEN 1 THEN 't' END")
    r.query("T", "SELECT CASE WHEN 0 THEN 't' END")
    r.query("T", "SELECT CASE WHEN NULL THEN 't' ELSE 'f' END")
    r.query("T", "SELECT CASE NULL WHEN NULL THEN 'm' ELSE 'n' END")
    r.query("T", "SELECT CASE 1 WHEN 1.0 THEN 'eq' ELSE 'ne' END")
    r.query("I", "SELECT CASE a WHEN 100 THEN 1 ELSE 0 END FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT CASE WHEN a>200 THEN a ELSE 0 END FROM t1 ORDER BY a LIMIT 5")
    # 逻辑与 CASE 组合
    r.query("I", "SELECT CASE WHEN a>100 AND b<200 THEN a ELSE -1 END FROM t1 ORDER BY a LIMIT 5")

    # ================= func1.test(核心标量函数) =================
    r = new_file("func1")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT abs(a) FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT abs(-5)")
    r.query("I", "SELECT abs(5)")
    r.query("R", "SELECT abs(-5.5)")
    r.query("R", "SELECT abs('abc')")
    r.query("R", "SELECT abs('-3')")
    r.query("R", "SELECT abs(x'2d31')")
    r.query("T", "SELECT typeof(abs('-3'))")
    r.query("T", "SELECT typeof(abs(3))")
    r.query("I", "SELECT abs(NULL)")
    r.query("I", "SELECT length('hello')")
    r.query("I", "SELECT length('')")
    r.query("I", "SELECT length(x'414243')")
    r.query("I", "SELECT length(x'')")
    r.query("I", "SELECT length(123)")
    r.query("I", "SELECT length(1.5)")
    r.query("I", "SELECT length('é')")
    r.query("I", "SELECT length(NULL)")
    r.query("T", "SELECT substr('hello', 2)")
    r.query("T", "SELECT substr('hello', 2, 3)")
    r.query("T", "SELECT substr('hello', -3)")
    r.query("T", "SELECT substr('hello', -3, 2)")
    r.query("T", "SELECT substr('hello', 0)")
    r.query("T", "SELECT substr('hello', 0, 3)")
    r.query("T", "SELECT substr('hello', 99)")
    r.query("T", "SELECT substr('hello', -99, 2)")
    r.query("T", "SELECT substr('abcdef', 3, -1)")
    r.query("T", "SELECT substr('abcdef', 4, -2)")
    r.query("T", "SELECT substr('abcdef', 1, -1)")
    r.query("T", "SELECT substr('abcdef', 0, -1)")
    r.query("T", "SELECT substr('ééé', 2, 2)")
    r.query("T", "SELECT substr(x'68656c6c6f', 2)")
    r.query("T", "SELECT substr('abc', NULL, 1)")
    r.query("T", "SELECT substr(NULL, 1)")
    r.query("T", "SELECT substr('abcdef', 3, 0)")
    r.query("T", "SELECT substr('abcdef', 100, 1)")
    r.query("T", "SELECT coalesce(NULL, NULL, 'x')")
    r.query("I", "SELECT coalesce(NULL, NULL, 3)")
    r.query("I", "SELECT coalesce(1, NULL)")
    r.query("T", "SELECT coalesce(NULL, 'a')")
    r.query("I", "SELECT ifnull(NULL, 5)")
    r.query("I", "SELECT ifnull(2, 5)")
    r.query("T", "SELECT ifnull(NULL, 'd')")
    r.query("I", "SELECT nullif(1, 1)")
    r.query("I", "SELECT nullif(1, 2)")
    r.query("T", "SELECT nullif('a', 'a')")
    r.query("T", "SELECT nullif('a', 'A')")
    r.query("I", "SELECT NULLIF(a,100) FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT COALESCE(NULLIF(a,100), -1) FROM t1 ORDER BY a LIMIT 5")
    r.query("T", "SELECT typeof(NULL)")
    r.query("T", "SELECT typeof(1)")
    r.query("T", "SELECT typeof(1.5)")
    r.query("T", "SELECT typeof('x')")
    r.query("T", "SELECT typeof(x'41')")
    r.query("T", "SELECT typeof(1+1)")
    r.query("T", "SELECT typeof(1.0+1)")
    r.stmt_err("SELECT coalesce(NULL)", "wrong number of arguments")
    r.stmt_err("SELECT ifnull(1)", "wrong number of arguments")
    r.stmt_err("SELECT abs(1, 2)", "wrong number of arguments")

    # ================= func2.test(文本/编码函数) =================
    r = new_file("func2")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("T", "SELECT upper('AbC')")
    r.query("T", "SELECT lower('AbC')")
    r.query("T", "SELECT upper('äöü')")
    r.query("T", "SELECT lower('ÄÖÜ')")
    r.query("T", "SELECT upper(NULL)")
    r.query("T", "SELECT upper(123)")
    r.query("T", "SELECT upper(x'61')")
    r.query("T", "SELECT lower(x'41')")
    r.query("T", "SELECT upper('aBc')")
    r.query("T", "SELECT lower('aBc')")
    r.query("T", "SELECT hex(x'4142')")
    r.query("T", "SELECT hex('AB')")
    r.query("T", "SELECT hex(123)")
    r.query("T", "SELECT hex(1.5)")
    r.query("T", "SELECT hex(x'')")
    r.query("T", "SELECT hex(NULL)")
    r.query("T", "SELECT hex(x'00ff10')")
    r.query("T", "SELECT quote(NULL)")
    r.query("T", "SELECT quote(123)")
    r.query("T", "SELECT quote(1.5)")
    r.query("T", "SELECT quote('ab')")
    r.query("T", "SELECT quote('a''b')")
    r.query("T", "SELECT quote(x'ab')")
    r.query("T", "SELECT quote(x'00')")
    r.query("R", "SELECT round(2.5)")
    r.query("R", "SELECT round(-2.5)")
    r.query("R", "SELECT round(0.5)")
    r.query("R", "SELECT round(-0.5)")
    r.query("R", "SELECT round(1.5)")
    r.query("R", "SELECT round(-1.5)")
    r.query("R", "SELECT round(2.675, 2)")
    r.query("R", "SELECT round(2.685, 2)")
    r.query("R", "SELECT round(123.456, -1)")
    r.query("R", "SELECT round(1234.5678, -2)")
    r.query("R", "SELECT round(99.9, -1)")
    r.query("R", "SELECT round(123456789.123, 2)")
    r.query("R", "SELECT round('12.345', 2)")
    r.query("R", "SELECT round(3.14159, 2)")
    r.query("R", "SELECT round(NULL)")
    r.query("T", "SELECT typeof(round(3.0))")
    r.query("T", "SELECT typeof(round(3))")
    r.query("T", "SELECT typeof(round(2.5))")
    r.query("I", "SELECT sign(-5)")
    r.query("I", "SELECT sign(0)")
    r.query("I", "SELECT sign(5)")
    r.query("I", "SELECT sign('-2')")
    r.query("I", "SELECT sign('abc')")
    r.query("I", "SELECT sign(NULL)")
    r.query("R", "SELECT sign(-5.5)")
    r.query("I", "SELECT unicode('A')")
    r.query("I", "SELECT unicode('ab')")
    r.query("I", "SELECT unicode('')")
    r.query("I", "SELECT unicode(x'41')")
    r.query("I", "SELECT unicode(65)")
    r.query("I", "SELECT unicode(NULL)")
    r.query("T", "SELECT char(65)")
    r.query("T", "SELECT char(65, 66)")
    r.query("T", "SELECT char(0)")
    r.query("T", "SELECT char(NULL)")
    r.query("T", "SELECT char(72, 105)")

    # ================= func3.test(文本处理/极值) =================
    r = new_file("func3")
    r.query("T", "SELECT min('b', 'a')")
    r.query("T", "SELECT max('b', 'a')")
    r.query("I", "SELECT min(3, 1, 2)")
    r.query("I", "SELECT max(3, 1, 2)")
    r.query("I", "SELECT min(1, '2')")
    r.query("T", "SELECT max(1, '2')")
    r.query("I", "SELECT min(1, 2.5)")
    r.query("R", "SELECT max(1, 2.5)")
    r.query("T", "SELECT min('10', '9')")
    r.query("I", "SELECT min(3)")
    r.query("I", "SELECT max(3)")
    r.query("I", "SELECT min(NULL, 1)")
    r.query("I", "SELECT max(NULL, 1)")
    r.query("T", "SELECT replace('abc', 'b', 'B')")
    r.query("T", "SELECT replace('abc', '', 'x')")
    r.query("T", "SELECT replace('aabbcc', 'b', 'X')")
    r.query("T", "SELECT replace('abc', 'z', 'Y')")
    r.query("T", "SELECT replace(NULL, 'a', 'b')")
    r.query("T", "SELECT replace('abc', NULL, 'x')")
    r.query("T", "SELECT replace('abc', 'a', NULL)")
    r.query("I", "SELECT instr('abc', 'b')")
    r.query("I", "SELECT instr('abc', '')")
    r.query("I", "SELECT instr('', 'a')")
    r.query("I", "SELECT instr('abc', 'abc')")
    r.query("I", "SELECT instr('abc', 'z')")
    r.query("I", "SELECT instr(NULL, 'a')")
    r.query("I", "SELECT instr('abc', NULL)")
    r.query("T", "SELECT trim('  ab  ')")
    r.query("T", "SELECT ltrim('  ab  ')")
    r.query("T", "SELECT rtrim('  ab  ')")
    r.query("T", "SELECT trim('xxabxx', 'x')")
    r.query("T", "SELECT ltrim('abc', 'ab')")
    r.query("T", "SELECT rtrim('abc', 'bc')")
    r.query("T", "SELECT trim('abc')")
    r.query("T", "SELECT trim(NULL)")
    r.query("T", "SELECT ltrim('xyxyab', 'xy')")
    r.stmt_err("SELECT min()", "wrong number of arguments")
    r.stmt_err("SELECT instr('a')", "wrong number of arguments")
    r.stmt_err("SELECT replace('a','b')", "wrong number of arguments")
    r.stmt_err("SELECT no_such_func(1)", "no such function")

    # ================= func4.test(printf/高级) =================
    r = new_file("func4")
    r.query("T", "SELECT printf('%d-%s', 42, 'x')")
    r.query("T", "SELECT printf('%.2f', 3.14159)")
    r.query("T", "SELECT printf('%s', 'hello')")
    r.query("T", "SELECT printf('%05d', 42)")
    r.query("T", "SELECT printf('%-5d|', 42)")
    r.query("T", "SELECT printf('%5s|', 'ab')")
    r.query("T", "SELECT printf('%x', 255)")
    r.query("T", "SELECT printf('%X', 255)")
    r.query("T", "SELECT printf('%c', 65)")
    r.query("T", "SELECT printf('100%%')")
    r.query("T", "SELECT printf('%d', 3.9)")
    r.query("T", "SELECT printf('%s', 1.5)")
    r.query("T", "SELECT printf('%s', 1e10)")
    r.query("T", "SELECT printf('%f', 1.5)")
    r.query("T", "SELECT printf('%d+%d=%d', 1, 2, 3)")
    r.query("T", "SELECT printf('%q', 'it''s')")
    r.query("T", "SELECT printf('%q', 'a''b''c')")
    r.query("I", "SELECT like('a%', 'abc')")
    r.query("I", "SELECT like('%z', 'abc')")
    r.query("I", "SELECT like('A%', 'abc')")
    r.query("I", "SELECT like('a_c', 'abc')")
    r.query("I", "SELECT glob('a*', 'abc')")
    r.query("I", "SELECT glob('A*', 'abc')")
    r.query("I", "SELECT glob('a?c', 'abc')")
    r.query("I", "SELECT glob('a[bc]c', 'abc')")
    r.query("I", "SELECT like(NULL, 'abc')")
    r.query("I", "SELECT like('a%', NULL)")
    r.query("I", "SELECT glob(NULL, 'abc')")

    # ================= func5.test(函数嵌套/组合) =================
    r = new_file("func5")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT abs(-abs(-5))")
    r.query("I", "SELECT length(upper('abc'))")
    r.query("T", "SELECT upper(substr('hello', 1, 3))")
    r.query("I", "SELECT abs(a)+b FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT coalesce(nullif(a,100), -a) FROM t1 ORDER BY a LIMIT 5")
    r.query("T", "SELECT typeof(coalesce(1, 'x'))")
    r.query("T", "SELECT typeof(coalesce(NULL, 'x'))")
    r.query("T", "SELECT substr(upper('abcdef'), 2, 3)")
    r.query("I", "SELECT length(trim('  a  '))")
    r.query("T", "SELECT hex(CAST('AB' AS BLOB))")
    r.query("T", "SELECT quote(upper('ab'))")
    r.query("I", "SELECT abs(-3)+abs(-4)")
    r.query("R", "SELECT round(abs(-2.5), 1)")
    r.query("I", "SELECT length('')+0")
    r.query("I", "SELECT min(abs(a), abs(b)) FROM t1 ORDER BY a LIMIT 5")
    r.query("T", "SELECT printf('%s', upper('ab'))")
    r.query("I", "SELECT instr(upper('abc'), 'B')")
    r.query("T", "SELECT replace(upper('abc'), 'B', 'x')")

    # ================= like.test =================
    r = new_file("like")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.stmt_ok("CREATE TABLE t2(s TEXT)")
    r.stmt_ok("INSERT INTO t2 VALUES('abc'),('ABC'),('aBc'),('xyz'),('hello world'),(''),('a%c'),('a_c'),('a\\c'),('a1c')")
    r.query("I", "SELECT s LIKE 'abc' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'ABC' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a%' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE '%c' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE '%o%' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a_c' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a%c' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE '_bc' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a\\_c' ESCAPE '\\' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a\\%c' ESCAPE '\\' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a\\\\c' ESCAPE '\\' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE 'a\\_c' ESCAPE 'z' FROM t2 ORDER BY s")
    r.query("I", "SELECT s LIKE '' FROM t2 ORDER BY s")
    r.query("I", "SELECT s NOT LIKE 'abc' FROM t2 ORDER BY s")
    r.query("I", "SELECT 'A' LIKE 'a'")
    r.query("I", "SELECT 'a' LIKE 'A'")
    r.query("I", "SELECT 'ä' LIKE 'Ä'")
    r.query("I", "SELECT x'41' LIKE 'a'")
    r.query("I", "SELECT 'a' LIKE x'61'")
    r.query("I", "SELECT NULL LIKE 'a%'")
    r.query("I", "SELECT 'a' LIKE NULL")
    r.query("I", "SELECT '' LIKE '%'")
    r.query("I", "SELECT '' LIKE '_'")
    r.query("I", "SELECT 'x' LIKE ''")
    r.query("I", "SELECT '%' LIKE '\\%' ESCAPE '\\'")
    r.query("I", "SELECT 'a%b' LIKE 'a\\%b' ESCAPE '\\'")
    r.query("I", "SELECT 'aXb' LIKE 'a\\%b' ESCAPE '\\'")
    r.query("I", "SELECT 'a_b' LIKE 'a\\_b' ESCAPE '\\'")
    r.query("I", "SELECT 'axb' LIKE 'a\\_b' ESCAPE '\\'")
    r.query("I", "SELECT 'a\\b' LIKE 'a\\\\b' ESCAPE '\\'")
    r.query("I", "SELECT 'ab' LIKE 'a\\\\b' ESCAPE '\\'")
    r.query("I", "SELECT 'hello' LIKE 'H%O'")
    r.query("I", "SELECT 'hello' LIKE 'h_llo'")
    r.query("I", "SELECT 'a\nc' LIKE 'a%c'")
    r.query("I", "SELECT 'a%c' LIKE 'a%c' ESCAPE 'z'")
    r.query("I", "SELECT s LIKE 'hello%' FROM t2 ORDER BY s")

    # ================= in.test =================
    r = new_file("in")
    r.stmt_ok(t1_create)
    for ins in t1_inserts:
        r.stmt_ok(ins)
    r.query("I", "SELECT 1 IN (1, 2, 3)")
    r.query("I", "SELECT 4 IN (1, 2, 3)")
    r.query("I", "SELECT 3 IN (1, 2, 3)")
    r.query("I", "SELECT 3 NOT IN (1, 2, 3)")
    r.query("I", "SELECT 4 NOT IN (1, 2, 3)")
    r.query("I", "SELECT 1 IN ()")
    r.query("I", "SELECT 1 NOT IN ()")
    r.query("I", "SELECT NULL IN (1, 2)")
    r.query("I", "SELECT 3 IN (1, 2, NULL)")
    r.query("I", "SELECT 2 IN (1, 2, NULL)")
    r.query("I", "SELECT 1 NOT IN (NULL, 2)")
    r.query("I", "SELECT 2 NOT IN (NULL, 2)")
    r.query("I", "SELECT 3 NOT IN (NULL, 2)")
    r.query("I", "SELECT NULL IN (NULL)")
    r.query("I", "SELECT 'abc' IN ('abc', 'def')")
    r.query("I", "SELECT 'ABC' IN ('abc', 'def')")
    r.query("I", "SELECT 'a' IN ('a', 'b')")
    r.query("I", "SELECT a IN (100, 101) FROM t1 ORDER BY a")
    r.query("I", "SELECT a IN (100, 101, 102) FROM t1 ORDER BY a")
    r.query("I", "SELECT a NOT IN (100, 101) FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT a IN (b, c) FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT a IN (100) FROM t1 ORDER BY a LIMIT 5")
    r.query("I", "SELECT a+1 IN (101, 102) FROM t1 ORDER BY a LIMIT 5")
    # 亲和
    r.stmt_ok("CREATE TABLE t2(a INTEGER, b TEXT)")
    r.stmt_ok("INSERT INTO t2 VALUES(1,'1'),(2,'2'),(3,'3')")
    r.query("I", "SELECT a IN ('1','2') FROM t2 ORDER BY a")
    r.query("I", "SELECT b IN (1,2) FROM t2 ORDER BY a")
    r.query("I", "SELECT '2' IN (a) FROM t2 ORDER BY a")
    r.query("I", "SELECT 2 IN (b) FROM t2 ORDER BY a")
    r.query("I", "SELECT 2 IN (a) FROM t2 ORDER BY a")
    r.query("I", "SELECT a IN (1,'2') FROM t2 ORDER BY a")
    r.query("I", "SELECT 2 IN (a,b) FROM t2 ORDER BY a")
    r.query("I", "SELECT '2' IN (a,b) FROM t2 ORDER BY a")

    # ================= null.test =================
    r = new_file("null")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b INTEGER)")
    r.stmt_ok("INSERT INTO t1 VALUES(1, NULL),(NULL, 2),(NULL, NULL),(3, 4)")
    r.query("I", "SELECT a IS NULL FROM t1 ORDER BY a")
    r.query("I", "SELECT a IS NOT NULL FROM t1 ORDER BY a")
    r.query("I", "SELECT a=b FROM t1 ORDER BY a")
    r.query("I", "SELECT a!=b FROM t1 ORDER BY a")
    r.query("I", "SELECT a<b FROM t1 ORDER BY a")
    r.query("I", "SELECT a AND b FROM t1 ORDER BY a")
    r.query("I", "SELECT a OR b FROM t1 ORDER BY a")
    r.query("I", "SELECT NOT a FROM t1 ORDER BY a")
    r.query("I", "SELECT a+1 FROM t1 ORDER BY a")
    r.query("I", "SELECT a*b FROM t1 ORDER BY a")
    r.query("I", "SELECT -a FROM t1 ORDER BY a")
    r.query("I", "SELECT a||b FROM t1 ORDER BY a")
    r.query("I", "SELECT a IN (1, 2) FROM t1 ORDER BY a")
    r.query("I", "SELECT a BETWEEN 1 AND 3 FROM t1 ORDER BY a")
    r.query("I", "SELECT a BETWEEN NULL AND 3 FROM t1 ORDER BY a")
    r.query("I", "SELECT 2 BETWEEN NULL AND 3")
    r.query("I", "SELECT 2 BETWEEN 1 AND NULL")
    r.query("I", "SELECT NULL BETWEEN 1 AND 3")
    r.query("I", "SELECT 2 NOT BETWEEN 1 AND 3")
    r.query("I", "SELECT 2 NOT BETWEEN NULL AND 3")
    r.query("I", "SELECT CASE WHEN a THEN 1 ELSE 0 END FROM t1 ORDER BY a")
    r.query("I", "SELECT CASE a WHEN 1 THEN 1 ELSE 0 END FROM t1 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a IS NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a IS NOT NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a=NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a!=NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE NOT a=1 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a=1 OR a IS NULL ORDER BY a")
    r.query("I", "SELECT NULL=NULL")
    r.query("I", "SELECT NULL!=NULL")
    r.query("I", "SELECT NULL<NULL")
    r.query("I", "SELECT NULL AND 1")
    r.query("I", "SELECT NULL OR 1")
    r.query("I", "SELECT NOT NULL")
    r.query("I", "SELECT NULL+1")
    r.query("I", "SELECT NULL*1")
    r.query("I", "SELECT NULL||'a'")
    r.query("I", "SELECT 1 IS NULL")
    r.query("I", "SELECT NULL IS NULL")
    r.query("I", "SELECT NULL IS NOT NULL")
    r.query("I", "SELECT 1 ISNULL")
    r.query("I", "SELECT NULL ISNULL")
    r.query("I", "SELECT 1 NOTNULL")
    r.query("I", "SELECT NULL NOTNULL")

    # ================= collate1.test(BINARY) =================
    r = new_file("collate1")
    r.stmt_ok("CREATE TABLE t1(a TEXT, b TEXT COLLATE NOCASE, c TEXT COLLATE RTRIM)")
    r.stmt_ok("INSERT INTO t1 VALUES('abc','ABC','x  '),('ABD','abd','x'),('abc','aBc','x '),('b','B','y')")
    r.query("T", "SELECT a FROM t1 ORDER BY a")
    r.query("T", "SELECT a FROM t1 ORDER BY a COLLATE BINARY")
    r.query("T", "SELECT a FROM t1 ORDER BY a COLLATE NOCASE")
    r.query("I", "SELECT a='abc' FROM t1 ORDER BY a")
    r.query("I", "SELECT a='ABC' FROM t1 ORDER BY a")
    r.query("I", "SELECT a='abc' COLLATE NOCASE FROM t1 ORDER BY a")
    r.query("I", "SELECT a COLLATE NOCASE='ABC' FROM t1 ORDER BY a")
    r.query("I", "SELECT 'abc'=a FROM t1 ORDER BY a")
    r.query("I", "SELECT 'ABC'=a COLLATE NOCASE FROM t1 ORDER BY a")
    r.query("T", "SELECT b FROM t1 ORDER BY b")
    r.query("T", "SELECT b FROM t1 ORDER BY b COLLATE BINARY")
    r.query("I", "SELECT b='abc' FROM t1 ORDER BY a")
    r.query("I", "SELECT b='ABC' FROM t1 ORDER BY a")
    r.query("I", "SELECT 'abc'=b FROM t1 ORDER BY a")
    r.query("T", "SELECT c FROM t1 ORDER BY c")
    r.query("T", "SELECT c FROM t1 ORDER BY c COLLATE BINARY")
    r.query("I", "SELECT c='x' FROM t1 ORDER BY a")
    r.query("I", "SELECT 'x'=c FROM t1 ORDER BY a")
    r.query("I", "SELECT 'ABC' < 'abc' COLLATE NOCASE")
    r.query("I", "SELECT 'ABC' < 'abc' COLLATE BINARY")
    r.query("I", "SELECT 'A' < 'a' COLLATE NOCASE")
    r.query("I", "SELECT 'B' > 'a' COLLATE NOCASE")
    r.query("I", "SELECT 'a' < 'B' COLLATE BINARY")

    # ================= collate2.test(NOCASE 排序) =================
    r = new_file("collate2")
    r.stmt_ok("CREATE TABLE t1(x TEXT COLLATE NOCASE)")
    r.stmt_ok("INSERT INTO t1 VALUES('apple'),('Apple'),('APPLE'),('banana'),('Banana'),('cherry'),('Cherry')")
    r.query("T", "SELECT x FROM t1 ORDER BY x")
    r.query("T", "SELECT x FROM t1 ORDER BY x COLLATE BINARY")
    r.query("T", "SELECT x FROM t1 ORDER BY x COLLATE NOCASE")
    r.query("T", "SELECT x FROM t1 ORDER BY x DESC")
    r.query("I", "SELECT x='apple' FROM t1 ORDER BY x COLLATE NOCASE")
    r.query("I", "SELECT x='APPLE' FROM t1 ORDER BY x COLLATE BINARY")
    r.query("I", "SELECT x='apple' FROM t1 ORDER BY x COLLATE NOCASE")
    r.query("I", "SELECT x='APPLE' FROM t1 ORDER BY x COLLATE BINARY")
    r.stmt_ok("CREATE TABLE t2(a TEXT COLLATE NOCASE, b TEXT COLLATE BINARY)")
    r.stmt_ok("INSERT INTO t2 VALUES('one','one'),('One','One'),('ONE','ONE')")
    r.query("I", "SELECT a=b FROM t2 ORDER BY a")
    r.query("I", "SELECT a=b COLLATE NOCASE FROM t2 ORDER BY a")
    r.query("I", "SELECT a<b FROM t2 ORDER BY a")
    r.query("I", "SELECT a>b FROM t2 ORDER BY a")

    # ================= collate3.test(RTRIM) =================
    r = new_file("collate3")
    r.stmt_ok("CREATE TABLE t1(a TEXT COLLATE RTRIM)")
    r.stmt_ok("INSERT INTO t1 VALUES('abc'),('abc '),('abc  '),(' abc'),('x'),('x ')")
    r.query("T", "SELECT a FROM t1 ORDER BY a")
    r.query("T", "SELECT a FROM t1 ORDER BY a COLLATE BINARY")
    r.query("T", "SELECT a FROM t1 ORDER BY a COLLATE RTRIM")
    r.query("I", "SELECT a='abc' FROM t1 ORDER BY a COLLATE RTRIM")
    r.query("I", "SELECT a='abc' FROM t1 ORDER BY a COLLATE BINARY")
    r.query("I", "SELECT a='abc ' FROM t1 ORDER BY a COLLATE RTRIM")
    r.query("I", "SELECT '  abc' = 'abc' COLLATE RTRIM")
    r.query("I", "SELECT 'a b' = 'a b ' COLLATE RTRIM")
    r.query("I", "SELECT 'abc  ' = 'abc' COLLATE RTRIM")
    r.query("I", "SELECT 'abc' = 'abc ' COLLATE RTRIM")
    r.query("I", "SELECT ' abc' = 'abc' COLLATE RTRIM")

    # ================= collate4.test(表达式 COLLATE) =================
    r = new_file("collate4")
    r.query("I", "SELECT 'a' || 'b' COLLATE NOCASE = 'AB'")
    r.query("I", "SELECT 'abc' COLLATE NOCASE = 'ABC'")
    r.query("I", "SELECT 'abc' COLLATE BINARY = 'ABC'")
    r.query("I", "SELECT 'abc' COLLATE NOCASE < 'ABD'")
    r.query("I", "SELECT 'abc' COLLATE BINARY < 'ABD'")
    r.query("I", "SELECT 'b' BETWEEN 'A' AND 'C' COLLATE NOCASE")
    r.query("I", "SELECT 'B' BETWEEN 'a' AND 'c' COLLATE NOCASE")
    r.query("I", "SELECT 'ABC' IN ('abc','def') COLLATE NOCASE")
    r.query("I", "SELECT 'abc' IN ('abc','def')")
    r.query("I", "SELECT 'ABC' IN ('abc','def')")
    r.stmt_ok("CREATE TABLE t1(a TEXT, b TEXT COLLATE NOCASE)")
    r.stmt_ok("INSERT INTO t1 VALUES('abc','ABC'),('ABD','abd'),('abc','aBc')")
    r.query("T", "SELECT a || b FROM t1 ORDER BY a")
    r.query("I", "SELECT a = b FROM t1 ORDER BY a")
    r.query("I", "SELECT a = b COLLATE NOCASE FROM t1 ORDER BY a")
    r.query("I", "SELECT a COLLATE NOCASE = b FROM t1 ORDER BY a")
    r.query("I", "SELECT (a COLLATE NOCASE) = b FROM t1 ORDER BY a")
    r.query("T", "SELECT a FROM t1 ORDER BY a || b")

    # ================= collate5.test(混合排序/多列) =================
    r = new_file("collate5")
    r.stmt_ok("CREATE TABLE t1(a TEXT COLLATE NOCASE, b TEXT COLLATE BINARY)")
    r.stmt_ok("INSERT INTO t1 VALUES('a','Z'),('A','y'),('b','X'),('B','w'),('c','v')")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY a")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY a, b")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY b, a")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY a COLLATE BINARY")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY a DESC")
    r.query("TT", "SELECT a, b FROM t1 ORDER BY b DESC, a")
    r.query("T", "SELECT b FROM t1 ORDER BY b COLLATE NOCASE")
    r.query("I", "SELECT a=b FROM t1 ORDER BY a")
    r.query("I", "SELECT a=b COLLATE BINARY FROM t1 ORDER BY a")
    r.query("I", "SELECT a=b COLLATE NOCASE FROM t1 ORDER BY a")
    r.query("I", "SELECT a='a' FROM t1 ORDER BY a")
    r.query("I", "SELECT b='Z' FROM t1 ORDER BY a")
    r.query("I", "SELECT a='a' AND b='Z' FROM t1 ORDER BY a")
    r.query("T", "SELECT a FROM t1 ORDER BY a LIMIT 3")

    # ================= insert1.test(DML:INSERT 多行/缺省/NULL/亲和) =================
    # 官方 insert1-5.test 场景重构:多行、DEFAULT VALUES、列清单、省略列、
    # 显式 NULL、列级 DEFAULT、亲和转换、错误
    r = new_file("insert1")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT, c REAL)")
    r.stmt_ok("INSERT INTO t1 VALUES(1, 'one', 1.5)")
    r.stmt_ok("INSERT INTO t1 VALUES(2, 'two', 2.5), (3, 'three', 3.5)")
    r.stmt_ok("INSERT INTO t1 DEFAULT VALUES")
    r.stmt_ok("INSERT INTO t1(a) VALUES(4)")
    r.stmt_ok("INSERT INTO t1(b, a) VALUES('four', 5)")
    r.stmt_ok("INSERT INTO t1 VALUES(NULL, NULL, NULL)")
    r.stmt_ok("INSERT INTO t1 VALUES('6', 6, '7')")
    r.query("ITR", "SELECT a, b, c FROM t1")
    r.query("TTT", "SELECT typeof(a), typeof(b), typeof(c) FROM t1 ORDER BY a")
    # 列级 DEFAULT:省略列取 DEFAULT;显式 NULL 覆盖;DEFAULT 值按列亲和转换
    r.stmt_ok("CREATE TABLE t2(a INTEGER DEFAULT 42, b TEXT DEFAULT 'x', c REAL DEFAULT 1.5, d)")
    r.stmt_ok("INSERT INTO t2 DEFAULT VALUES")
    r.stmt_ok("INSERT INTO t2(a) VALUES(7)")
    r.stmt_ok("INSERT INTO t2(a, b) VALUES(8, NULL)")
    r.stmt_ok("INSERT INTO t2(a, c, d) VALUES(9, 2.5, 'z')")
    r.query("ITRT", "SELECT a, b, c, d FROM t2")
    r.stmt_ok("CREATE TABLE t3(a INTEGER DEFAULT '42', b TEXT DEFAULT 7, c REAL DEFAULT '2.5')")
    r.stmt_ok("INSERT INTO t3 DEFAULT VALUES")
    r.query("TTT", "SELECT typeof(a), typeof(b), typeof(c) FROM t3")
    # 错误
    r.stmt_err("INSERT INTO t1 VALUES(1)", "INSERT has 1 values")
    r.stmt_err("INSERT INTO t1 VALUES(1,2,3,4)", "INSERT has 4 values")
    r.stmt_err("INSERT INTO nosuch VALUES(1)", "no such table")
    r.stmt_err("INSERT INTO t1(z) VALUES(1)", "no such column")
    r.stmt_err("INSERT INTO t1(a, a) VALUES(1, 2)", "duplicate column")

    # ================= update1.test(官方 update1-3 场景:表达式/WHERE/亲和) =================
    r = new_file("update1")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT)")
    r.stmt_ok("INSERT INTO t1 VALUES(1,'one'),(2,'two'),(3,'three'),(4,'four'),(5,'five')")
    r.stmt_ok("UPDATE t1 SET b = b || '!'")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    r.stmt_ok("UPDATE t1 SET a = a * 10 WHERE a <= 3")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    r.stmt_ok("UPDATE t1 SET a = a + 1, b = 'x' WHERE b = 'two!'")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    # 交换赋值:SET 表达式都基于原行
    r.stmt_ok("UPDATE t1 SET a = b, b = a WHERE a = 40")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    # 无匹配 UPDATE
    r.stmt_ok("UPDATE t1 SET b = 'z' WHERE a = 999")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    # 亲和转换:INTEGER 列赋 '3.9' → REAL 3.9
    r.stmt_ok("CREATE TABLE t2(a INTEGER)")
    r.stmt_ok("INSERT INTO t2 VALUES(1),(2)")
    r.stmt_ok("UPDATE t2 SET a = '3.9'")
    r.query("RT", "SELECT a, typeof(a) FROM t2 ORDER BY a")
    # collation 参与 WHERE
    r.stmt_ok("CREATE TABLE t3(a TEXT COLLATE NOCASE)")
    r.stmt_ok("INSERT INTO t3 VALUES('abc'),('ABC'),('xyz')")
    r.stmt_ok("UPDATE t3 SET a = 'matched' WHERE a = 'abc'")
    r.query("T", "SELECT a FROM t3 ORDER BY a")
    # 错误
    r.stmt_err("UPDATE t1 SET z = 1", "no such column")
    r.stmt_err("UPDATE nosuch SET a = 1", "no such table")

    # ================= delete1.test(官方 delete1-4 场景:WHERE/全删) =================
    r = new_file("delete1")
    r.stmt_ok("CREATE TABLE t1(a INTEGER)")
    r.stmt_ok("INSERT INTO t1 VALUES(1),(2),(3),(4),(5)")
    r.stmt_ok("DELETE FROM t1 WHERE a > 3")
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    r.stmt_ok("DELETE FROM t1 WHERE a = 2")
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    r.stmt_ok("DELETE FROM t1 WHERE a = 99")
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    r.stmt_ok("DELETE FROM t1")
    r.query("I", "SELECT a FROM t1")
    r.stmt_err("DELETE FROM nosuch", "no such table")

    # ================= select2.test(官方 select2 t1 数据,含 NULL;WHERE 谓词) =================
    r = new_file("select2")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b INTEGER, c INTEGER, d INTEGER, e INTEGER)")
    for ins in [
        "INSERT INTO t1(e,c,b,d,a) VALUES(NULL,102,NULL,101,104)",
        "INSERT INTO t1(a,c,d,e,b) VALUES(107,106,108,109,105)",
        "INSERT INTO t1(e,d,b,a,c) VALUES(110,114,112,NULL,113)",
        "INSERT INTO t1(d,c,e,a,b) VALUES(116,119,117,115,NULL)",
        "INSERT INTO t1(c,d,b,e,a) VALUES(123,122,124,NULL,121)",
        "INSERT INTO t1(a,d,b,e,c) VALUES(127,128,129,126,125)",
        "INSERT INTO t1(e,c,a,d,b) VALUES(132,134,131,133,130)",
        "INSERT INTO t1(a,d,b,e,c) VALUES(138,136,139,135,137)",
        "INSERT INTO t1(e,c,d,a,b) VALUES(144,141,140,142,143)",
        "INSERT INTO t1(b,a,e,d,c) VALUES(145,149,146,NULL,147)",
        "INSERT INTO t1(b,c,a,d,e) VALUES(151,150,153,NULL,NULL)",
        "INSERT INTO t1(c,e,a,d,b) VALUES(155,157,159,NULL,158)",
        "INSERT INTO t1(c,b,a,d,e) VALUES(161,160,163,164,162)",
        "INSERT INTO t1(b,d,a,e,c) VALUES(167,NULL,168,165,166)",
        "INSERT INTO t1(d,b,c,e,a) VALUES(171,170,172,173,174)",
        "INSERT INTO t1(e,c,a,d,b) VALUES(177,176,179,NULL,175)",
        "INSERT INTO t1(b,e,a,d,c) VALUES(181,180,182,183,184)",
        "INSERT INTO t1(c,a,b,e,d) VALUES(187,188,186,189,185)",
        "INSERT INTO t1(d,b,c,e,a) VALUES(190,194,193,192,191)",
        "INSERT INTO t1(a,e,b,d,c) VALUES(199,197,198,196,195)",
        "INSERT INTO t1(b,c,d,a,e) VALUES(NULL,202,203,201,204)",
        "INSERT INTO t1(c,e,a,b,d) VALUES(208,NULL,NULL,206,207)",
        "INSERT INTO t1(c,e,a,d,b) VALUES(214,210,213,212,211)",
        "INSERT INTO t1(b,c,a,d,e) VALUES(218,215,216,217,219)",
        "INSERT INTO t1(b,e,d,a,c) VALUES(223,221,222,220,224)",
        "INSERT INTO t1(d,e,b,a,c) VALUES(226,227,228,229,225)",
        "INSERT INTO t1(a,c,b,e,d) VALUES(234,231,232,230,233)",
        "INSERT INTO t1(e,b,a,c,d) VALUES(237,236,239,NULL,238)",
        "INSERT INTO t1(e,c,b,a,d) VALUES(NULL,244,240,243,NULL)",
        "INSERT INTO t1(e,d,c,b,a) VALUES(246,248,247,249,245)",
    ]:
        r.stmt_ok(ins)
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE b IS NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a IS NOT NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE c > 200 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE b < a ORDER BY a")
    r.query("II", "SELECT a, b FROM t1 WHERE a > 200 AND b > 200 ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE b IS NULL OR c IS NULL ORDER BY a")
    r.query("I", "SELECT a FROM t1 ORDER BY a DESC LIMIT 5")
    r.query("I", "SELECT a FROM t1 ORDER BY a LIMIT 5 OFFSET 10")
    r.query("I", "SELECT a FROM t1 ORDER BY a LIMIT 10, 5")
    r.query("I", "SELECT a FROM t1 WHERE b IS NULL ORDER BY a LIMIT 3")
    r.query("I", "SELECT a FROM t1 ORDER BY a LIMIT -1 OFFSET 25")
    r.query("I", "SELECT a FROM t1 ORDER BY a LIMIT 0")

    # ================= select3.test(官方 select3 场景:DISTINCT) =================
    r = new_file("select3")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT)")
    r.stmt_ok("INSERT INTO t1 VALUES(1,'x'),(2,'y'),(1,'x'),(3,'z'),(2,'y'),(1,'w'),(NULL,'n'),(NULL,'n')")
    r.query("I", "SELECT DISTINCT a FROM t1 ORDER BY a")
    r.query("T", "SELECT DISTINCT b FROM t1 ORDER BY b")
    r.query("IT", "SELECT DISTINCT a, b FROM t1 ORDER BY a, b")
    r.query("I", "SELECT DISTINCT a FROM t1 WHERE a IS NOT NULL ORDER BY a")
    r.query("I", "SELECT DISTINCT a FROM t1 ORDER BY a LIMIT 2")
    r.query("T", "SELECT DISTINCT b FROM t1 ORDER BY b LIMIT 2 OFFSET 1")
    r.query("I", "SELECT DISTINCT a+1 FROM t1 ORDER BY a+1")
    r.query("T", "SELECT DISTINCT b FROM t1 ORDER BY b DESC")
    # collation 参与 DISTINCT
    r.stmt_ok("CREATE TABLE t2(a TEXT COLLATE NOCASE)")
    r.stmt_ok("INSERT INTO t2 VALUES('a'),('A'),('b'),('B'),('a')")
    r.query("T", "SELECT DISTINCT a FROM t2 ORDER BY a")
    # int/float 数值视为相同
    r.stmt_ok("CREATE TABLE t3(a)")
    r.stmt_ok("INSERT INTO t3 VALUES(1),(1.0),(2),(2.0),(3)")
    r.query("T", "SELECT DISTINCT a FROM t3 ORDER BY a")
    # DISTINCT + WHERE + LIMIT/OFFSET
    r.stmt_ok("CREATE TABLE t4(a INTEGER)")
    r.stmt_ok("INSERT INTO t4 VALUES(1),(2),(1),(3),(2),(4),(5),(3)")
    r.query("I", "SELECT DISTINCT a FROM t4 WHERE a >= 2 ORDER BY a LIMIT 2")
    r.query("I", "SELECT DISTINCT a FROM t4 WHERE a >= 2 ORDER BY a LIMIT 2 OFFSET 1")

    # ================= select4.test(官方 select4 场景:ORDER BY collation/LIMIT) =================
    r = new_file("select4")
    r.stmt_ok("CREATE TABLE t1(a1 INTEGER, a2 INTEGER, a3 INTEGER, a4 INTEGER, a5 INTEGER)")
    r.stmt_ok("INSERT INTO t1 VALUES(5,4,3,2,1),(1,2,3,4,5),(3,3,3,3,3),(2,4,1,5,3),(4,1,5,2,3)")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 DESC")
    r.query("II", "SELECT a1, a2 FROM t1 ORDER BY a1, a2")
    r.query("II", "SELECT a1, a2 FROM t1 ORDER BY a2, a1")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT 2")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT 2 OFFSET 2")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 DESC LIMIT 3")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT -1 OFFSET 1")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT 0")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT 2+2")
    r.query("I", "SELECT a1 FROM t1 ORDER BY a1 LIMIT 2, 3")
    # 文本 collation 排序
    r.stmt_ok("CREATE TABLE t2(a TEXT COLLATE NOCASE, b TEXT COLLATE BINARY)")
    r.stmt_ok("INSERT INTO t2 VALUES('apple','Z'),('Apple','y'),('banana','X'),('BANANA','w'),('cherry','v')")
    r.query("T", "SELECT a FROM t2 ORDER BY a")
    r.query("T", "SELECT a FROM t2 ORDER BY a COLLATE BINARY")
    r.query("T", "SELECT a FROM t2 ORDER BY a DESC")
    r.query("T", "SELECT b FROM t2 ORDER BY b")
    r.query("T", "SELECT a FROM t2 ORDER BY a LIMIT 2 OFFSET 1")
    r.query("T", "SELECT DISTINCT a FROM t2 ORDER BY a")

    # ================= select5.test(官方 select5 为全连接 → 重构单表组合) =================
    r = new_file("select5")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT)")
    r.stmt_ok("INSERT INTO t1 VALUES(3,'c'),(1,'a'),(2,'b'),(1,'a'),(3,'d'),(2,'b'),(1,'e')")
    r.query("I", "SELECT DISTINCT a FROM t1 WHERE b >= 'b' ORDER BY a LIMIT 2")
    r.query("IT", "SELECT a, b FROM t1 WHERE a >= 2 ORDER BY a DESC, b LIMIT 3")
    r.query("IT", "SELECT DISTINCT a, b FROM t1 ORDER BY a, b LIMIT 3 OFFSET 1")
    r.query("T", "SELECT DISTINCT b FROM t1 WHERE a = 1 ORDER BY b")
    r.query("I", "SELECT a FROM t1 ORDER BY a LIMIT 2, 3")
    r.query("I", "SELECT DISTINCT a FROM t1 ORDER BY a LIMIT -1 OFFSET 1")
    r.query("I", "SELECT a FROM t1 WHERE b LIKE 'a%' OR b LIKE 'e%' ORDER BY a")
    r.query("I", "SELECT a FROM t1 WHERE a BETWEEN 1 AND 2 ORDER BY a")
    r.query("T", "SELECT DISTINCT b FROM t1 ORDER BY b DESC LIMIT 2")
    # 常量投影 + LIMIT/OFFSET/DISTINCT
    r.query("II", "SELECT 1, 2 LIMIT 1")
    r.query("II", "SELECT DISTINCT 1, 2")
    r.query("I", "SELECT 1 WHERE 1 LIMIT 0")
    r.query("I", "SELECT 1 WHERE 0 LIMIT 1")

    # ================= index1.test(官方 index*.test 场景:CREATE/DROP INDEX) =================
    r = new_file("index1")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT, c TEXT)")
    r.stmt_ok("INSERT INTO t1 VALUES(1,'x','a'),(2,'y','b'),(3,'x','c')")
    # 普通索引:单列/多列/含 COLLATE;索引存在不影响查询结果
    r.stmt_ok("CREATE INDEX idx1 ON t1(a)")
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    r.stmt_ok("CREATE INDEX idx2 ON t1(b, a)")
    r.stmt_ok("CREATE INDEX idx3 ON t1(c COLLATE NOCASE)")
    r.query("T", "SELECT c FROM t1 ORDER BY c")
    r.stmt_ok("INSERT INTO t1 VALUES(4,'w','d')")
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    # 索引名冲突
    r.stmt_err("CREATE INDEX idx1 ON t1(b)", "index idx1 already exists")
    # 未知列/未知表
    r.stmt_err("CREATE INDEX idxz ON t1(z)", "no such column")
    r.stmt_err("CREATE INDEX idxt ON nosuch(a)", "no such table")
    # DROP INDEX
    r.stmt_ok("DROP INDEX idx1")
    r.stmt_err("DROP INDEX idx1", "no such index")
    r.stmt_err("DROP INDEX nosuch", "no such index")

    # ================= index2.test(官方 index*.test 场景:UNIQUE INDEX) =================
    r = new_file("index2")
    r.stmt_ok("CREATE TABLE t1(a INTEGER, b TEXT)")
    r.stmt_ok("CREATE UNIQUE INDEX uidx ON t1(a)")
    r.stmt_ok("INSERT INTO t1 VALUES(1,'x'),(2,'y')")
    r.stmt_err("INSERT INTO t1 VALUES(1,'z')", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t1 VALUES(NULL,'n1'),(NULL,'n2')")  # UNIQUE 允许多 NULL
    r.query("I", "SELECT a FROM t1 ORDER BY a")
    # UNIQUE 索引创建时已有重复数据 → 失败
    r.stmt_ok("CREATE TABLE t2(a INTEGER)")
    r.stmt_ok("INSERT INTO t2 VALUES(1),(1)")
    r.stmt_err("CREATE UNIQUE INDEX u2 ON t2(a)", "UNIQUE constraint failed")
    # UNIQUE 多列索引
    r.stmt_ok("CREATE TABLE t3(a INTEGER, b INTEGER)")
    r.stmt_ok("CREATE UNIQUE INDEX u3 ON t3(a, b)")
    r.stmt_ok("INSERT INTO t3 VALUES(1,1),(1,2)")
    r.stmt_err("INSERT INTO t3 VALUES(1,1)", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t3 VALUES(1,3)")
    # UNIQUE 索引含 COLLATE
    r.stmt_ok("CREATE TABLE t4(a TEXT)")
    r.stmt_ok("CREATE UNIQUE INDEX u4 ON t4(a COLLATE NOCASE)")
    r.stmt_ok("INSERT INTO t4 VALUES('abc')")
    r.stmt_err("INSERT INTO t4 VALUES('ABC')", "UNIQUE constraint failed")
    # UPDATE 违反唯一索引
    r.stmt_ok("CREATE TABLE t5(a INTEGER)")
    r.stmt_ok("CREATE UNIQUE INDEX u5 ON t5(a)")
    r.stmt_ok("INSERT INTO t5 VALUES(1),(2)")
    r.stmt_err("UPDATE t5 SET a = 1 WHERE a = 2", "UNIQUE constraint failed")
    # DROP UNIQUE INDEX 后不再强制
    r.stmt_ok("DROP INDEX u5")
    r.stmt_ok("INSERT INTO t5 VALUES(2)")
    r.query("I", "SELECT a FROM t5 ORDER BY a")

    # ================= table1.test(官方 table*.test 场景:PRIMARY KEY / UNIQUE) =================
    r = new_file("table1")
    # 列级 PRIMARY KEY
    r.stmt_ok("CREATE TABLE t1(a INTEGER PRIMARY KEY, b TEXT)")
    r.stmt_ok("INSERT INTO t1 VALUES(1,'x')")
    r.stmt_err("INSERT INTO t1 VALUES(1,'y')", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t1 VALUES(2,'z')")
    r.query("IT", "SELECT a, b FROM t1 ORDER BY a")
    # INTEGER PRIMARY KEY:NULL 自动分配
    r.stmt_ok("CREATE TABLE t2(a INTEGER PRIMARY KEY)")
    r.stmt_ok("INSERT INTO t2 VALUES(NULL),(NULL)")
    r.query("I", "SELECT a FROM t2 ORDER BY a")
    # TEXT PRIMARY KEY:NULL 允许多个(SQLite 非 INTEGER PK 不隐式 NOT NULL)
    r.stmt_ok("CREATE TABLE t3(a TEXT PRIMARY KEY)")
    r.stmt_ok("INSERT INTO t3 VALUES(NULL),(NULL),('k')")
    r.query("T", "SELECT a FROM t3 ORDER BY a")
    # 列级 UNIQUE
    r.stmt_ok("CREATE TABLE t4(a INTEGER UNIQUE, b TEXT)")
    r.stmt_ok("INSERT INTO t4 VALUES(1,'x')")
    r.stmt_err("INSERT INTO t4 VALUES(1,'y')", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t4 VALUES(NULL,'n1'),(NULL,'n2')")
    r.query("IT", "SELECT a, b FROM t4 ORDER BY a")
    # 表级 PRIMARY KEY 多列
    r.stmt_ok("CREATE TABLE t5(a INTEGER, b TEXT, PRIMARY KEY(a, b))")
    r.stmt_ok("INSERT INTO t5 VALUES(1,'x')")
    r.stmt_err("INSERT INTO t5 VALUES(1,'x')", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t5 VALUES(1,'y')")
    # 表级 UNIQUE 多列
    r.stmt_ok("CREATE TABLE t6(a INTEGER, b TEXT, UNIQUE(a, b))")
    r.stmt_ok("INSERT INTO t6 VALUES(1,'x')")
    r.stmt_err("INSERT INTO t6 VALUES(1,'x')", "UNIQUE constraint failed")
    r.stmt_ok("INSERT INTO t6 VALUES(1,'y')")
    # AUTOINCREMENT 解析(行为同 INTEGER PK)
    r.stmt_ok("CREATE TABLE t7(a INTEGER PRIMARY KEY AUTOINCREMENT, b TEXT)")
    r.stmt_ok("INSERT INTO t7(b) VALUES('x')")
    r.query("IT", "SELECT a, b FROM t7")

    # ================= table2.test(官方 table*.test 场景:NOT NULL / CHECK / DEFAULT) =================
    r = new_file("table2")
    # NOT NULL
    r.stmt_ok("CREATE TABLE t1(a INTEGER NOT NULL)")
    r.stmt_ok("INSERT INTO t1 VALUES(1)")
    r.stmt_err("INSERT INTO t1 VALUES(NULL)", "NOT NULL constraint failed")
    r.stmt_ok("CREATE TABLE t2(a INTEGER NOT NULL DEFAULT 5)")
    r.stmt_ok("INSERT INTO t2 DEFAULT VALUES")
    r.query("I", "SELECT a FROM t2")
    # CHECK 列级
    r.stmt_ok("CREATE TABLE t3(a INTEGER CHECK(a > 0))")
    r.stmt_ok("INSERT INTO t3 VALUES(1)")
    r.stmt_err("INSERT INTO t3 VALUES(0)", "CHECK constraint failed")
    r.stmt_ok("INSERT INTO t3 VALUES(NULL)")  # CHECK 遇 NULL 通过
    r.query("I", "SELECT a FROM t3 ORDER BY a")
    # CHECK 表级
    r.stmt_ok("CREATE TABLE t4(a INTEGER, CHECK(a >= 0 AND a < 10))")
    r.stmt_ok("INSERT INTO t4 VALUES(5)")
    r.stmt_err("INSERT INTO t4 VALUES(10)", "CHECK constraint failed")
    # CHECK 引用其他列
    r.stmt_ok("CREATE TABLE t5(a INTEGER, b INTEGER CHECK(b < a))")
    r.stmt_ok("INSERT INTO t5 VALUES(5, 3)")
    r.stmt_err("INSERT INTO t5 VALUES(2, 9)", "CHECK constraint failed")
    # CHECK 违反在 UPDATE
    r.stmt_ok("CREATE TABLE t6(a INTEGER CHECK(a > 0))")
    r.stmt_ok("INSERT INTO t6 VALUES(1)")
    r.stmt_err("UPDATE t6 SET a = -5", "CHECK constraint failed")
    # DEFAULT 括号表达式
    r.stmt_ok("CREATE TABLE t7(a INTEGER DEFAULT (1+2))")
    r.stmt_ok("INSERT INTO t7 DEFAULT VALUES")
    r.query("IT", "SELECT a, typeof(a) FROM t7")
    # 约束组合:PK + UNIQUE + NOT NULL
    r.stmt_ok("CREATE TABLE t8(a INTEGER PRIMARY KEY, b TEXT UNIQUE NOT NULL)")
    r.stmt_ok("INSERT INTO t8 VALUES(1,'x')")
    r.stmt_err("INSERT INTO t8 VALUES(1,'y')", "UNIQUE constraint failed")
    r.stmt_err("INSERT INTO t8 VALUES(2,'x')", "UNIQUE constraint failed")
    r.stmt_err("INSERT INTO t8 VALUES(2,NULL)", "NOT NULL constraint failed")
    r.query("IT", "SELECT a, b FROM t8")
    # 多行 INSERT 原子性:任一行违反则整条失败
    r.stmt_ok("CREATE TABLE t9(a INTEGER UNIQUE)")
    r.stmt_ok("INSERT INTO t9 VALUES(1),(2)")
    r.stmt_err("INSERT INTO t9 VALUES(3),(1),(4)", "UNIQUE constraint failed")
    r.query("I", "SELECT a FROM t9 ORDER BY a")

    for fb in files.values():
        fb.close()
    return files


def main():
    files = build_records()
    TEST.mkdir(exist_ok=True)
    order = [
        "types", "cast", "expr1", "expr2", "expr3", "func1", "func2", "func3",
        "func4", "func5", "like", "in", "null", "collate1", "collate2",
        "collate3", "collate4", "collate5",
        "insert1", "update1", "delete1", "select2", "select3", "select4",
        "select5",
        "index1", "index2", "table1", "table2",
    ]
    for name in order:
        fb = files[name]
        path = TEST / f"{name}.test"
        path.write_text("".join(fb.recs), encoding="utf-8")
        nrec = sum(1 for r in fb.recs if r.startswith("query") or r.startswith("statement"))
        print(f"wrote {path.name}: {nrec} records")


if __name__ == "__main__":
    main()

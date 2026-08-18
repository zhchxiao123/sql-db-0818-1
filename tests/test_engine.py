"""引擎单元测试:解析、执行、比对的最小内核覆盖。

运行:python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

# 保证在未安装(pip install -e .)时也能从 src 布局导入
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from sql_db_0818_1.executor import QueryResult, execute  # noqa: E402
from sql_db_0818_1.parser import SqlParseError, parse  # noqa: E402
from sql_db_0818_1.storage import Database, SqlError  # noqa: E402


class CreateInsertTest(unittest.TestCase):
    def test_create_and_insert_full_row(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t VALUES(1, 'x')"))
        r = execute(db, parse("SELECT a, b FROM t"))
        self.assertEqual(r.rows, [[1, "x"]])

    def test_insert_multi_row(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER)"))
        execute(db, parse("INSERT INTO t VALUES(1), (2), (3)"))
        r = execute(db, parse("SELECT a FROM t"))
        self.assertEqual(r.rows, [[1], [2], [3]])

    def test_insert_column_list(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t(b, a) VALUES('y', 2)"))
        r = execute(db, parse("SELECT a, b FROM t"))
        self.assertEqual(r.rows, [[2, "y"]])

    def test_insert_unspecified_column_null(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t(a) VALUES(5)"))
        r = execute(db, parse("SELECT a, b FROM t"))
        self.assertEqual(r.rows, [[5, None]])

    def test_create_duplicate_table_error(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER)"))
        with self.assertRaises(SqlError):
            execute(db, parse("CREATE TABLE t(a INTEGER)"))

    def test_insert_unknown_table_error(self):
        db = Database()
        with self.assertRaises(SqlError):
            execute(db, parse("INSERT INTO t VALUES(1)"))

    def test_affinity_integer_text(self):
        # INTEGER 亲和:可解析数字的文本转数值;不可解析的保留文本
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t VALUES('42', 42)"))
        r = execute(db, parse("SELECT a, b FROM t"))
        self.assertEqual(r.rows, [[42, "42"]])


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        execute(self.db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(
            self.db,
            parse("INSERT INTO t VALUES(1,'a'),(2,'b'),(3,'c'),(4,'d'),(5,'e')"),
        )

    def test_select_constant_no_from(self):
        r = execute(self.db, parse("SELECT 42"))
        self.assertEqual(r.rows, [[42]])

    def test_select_column_ref(self):
        r = execute(self.db, parse("SELECT a FROM t"))
        self.assertEqual(r.rows, [[1], [2], [3], [4], [5]])

    def test_where_comparison(self):
        r = execute(self.db, parse("SELECT a FROM t WHERE a>3"))
        self.assertEqual(r.rows, [[4], [5]])

    def test_where_and_or_not(self):
        r = execute(self.db, parse("SELECT a FROM t WHERE a>1 AND a<4"))
        self.assertEqual(r.rows, [[2], [3]])
        r = execute(self.db, parse("SELECT a FROM t WHERE a=1 OR a=5"))
        self.assertEqual(r.rows, [[1], [5]])
        r = execute(self.db, parse("SELECT a FROM t WHERE NOT a=3"))
        self.assertEqual(r.rows, [[1], [2], [4], [5]])

    def test_where_text(self):
        r = execute(self.db, parse("SELECT a FROM t WHERE b='d'"))
        self.assertEqual(r.rows, [[4]])

    def test_order_by(self):
        r = execute(self.db, parse("SELECT a FROM t ORDER BY a DESC"))
        self.assertEqual(r.rows, [[5], [4], [3], [2], [1]])
        r = execute(self.db, parse("SELECT a FROM t ORDER BY b"))
        self.assertEqual(r.rows, [[1], [2], [3], [4], [5]])

    def test_order_by_ordinal(self):
        r = execute(self.db, parse("SELECT a FROM t ORDER BY 1 DESC"))
        self.assertEqual(r.rows, [[5], [4], [3], [2], [1]])

    def test_limit(self):
        r = execute(self.db, parse("SELECT a FROM t LIMIT 2"))
        self.assertEqual(r.rows, [[1], [2]])
        r = execute(self.db, parse("SELECT a FROM t ORDER BY a DESC LIMIT 2"))
        self.assertEqual(r.rows, [[5], [4]])
        r = execute(self.db, parse("SELECT a FROM t LIMIT 0"))
        self.assertEqual(r.rows, [])

    def test_unknown_column_error(self):
        with self.assertRaises(SqlError):
            execute(self.db, parse("SELECT z FROM t"))


class ParserTest(unittest.TestCase):
    def test_parse_error(self):
        with self.assertRaises(SqlParseError):
            parse("SELECT FROM")
        with self.assertRaises(SqlParseError):
            parse("DROP TABLE t")

    def test_trailing_semicolon_ok(self):
        stmt = parse("SELECT 1;")
        self.assertIsNotNone(stmt)

    def test_multiline_sql(self):
        stmt = parse("SELECT a\nFROM t\nWHERE a>1\nORDER BY a\nLIMIT 2")
        self.assertIsNotNone(stmt)


class SqllogictestRunnerTest(unittest.TestCase):
    def test_hash_record(self):
        from sql_db_0818_1 import sqllogictest as slt

        db = Database()
        execute(db, parse("CREATE TABLE t1(a INTEGER, b INTEGER)"))
        execute(db, parse("INSERT INTO t1 VALUES(1,2),(3,4)"))
        rec = slt.QueryRecord(
            line=1,
            types="I",
            sort_mode=slt.SORT_NOSORT,
            sql="SELECT a FROM t1 ORDER BY 1",
            hash_expected=(2, "0a88863510308751293f4b91afc07dd6"),  # md5("1\n3\n")
        )
        self.assertIsNone(slt.run_query(db, rec))

    def test_mismatch_reports_location(self):
        from sql_db_0818_1 import sqllogictest as slt

        db = Database()
        execute(db, parse("CREATE TABLE t1(a INTEGER)"))
        execute(db, parse("INSERT INTO t1 VALUES(1),(2)"))
        rec = slt.QueryRecord(
            line=7,
            types="I",
            sort_mode=slt.SORT_ROWSORT,
            sql="SELECT a FROM t1",
            expected_rows=[["9"]],
        )
        err = slt.run_query(db, rec)
        self.assertIsNotNone(err)
        self.assertIn("结果集不一致", err)


# ---------------------------------------------------------------- 子需求 1:表达式系统
class ArithmeticTest(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        execute(self.db, parse("CREATE TABLE t(a INTEGER, b INTEGER)"))
        execute(self.db, parse("INSERT INTO t VALUES(10, 3), (7, 2), (-10, 3)"))

    def test_arith_ops(self):
        r = execute(self.db, parse("SELECT a+b FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[-7], [9], [13]])
        r = execute(self.db, parse("SELECT a-b FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[-13], [5], [7]])
        r = execute(self.db, parse("SELECT a*b FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[-30], [14], [30]])

    def test_int_division_trunc_toward_zero(self):
        r = execute(self.db, parse("SELECT a/b FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[-3], [3], [3]])  # -10/3 = -3(向零)
        r = execute(self.db, parse("SELECT -7/2"))
        self.assertEqual(r.rows, [[-3]])

    def test_modulo_c_style(self):
        r = execute(self.db, parse("SELECT a%b FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[-1], [1], [1]])  # -10%3 = -1(符号随被除数)
        r = execute(self.db, parse("SELECT 10%-3"))
        self.assertEqual(r.rows, [[1]])

    def test_division_by_zero_null(self):
        r = execute(self.db, parse("SELECT 1/0"))
        self.assertEqual(r.rows, [[None]])
        r = execute(self.db, parse("SELECT 1%0"))
        self.assertEqual(r.rows, [[None]])

    def test_real_division(self):
        r = execute(self.db, parse("SELECT 7.0/2"))
        self.assertEqual(r.rows, [[3.5]])
        r = execute(self.db, parse("SELECT 10/3.0"))
        self.assertEqual(r.rows, [[3.3333333333333335]])

    def test_int64_overflow_to_real(self):
        r = execute(self.db, parse("SELECT 9223372036854775807 + 1"))
        self.assertEqual(r.rows, [[9.223372036854776e18]])
        r = execute(self.db, parse("SELECT typeof(9223372036854775807 * 2)"))
        self.assertEqual(r.rows, [["real"]])

    def test_concat(self):
        r = execute(self.db, parse("SELECT 'a'||1||2.5"))
        self.assertEqual(r.rows, [["a12.5"]])
        r = execute(self.db, parse("SELECT x'41'||x'42'"))
        self.assertEqual(r.rows, [["AB"]])  # BLOB||BLOB → TEXT
        r = execute(self.db, parse("SELECT 'a'||NULL"))
        self.assertEqual(r.rows, [[None]])

    def test_text_numeric_coercion(self):
        r = execute(self.db, parse("SELECT '2'+3"))
        self.assertEqual(r.rows, [[5]])
        r = execute(self.db, parse("SELECT '2.5'+1"))
        self.assertEqual(r.rows, [[3.5]])
        r = execute(self.db, parse("SELECT 'abc'+1"))
        self.assertEqual(r.rows, [[1]])

    def test_unary_minus_plus(self):
        r = execute(self.db, parse("SELECT -'5', -'5.5', -'abc', +'5', +5"))
        self.assertEqual(r.rows, [[-5, -5.5, 0, "5", 5]])

    def test_precedence(self):
        # || 高于 * / % 高于 + -;与 sqlite 一致:1||2*3 = (1||2)*3 = 36
        r = execute(self.db, parse("SELECT 1||2*3"))
        self.assertEqual(r.rows, [[36]])
        r = execute(self.db, parse("SELECT 1+2||3"))
        self.assertEqual(r.rows, [[24]])
        r = execute(self.db, parse("SELECT 1+2*3"))
        self.assertEqual(r.rows, [[7]])


class ComparisonTest(unittest.TestCase):
    def test_is_null_safe(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER)"))
        execute(db, parse("INSERT INTO t VALUES(NULL),(1)"))
        r = execute(db, parse("SELECT a IS NULL FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[1], [0]])
        r = execute(db, parse("SELECT a IS NOT NULL FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[0], [1]])
        r = execute(db, parse("SELECT NULL IS NULL, NULL IS NOT NULL, 1 ISNULL, NULL ISNULL"))
        self.assertEqual(r.rows, [[1, 0, 0, 1]])

    def test_is_no_affinity(self):
        r = execute(Database(), parse("SELECT 1 IS '1', 1 IS 1.0, 'a' IS 'a'"))
        self.assertEqual(r.rows, [[0, 1, 1]])

    def test_column_affinity_comparison(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT, c REAL)"))
        execute(db, parse("INSERT INTO t VALUES(1,'1',1.0),(2,'2',2.0)"))
        r = execute(db, parse("SELECT a='1', b=1, c='2', a=b, a=c, b=c FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[1, 1, 0, 1, 1, 1], [0, 0, 1, 1, 1, 1]])

    def test_storage_class_order(self):
        r = execute(Database(), parse("SELECT 1 < 'a', 'a' < x'61', NULL < 1"))
        self.assertEqual(r.rows, [[1, 1, None]])

    def test_chained_comparison_left_assoc(self):
        r = execute(Database(), parse("SELECT 1<2<3, 3>2>1, 1=1=1"))
        self.assertEqual(r.rows, [[1, 0, 1]])


class LogicTest(unittest.TestCase):
    def test_three_valued_logic(self):
        r = execute(Database(), parse("SELECT 1 AND NULL, 0 AND NULL, NULL AND NULL"))
        self.assertEqual(r.rows, [[None, 0, None]])
        r = execute(Database(), parse("SELECT 1 OR NULL, 0 OR NULL, NULL OR NULL"))
        self.assertEqual(r.rows, [[1, None, None]])
        r = execute(Database(), parse("SELECT NOT NULL, NOT 'abc', NOT '2'"))
        self.assertEqual(r.rows, [[None, 1, 0]])

    def test_truthiness(self):
        r = execute(Database(), parse("SELECT 'abc' AND 1, '2' AND 1, '' AND 1, x'31' AND 1"))
        self.assertEqual(r.rows, [[0, 1, 0, 1]])


class CastTest(unittest.TestCase):
    def test_cast_int_prefix(self):
        r = execute(Database(), parse("SELECT CAST('123abc' AS INTEGER), CAST('abc' AS INTEGER), CAST('12.7' AS INTEGER)"))
        self.assertEqual(r.rows, [[123, 0, 12]])
        r = execute(Database(), parse("SELECT CAST('1e3' AS INTEGER)"))
        self.assertEqual(r.rows, [[1]])  # 整数前缀解析忽略指数

    def test_cast_real(self):
        r = execute(Database(), parse("SELECT CAST('12.7' AS REAL), CAST('abc' AS REAL), CAST('1e3' AS REAL)"))
        self.assertEqual(r.rows, [[12.7, 0.0, 1000.0]])

    def test_cast_text_blob_numeric(self):
        r = execute(Database(), parse("SELECT CAST(42 AS TEXT), CAST(1.5 AS TEXT)"))
        self.assertEqual(r.rows, [["42", "1.5"]])
        r = execute(Database(), parse("SELECT typeof(CAST('ab' AS BLOB)), hex(CAST(1 AS BLOB))"))
        self.assertEqual(r.rows, [["blob", "31"]])
        r = execute(Database(), parse("SELECT CAST('abc' AS NUMERIC), CAST('1.5' AS NUMERIC), CAST(2.0 AS NUMERIC)"))
        self.assertEqual(r.rows, [[0, 1.5, 2.0]])

    def test_cast_int64_clamp(self):
        r = execute(Database(), parse("SELECT CAST(18446744073709551615 AS INTEGER)"))
        self.assertEqual(r.rows, [[9223372036854775807]])

    def test_cast_affinity_in_comparison(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(b TEXT)"))
        execute(db, parse("INSERT INTO t VALUES('1'),('x')"))
        r = execute(db, parse("SELECT CAST(b AS INTEGER)=1 FROM t ORDER BY b"))
        self.assertEqual(r.rows, [[1], [0]])


class FunctionTest(unittest.TestCase):
    def test_abs(self):
        r = execute(Database(), parse("SELECT abs(-5), abs(-5.5), abs('abc'), abs('-3'), typeof(abs('-3'))"))
        self.assertEqual(r.rows, [[5, 5.5, 0.0, 3.0, "real"]])

    def test_length(self):
        r = execute(Database(), parse("SELECT length('hello'), length(''), length(x'414243'), length(123), length('é')"))
        self.assertEqual(r.rows, [[5, 0, 3, 3, 1]])

    def test_substr(self):
        r = execute(Database(), parse("SELECT substr('hello',2), substr('hello',2,3), substr('hello',-3,2), substr('hello',0,3)"))
        self.assertEqual(r.rows, [["ello", "ell", "ll", "he"]])
        r = execute(Database(), parse("SELECT substr('abcdef',3,-1), substr('abcdef',0), substr('abc',NULL,1)"))
        self.assertEqual(r.rows, [["b", "abcdef", None]])

    def test_coalesce_ifnull_nullif(self):
        r = execute(Database(), parse("SELECT coalesce(NULL,NULL,'x'), ifnull(NULL,5), ifnull(2,5), nullif(1,1), nullif(1,2)"))
        self.assertEqual(r.rows, [["x", 5, 2, None, 1]])

    def test_typeof(self):
        r = execute(Database(), parse("SELECT typeof(NULL), typeof(1), typeof(1.5), typeof('x'), typeof(x'41')"))
        self.assertEqual(r.rows, [["null", "integer", "real", "text", "blob"]])

    def test_upper_lower_hex_quote(self):
        r = execute(Database(), parse("SELECT upper('AbC'), lower('AbC'), upper('äöü'), hex(1.5), hex(x'00ff10')"))
        self.assertEqual(r.rows, [["ABC", "abc", "äöü", "312E35", "00FF10"]])
        r = execute(Database(), parse("SELECT quote('a''b'), quote(x'00'), quote(NULL)"))
        self.assertEqual(r.rows, [["'a''b'", "X'00'", "NULL"]])

    def test_round(self):
        r = execute(Database(), parse("SELECT round(2.5), round(-2.5), round(2.675,2), round(123.456,-1)"))
        self.assertEqual(r.rows, [[3.0, -3.0, 2.67, 123.0]])
        r = execute(Database(), parse("SELECT typeof(round(3))"))
        self.assertEqual(r.rows, [["real"]])

    def test_minmax_sign_unicode_char(self):
        r = execute(Database(), parse("SELECT min(3,1,2), max(3,1,2), min('10','9'), min(NULL,1)"))
        self.assertEqual(r.rows, [[1, 3, "10", None]])
        r = execute(Database(), parse("SELECT sign(-5), sign('abc'), unicode('A'), unicode(''), char(65,66), char(NULL)"))
        self.assertEqual(r.rows, [[-1, None, 65, None, "AB", "\x00"]])

    def test_replace_instr_trim(self):
        r = execute(Database(), parse("SELECT replace('abc','b','B'), replace('abc','','x'), instr('abc',''), instr('abc','z')"))
        self.assertEqual(r.rows, [["aBc", "abc", 1, 0]])
        r = execute(Database(), parse("SELECT trim('xxabxx','x'), ltrim('abc','ab'), rtrim('abc','bc')"))
        self.assertEqual(r.rows, [["ab", "c", "a"]])

    def test_printf(self):
        r = execute(Database(), parse("SELECT printf('%d-%s', 42, 'x'), printf('%.2f', 3.14159), printf('%c', 65)"))
        self.assertEqual(r.rows, [["42-x", "3.14", "6"]])  # %c 取文本首字符

    def test_function_arg_count_error(self):
        with self.assertRaises(SqlError):
            execute(Database(), parse("SELECT coalesce(NULL)"))
        with self.assertRaises(SqlError):
            execute(Database(), parse("SELECT ifnull(1)"))
        with self.assertRaises(SqlError):
            execute(Database(), parse("SELECT no_such_func(1)"))


class LikeGlobTest(unittest.TestCase):
    def test_like(self):
        r = execute(Database(), parse("SELECT 'abc' LIKE 'a%', 'ABC' LIKE 'abc', 'abc' LIKE 'a_c', 'abc' LIKE 'A_C'"))
        self.assertEqual(r.rows, [[1, 1, 1, 1]])
        r = execute(Database(), parse("SELECT 'ä' LIKE 'Ä'"))
        self.assertEqual(r.rows, [[0]])  # 非 ASCII 不折叠

    def test_like_escape(self):
        r = execute(Database(), parse("SELECT 'a_b' LIKE 'a\\_b' ESCAPE '\\', 'axb' LIKE 'a\\_b' ESCAPE '\\'"))
        self.assertEqual(r.rows, [[1, 0]])
        r = execute(Database(), parse("SELECT 'a%b' LIKE 'a\\%b' ESCAPE '\\', 'a%c' LIKE 'a\\%c' ESCAPE 'z'"))
        self.assertEqual(r.rows, [[1, 0]])

    def test_like_blob_false(self):
        r = execute(Database(), parse("SELECT x'41' LIKE 'a', 'a' LIKE x'61', x'61' LIKE x'61'"))
        self.assertEqual(r.rows, [[0, 0, 0]])

    def test_like_null(self):
        r = execute(Database(), parse("SELECT NULL LIKE 'a%', 'a' LIKE NULL"))
        self.assertEqual(r.rows, [[None, None]])

    def test_not_like(self):
        r = execute(Database(), parse("SELECT 'abc' NOT LIKE 'a%', 'xyz' NOT LIKE 'a%'"))
        self.assertEqual(r.rows, [[0, 1]])

    def test_glob(self):
        r = execute(Database(), parse("SELECT 'abc' GLOB 'a*', 'abc' GLOB 'A*', 'abc' GLOB 'a?c', 'a1c' GLOB 'a[0-9]c'"))
        self.assertEqual(r.rows, [[1, 0, 1, 1]])
        r = execute(Database(), parse("SELECT 'axc' GLOB 'a[^x]c', 'a.c' GLOB 'a.c', 'a.c' GLOB 'a?.c'"))
        self.assertEqual(r.rows, [[0, 1, 0]])


class InBetweenCaseTest(unittest.TestCase):
    def test_in(self):
        r = execute(Database(), parse("SELECT 2 IN (1,2,3), 4 IN (1,2,3), 3 IN (1,2,NULL), 1 IN ()"))
        self.assertEqual(r.rows, [[1, 0, None, 0]])

    def test_in_null_semantics(self):
        r = execute(Database(), parse("SELECT NULL IN (1,2), 1 NOT IN (NULL,2), 2 NOT IN (NULL,2), 3 NOT IN (NULL,2)"))
        self.assertEqual(r.rows, [[None, None, 0, None]])

    def test_in_affinity(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t VALUES(1,'1'),(2,'2'),(3,'3')"))
        r = execute(db, parse("SELECT a IN ('1','2'), b IN (1,2), '2' IN (a), 2 IN (b) FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 0, 0]])

    def test_between(self):
        r = execute(Database(), parse("SELECT 5 BETWEEN 3 AND 7, 5 BETWEEN 7 AND 3, 2 BETWEEN NULL AND 3"))
        self.assertEqual(r.rows, [[1, 0, None]])
        r = execute(Database(), parse("SELECT 2 NOT BETWEEN 1 AND 3, 2 NOT BETWEEN NULL AND 3"))
        self.assertEqual(r.rows, [[0, None]])

    def test_case(self):
        r = execute(Database(), parse("SELECT CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' END, CASE NULL WHEN NULL THEN 'm' ELSE 'n' END"))
        self.assertEqual(r.rows, [["b", "n"]])
        r = execute(Database(), parse("SELECT CASE WHEN NULL THEN 1 WHEN 0 THEN 2 ELSE 3 END"))
        self.assertEqual(r.rows, [[3]])


class CollationTest(unittest.TestCase):
    def test_column_collation(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a TEXT, b TEXT COLLATE NOCASE, c TEXT COLLATE RTRIM)"))
        execute(db, parse("INSERT INTO t VALUES('abc','ABC','x  '),('ABD','abd','x')"))
        # ORDER BY a:BINARY 下 'ABD' < 'abc'(大写在小写前)
        r = execute(db, parse("SELECT a='abc', b='abc', c='x' FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[0, 0, 1], [1, 1, 1]])

    def test_order_by_collation(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(b TEXT COLLATE NOCASE)"))
        execute(db, parse("INSERT INTO t VALUES('ABC'),('aBc'),('abd')"))
        r = execute(db, parse("SELECT b FROM t ORDER BY b"))
        self.assertEqual(r.rows, [["ABC"], ["aBc"], ["abd"]])
        r = execute(db, parse("SELECT b FROM t ORDER BY b COLLATE BINARY"))
        self.assertEqual(r.rows, [["ABC"], ["aBc"], ["abd"]])

    def test_explicit_collate_wins(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a TEXT)"))
        execute(db, parse("INSERT INTO t VALUES('abc'),('ABD')"))
        # ORDER BY a:'ABD' < 'abc'(BINARY)
        r = execute(db, parse("SELECT a='ABC' COLLATE NOCASE FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[0], [1]])
        r = execute(db, parse("SELECT a COLLATE NOCASE='ABC' FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[0], [1]])

    def test_rtrim(self):
        r = execute(Database(), parse("SELECT 'abc  ' = 'abc' COLLATE RTRIM, '  abc' = 'abc' COLLATE RTRIM"))
        self.assertEqual(r.rows, [[1, 0]])

    def test_concat_collation_propagation(self):
        r = execute(Database(), parse("SELECT 'a' || 'b' COLLATE NOCASE = 'AB'"))
        self.assertEqual(r.rows, [[1]])

    def test_left_column_collation_priority(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a TEXT COLLATE BINARY, b TEXT COLLATE NOCASE)"))
        execute(db, parse("INSERT INTO t VALUES('abc','ABC')"))
        r = execute(db, parse("SELECT a=b FROM t"))
        self.assertEqual(r.rows, [[0]])  # 左列 BINARY 优先
        r = execute(db, parse("SELECT a=b COLLATE NOCASE FROM t"))
        self.assertEqual(r.rows, [[1]])  # 显式 COLLATE 覆盖


class CreateNoTypeTest(unittest.TestCase):
    def test_columns_without_type(self):
        db = Database()
        execute(db, parse("CREATE TABLE t1(a, b, c)"))
        execute(db, parse("INSERT INTO t1 VALUES(1, 1.5, 'x')"))
        r = execute(db, parse("SELECT typeof(a), typeof(b), typeof(c) FROM t1"))
        self.assertEqual(r.rows, [["integer", "real", "text"]])

    def test_where_no_from(self):
        r = execute(Database(), parse("SELECT 1 WHERE 1"))
        self.assertEqual(r.rows, [[1]])
        r = execute(Database(), parse("SELECT 1 WHERE 0"))
        self.assertEqual(r.rows, [])
        r = execute(Database(), parse("SELECT 1 WHERE NULL"))
        self.assertEqual(r.rows, [])

    def test_projection_alias(self):
        r = execute(Database(), parse("SELECT 2+3 AS x WHERE 1"))
        self.assertEqual(r.rows, [[5]])

    def test_select_star(self):
        db = Database()
        execute(db, parse("CREATE TABLE t(a INTEGER, b TEXT)"))
        execute(db, parse("INSERT INTO t VALUES(1,'x'),(2,'y')"))
        r = execute(db, parse("SELECT * FROM t ORDER BY a"))
        self.assertEqual(r.rows, [[1, "x"], [2, "y"]])


if __name__ == "__main__":
    unittest.main()

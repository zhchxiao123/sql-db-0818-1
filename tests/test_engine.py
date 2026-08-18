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


if __name__ == "__main__":
    unittest.main()

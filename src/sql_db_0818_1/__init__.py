"""sql-db-0818-1:sqlite 兼容的最小 SQL 引擎 + sqllogictest 运行器。

子模块:
- tokenizer:SQL 词法分析
- ast / parser:AST 与递归下降解析器(CREATE TABLE / CREATE INDEX / DROP INDEX /
  INSERT / UPDATE / DELETE / SELECT)
- storage:内存表存储(亲和转换、比较、CAST、LIKE/GLOB、collation、DEFAULT、
  索引与约束强制)
- executor:语句执行与表达式求值(算术/比较/逻辑/函数/CASE/IN/BETWEEN)
- sqllogictest:官方 sqllogictest .test 运行器

范围:CREATE TABLE(列级 COLLATE/DEFAULT、列级与表级约束 PRIMARY KEY/UNIQUE/
NOT NULL/CHECK)、CREATE/DROP INDEX(普通/UNIQUE、多列、COLLATE)、INSERT
(整行/多行/列清单/DEFAULT VALUES)、UPDATE(表达式赋值 + WHERE)、DELETE(WHERE)、
SELECT 投影(常量/列引用/算术/函数/CAST/CASE)、WHERE(三值逻辑/LIKE/GLOB/
IN/BETWEEN)、ORDER BY(任意表达式 + collation)、DISTINCT、LIMIT/OFFSET。
无连接、聚合、子查询、视图、触发器、事务、外键级联。纯标准库实现。
"""

from .executor import QueryResult, execute
from .parser import SqlParseError, parse
from .storage import Database, SqlError
from .tokenizer import SqlLexError

__all__ = [
    "Database",
    "QueryResult",
    "SqlError",
    "SqlLexError",
    "SqlParseError",
    "execute",
    "parse",
]

__version__ = "0.3.0"

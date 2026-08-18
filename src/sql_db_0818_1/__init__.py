"""sql-db-0818-1:SQL 引擎 + sqllogictest 运行器。

子模块:
- tokenizer:SQL 词法分析
- ast / parser:AST 与递归下降解析器(CREATE TABLE / INSERT / SELECT + 表达式)
- storage:内存表存储(亲和转换、存储类比较、排序规则)
- functions:SQLite 标量函数
- executor:语句执行与表达式求值
- sqllogictest:官方 sqllogictest .test 运行器

范围:CREATE TABLE、INSERT、SELECT(常量/列引用/算术/比较/逻辑/CAST/函数/
LIKE/GLOB/IN/BETWEEN/CASE/COLLATE/ORDER BY/LIMIT)、类型亲和与存储类转换、
NULL 三值逻辑、内建 collation(BINARY/NOCASE/RTRIM)。无连接、子查询、
GROUP BY 聚合、索引、事务、视图、触发器、DISTINCT。纯标准库实现。
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

__version__ = "0.2.0"

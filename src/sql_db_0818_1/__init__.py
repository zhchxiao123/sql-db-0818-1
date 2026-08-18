"""sql-db-0818-1:最小 SQL 引擎 + sqllogictest 运行器。

子模块:
- tokenizer:SQL 词法分析
- ast / parser:AST 与递归下降解析器(CREATE TABLE / INSERT / SELECT)
- storage:内存表存储(亲和转换、比较)
- executor:语句执行与表达式求值
- sqllogictest:官方 sqllogictest .test 运行器

范围:CREATE TABLE 基础形态、INSERT(整行/多行/列清单)、SELECT 常量与列引用、
简单 WHERE(比较 + AND/OR/NOT)、ORDER BY、LIMIT。无连接、聚合、子查询、
函数、索引、事务、视图、触发器、DISTINCT。纯标准库实现。
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

__version__ = "0.1.0"

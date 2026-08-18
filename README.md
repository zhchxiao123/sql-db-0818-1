# sql-db-0818-1

sqlite 兼容的最小 SQL 引擎 + sqllogictest 运行器(骨架版)。

## 技术栈

- **实现语言**:Python 3(>=3.9,纯标准库,无第三方依赖)
- **构建/运行**:无需构建;`make` 仅作命令聚合,内部直接调 `python3`
- **代码布局**:
  - `src/sql_db_0818_1/` — 引擎内核(tokenizer / ast / parser / storage / executor)
    与 sqllogictest 运行器(sqllogictest.py)
  - `test/*.test` — sqllogictest 基线夹具(期望值由 sqlite3 3.46.1 产出)
  - `tests/test_engine.py` — 引擎单元测试(unittest)
  - `vendor/sqllogictest/` — vendor 的官方 sqllogictest 套件(见下)

## 标准测试入口(一条命令)

```bash
make test
```

等价于:

```bash
python3 -m unittest discover -s tests -v   # 引擎单元测试
python3 run_sqllogictest.py                 # sqllogictest 运行器:跑 test/*.test
```

- `make test` 全部通过时退出码为 0;存在失败时退出码非 0。
- 也可单独运行 `python3 run_sqllogictest.py [file.test ...]`,输出逐文件
  通过/失败统计;不带参数时跑 `test/` 下全部 `*.test`。

## 支持范围(最小内核)

- `CREATE TABLE` 基础形态:列定义 + 类型名(INTEGER/TEXT/REAL/BLOB/NUMERIC、
  VARCHAR(n) 等,按 SQLite 亲和规则转换存储类)
- `INSERT`:整行 / 多行 VALUES / 列清单,未指定列填 NULL
- `SELECT`:常量与列引用投影;无 FROM 常量投影
- 简单 `WHERE`:比较(= != <> < <= > >=)与 AND/OR/NOT 组合
- `ORDER BY`:列名或列序号,ASC/DESC
- `LIMIT`:整数截断

范围外(后续子需求):连接、子查询、聚合、函数、索引、视图、触发器、事务、
DISTINCT、UPDATE/DELETE、CASE/LIKE/IN/BETWEEN/CAST。

## sqllogictest 运行器

解析官方 `.test` 格式的 `statement` / `query`(含 `hash` 哈希比对)记录:
- `statement ok` / `statement error [pattern]`
- `query <types> [nosort|rowsort|valuesort] [label]` + `----` 期望区,
  支持 `N values hashing to <md5>` 哈希行
- 结果按 sqlite 文本格式比对:NULL→`NULL`、空串→`(empty)`、浮点 `%.3f`、
  不可打印字符→`@`
- 失败时输出记录定位(行号)与差异摘要;每个 `.test` 文件一行统计

## vendor 的官方 sqllogictest 套件

- **上游**:SQLite 官方 sqllogictest(fossil)https://www.sqlite.org/sqllogictest
- **固定 commit(checkin)**:`db57eba95d7c412bb413da5480c8be24`
  (trunk 顶,提交信息 "Several minor doc typo fixes from BrickViking.",
  2026-08-18 抓取)
- **vendor 方式与目录**:逐文件 HTTP 下载上游 `doc/<checkin>/test/*.test`
  原文到 `vendor/sqllogictest/`(select1~select5.test),字节原样,未改写;
  详见 `vendor/sqllogictest/VENDOR.md`(含 MD5 与复现命令)。

## 夹具与官方文件的对应关系

`test/*.test` 为按官方 select1 场景重构的基线夹具:表结构与数据行逐条取自
官方 `select1.test`(1 条 CREATE TABLE + 30 条 INSERT),查询用例限制在最小
内核范围,期望值由 sqlite3 3.46.1 实际执行产出;其中 7 条与官方完全相同的
查询直接沿用官方哈希期望值。逐文件对应关系见 `test/FIXTURES.md`。

## 已知口径

- 官方 select1.test 共 1,031 条记录,绝大多数依赖连接/子查询/聚合/CASE/
  算术等超出最小内核范围的特性;本骨架按需求口径以「sqlite3 3.46.1 期望值
  重构的 test/ 夹具」作为基线验收,不声称全量官方套件通过。
- 性能:解释型实现,未与 C 的 sqlite3 做 wall-clock 对标;后续子需求若要求
  全量套件性能对标 sqlite3,需另行评估。

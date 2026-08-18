# sql-db-0818-1

sqlite 兼容的 SQL 引擎 + sqllogictest 运行器。

## 技术栈

- **实现语言**:Python 3(>=3.9,纯标准库,无第三方依赖)
- **构建/运行**:无需构建;`make` 仅作命令聚合,内部直接调 `python3`
- **代码布局**:
  - `src/sql_db_0818_1/` — 引擎内核(tokenizer / ast / parser / storage /
    functions / executor)与 sqllogictest 运行器(sqllogictest.py)
  - `test/*.test` — sqllogictest 基线夹具 + 类型/表达式夹具(期望值由
    sqlite3 3.46.1 产出)
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

## 支持范围

语句与查询结构:

- `CREATE TABLE`:列定义 + 类型名(INTEGER/TEXT/REAL/BLOB/NUMERIC、VARCHAR(n)
  等,按 SQLite 亲和规则转换存储类;列级 COLLATE;列/表约束解析后忽略)
- `INSERT`:整行 / 多行 VALUES / 列清单,未指定列填 NULL
- `SELECT`:投影、`WHERE`、`ORDER BY`(列名或列序号,ASC/DESC,COLLATE)、
  `LIMIT`;无 FROM 常量投影;隐式 rowid(rowid/_rowid_/oid)列引用

类型系统与表达式(与 sqlite 语义一致):

- 类型亲和与存储类转换(INTEGER/REAL/TEXT/BLOB/NULL)
- 字面量:数值(含指数)/字符串/BLOB(X'..')/NULL/TRUE/FALSE
- 列引用(可带表限定)、一元 +/-/NOT
- 算术 `+ - * / %`、比较 `= != <> < <= > >=`(跨存储类比较的类型排序规则:
  NULL < 数值 < 文本 < BLOB)、逻辑 AND/OR/NOT 与 NULL 三值逻辑
- `CAST`(含 '123abc'→123 前缀解析与 NULL 传播)
- 标量函数:abs/length/substr/coalesce/ifnull/nullif/upper/lower/min/max/
  round/typeof/quote/replace/trim 系/instr/hex/char/unicode/sign/printf/
  like/glob
- `LIKE`/`GLOB`(通配符、大小写、ESCAPE、字符类)
- `IN`(含 NOT IN 与 NULL 语义)、`BETWEEN`、`CASE WHEN/ELSE`
- 排序规则:内建 BINARY/NOCASE/RTRIM,`COLLATE` 表达式对比较与 ORDER BY
  的影响(不构造 CREATE INDEX 用例)

范围外(后续子需求):连接、子查询、GROUP BY 聚合、索引、视图、触发器、事务、
DISTINCT、UPDATE/DELETE。

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

`test/*.test` 为按官方 sqllogictest 场景重构的夹具:表结构与数据行取自官方
`select1.test`(1 条 CREATE TABLE + 30 条 INSERT),类型/表达式/函数/LIKE/IN/
NULL/collation 用例按官方同名测试文件(scenario 名称 types/cast/expr1-3/
func1-5/like/in/null/collate1-5)的语义重构,期望值由 sqlite3 3.46.1 实际
执行产出。逐文件对应关系见 `test/FIXTURES.md`。

## 已知口径

- 官方 sqllogictest 仓库的 test/ 目录只含 select1~select5.test;types/cast/
  expr/func/like/in/null/collate 等场景名称来自官方同名测试文件的语义,官方
  仓库不逐字 vendor 这些文件,故以「sqlite3 3.46.1 期望值重构的 test/ 夹具」
  作为验收基线(与需求口径一致)。
- 继承的已知语义差异(见 result.json questions):substr(X,0,Z) 边界
  (sqlite 'h' vs 本引擎 'he')等,均无夹具覆盖,不影响验收;若后续需求要求
  严格一致需先裁决。
- 性能:解释型实现,未与 C 的 sqlite3 做 wall-clock 对标;后续子需求若要求
  全量套件性能对标 sqlite3,需另行评估。

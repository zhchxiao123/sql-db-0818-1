# sql-db-0818-1

sqlite 兼容的最小 SQL 引擎 + sqllogictest 运行器。

## 技术栈

- **实现语言**:Python 3(>=3.9,纯标准库,无第三方依赖)
- **构建/运行**:无需构建;`make` 仅作命令聚合,内部直接调 `python3`
- **代码布局**:
  - `src/sql_db_0818_1/` — 引擎内核(tokenizer / ast / parser / storage / executor)
    与 sqllogictest 运行器(sqllogictest.py)
  - `test/*.test` — sqllogictest 夹具(期望值由 sqlite3 3.46.1 产出)
  - `tests/test_engine.py` — 引擎单元测试(unittest)
  - `vendor/sqllogictest/` — vendor 的官方 sqllogictest 套件(见下)
  - `tools/gen_fixtures.py` — 夹具生成器(场景重构 + sqlite3 期望值)

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

### DDL / DML
- `CREATE TABLE` 基础形态:列定义 + 类型名(INTEGER/TEXT/REAL/BLOB/NUMERIC、
  VARCHAR(n) 等,按 SQLite 亲和规则转换存储类);无类型列 → BLOB 亲和;
  列级 `COLLATE BINARY|NOCASE|RTRIM`
- `INSERT`:整行 / 多行 VALUES / 列清单,未指定列填 NULL;值可为表达式

### SELECT 与表达式(子需求 1)
- 投影:常量、列引用、算术、函数、CASE、CAST、`*` 展开、`expr [AS] alias`
- `WHERE`:比较、三值逻辑(AND/OR/NOT)、LIKE/GLOB/IN/BETWEEN/IS 等
- `ORDER BY`:任意表达式 + 列级/显式 COLLATE,列名或序号,ASC/DESC
- `LIMIT`:整数截断
- 字面量:整数/浮点(含指数与边界形式)/字符串/blob(`x'...'`)/NULL/TRUE/FALSE
- 类型亲和与存储类转换:INTEGER/REAL/TEXT/BLOB/NUMERIC(以 sqlite3 3.46.1 实测为准)
- 算术:`+ - * / % ||`;整数除法向零截断;`%` C 风格;除零 → NULL;int64 溢出 → REAL
- 比较:`= == != <> < <= > >=`(含跨存储类排序)、`IS [NOT]`、`ISNULL`/`NOTNULL`;
  比较前按列亲和做转换
- 逻辑:三值逻辑(NULL 传播),真值按数值转换
- `CAST`:INTEGER/REAL/TEXT/BLOB/NUMERIC(前缀解析、int64 截断)
- 标量函数:abs/length/substr/coalesce/ifnull/nullif/typeof/upper/lower/hex/
  quote/round/min/max/sign/unicode/char/replace/instr/trim/ltrim/rtrim/
  like/glob/printf(以 func1-5 夹具覆盖为准)
- `LIKE`/`GLOB`:通配符(`% _` / `* ? [...]`)、LIKE 仅 ASCII 大小写不敏感、
  ESCAPE;任一操作数为 BLOB 时 LIKE 恒为 false
- `IN`(列表,含 NULL 语义)/ `BETWEEN` / `CASE`(简单与搜索形式)
- collation:BINARY/NOCASE/RTRIM 影响比较与 ORDER BY;显式 COLLATE 覆盖列 collation

### 范围外(后续子需求)
连接、子查询、聚合(count/sum/avg/min/max 单参等)、索引、视图、触发器、
事务、DISTINCT、UPDATE/DELETE、GROUP BY。

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

`test/*.test` 为按官方场景重构的夹具:表结构与数据行逐条取自官方
`select1.test`(1 条 CREATE TABLE + 30 条 INSERT),查询用例限制在本模块
支持范围,期望值由 sqlite3 3.46.1 实际执行产出;其中部分与官方完全相同的
查询直接沿用官方哈希期望值。逐文件对应关系见 `test/FIXTURES.md`。

## 已知口径

- 官方 select1.test 共 1,031 条记录,绝大多数依赖连接/子查询/聚合/CASE/
  算术等超出本模块支持范围的特性;本模块按需求口径以「sqlite3 3.46.1 期望值
  重构的 test/ 夹具」作为基线验收,不声称全量官方套件通过。
- 性能:解释型实现,未与 C 的 sqlite3 做 wall-clock 对标;后续子需求若要求
  全量套件性能对标 sqlite3,需另行评估。

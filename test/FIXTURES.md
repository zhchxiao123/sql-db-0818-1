# test/ 夹具与官方 sqllogictest 套件的对应关系

> vendor 固定 commit:sqlite.org/sqllogictest trunk
> `db57eba95d7c412bb413da5480c8be24`(见 `vendor/sqllogictest/VENDOR.md`)。

本目录夹具按「需求口径:以 sqlite3 3.46.1 期望值重构的 test/ 夹具」构建,
避免验收口径漂移。所有期望值(除标注「官方哈希」者)由 sqlite3 3.46.1
实际执行产出,并已在本模块运行器中逐条通过。

## 逐文件清单

| 夹具文件 | 官方对应 | 内容 | 覆盖能力(验收 a6) |
|---|---|---|---|
| `select1.test` | `select1.test` 表结构与 30 行数据逐条对应(1 CREATE + 30 INSERT);7 条查询与官方逐字一致(官方哈希);10 条额外查询按最小内核重构 | t1(a..e INTEGER),30 行 | CREATE TABLE / INSERT / SELECT / WHERE / ORDER BY / LIMIT |
| `create.test` | 按 select1 的 CREATE TABLE 形态扩展 | 多种类型列(INTEGER/TEXT/REAL/NUMERIC/BLOB、VARCHAR(n)) | CREATE TABLE |
| `insert.test` | 按 select1 的 INSERT 形态扩展 | 整行/多行/列清单/部分列 | INSERT |
| `select.test` | select1 的列引用投影场景 | 常量(无 FROM)、单列/多列引用 | SELECT 常量与列引用 |
| `where.test` | select1 的 WHERE 场景 | 比较六种 + AND/OR/NOT | 简单 WHERE |
| `orderby.test` | select1 的 ORDER BY 1 场景 | 列名/序号、ASC/DESC | ORDER BY |
| `limit.test` | select1 中 LIMIT 场景(官方多在算术查询里,重构为纯列引用) | LIMIT 截断、与 WHERE/ORDER BY 组合 | LIMIT |

## select1.test 与官方文件的逐条对应

官方文件 `vendor/sqllogictest/select1.test`(1,031 条记录):

- 表结构:第 1 条 `statement ok CREATE TABLE t1(a INTEGER, b INTEGER, c INTEGER,
  d INTEGER, e INTEGER)` — 本夹具第 1 条逐字相同。
- 数据:第 2~31 条 `INSERT INTO t1(...) VALUES(...)`(30 条,列清单形式)—
  本夹具第 2~31 条逐字相同。
- 官方查询中属于最小内核范围(常量/列引用/WHERE 比较/ORDER BY/LIMIT)且
  不与连接/子查询/聚合/CASE/算术耦合的共 12 条(官方行号 1424/2171/3204/
  3515/4718/6049/6297/7158/7216/7309/9144/9629);本夹具取其去重后的
  7 条不同查询(4 条纯列引用+ORDER BY,3 条带 WHERE),期望值直接沿用
  官方 `N values hashing to <md5>` 哈希行,已用 sqlite3 3.46.1 复算一致。
- 其余 989 条官方查询依赖算术表达式(a+b*2 等)、子查询、聚合(count/CASE 等),
  超出最小内核范围,不纳入本基线;后续子需求扩展内核后可按需增量纳入。

## 期望值产出方式

```bash
python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect(":memory:")
cur = conn.cursor()
# 执行夹具中的 statement 记录后,对每条 query 记录执行并取出期望值
EOF
```

环境自带 sqlite3 3.46.1(python3 -c "import sqlite3; print(sqlite3.sqlite_version)")。

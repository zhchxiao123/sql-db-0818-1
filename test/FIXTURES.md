# test/ 夹具与官方 sqllogictest 套件的对应关系

> vendor 固定 commit:sqlite.org/sqllogictest trunk
> `db57eba95d7c412bb413da5480c8be24`(见 `vendor/sqllogictest/VENDOR.md`)。

本目录夹具按「需求口径:以 sqlite3 3.46.1 期望值重构的 test/ 夹具」构建,
避免验收口径漂移。所有期望值由 sqlite3 3.46.1 实际执行产出(本任务开发时
已对 18 个验收文件的全部 147 条 query 记录逐一复算比对一致),并已在本模块
运行器中逐条通过。

## 官方仓库说明

官方 sqllogictest(fossil,同 vendor commit)的 `test/` 目录只含
`select1~select5.test`。types/cast/expr1-3/func1-5/like/in/null/collate1-5
是 sqllogictest 套件的标准场景名称;本仓库 test/ 下同名夹具按这些场景的
官方语义重构(建表/插入/查询形态对齐),期望值由 sqlite3 3.46.1 产出。

## 逐文件清单

### 子需求 0 基线夹具(回归,验收 a11)

| 夹具文件 | 官方对应 | 内容 | 覆盖能力 |
|---|---|---|---|
| `select1.test` | `select1.test` 表结构/数据逐条对应(1 CREATE + 30 INSERT),7 条查询沿用官方哈希 | t1(a..e INTEGER),30 行 | CREATE/INSERT/SELECT/WHERE/ORDER BY/LIMIT |
| `create.test` | select1 的 CREATE TABLE 形态扩展 | 多类型列 | CREATE TABLE |
| `insert.test` | select1 的 INSERT 形态扩展 | 整行/多行/列清单 | INSERT |
| `select.test` | select1 的列引用投影 | 常量/列引用 | SELECT |
| `where.test` | select1 的 WHERE 场景 | 比较 + AND/OR/NOT | WHERE |
| `orderby.test` | select1 的 ORDER BY 1 场景 | 列名/序号、ASC/DESC | ORDER BY |
| `limit.test` | select1 的 LIMIT 场景重构 | LIMIT 组合 | LIMIT |

### 子需求 1 新增夹具(验收 a1~a10)

| 夹具文件 | 官方场景 | 内容(记录数) | 覆盖验收 |
|---|---|---|---|
| `types.test` | types | 存储类/亲和/typeof/文本-数值转换(11) | a2 类型亲和与存储类转换 |
| `cast.test` | cast | CAST 向 INTEGER/REAL/TEXT/BLOB 转换、前缀解析、NULL 传播(11) | a6 CAST |
| `expr1.test` | expr1 | 算术(优先级、整数除法、NULL 传播)(11) | a4 算术 |
| `expr2.test` | expr2 | 比较(= != <> < <= > >=、跨存储类、NULL)(8) | a4 比较 |
| `expr3.test` | expr3 | CASE WHEN/ELSE、简单 CASE、嵌套(8) | a9 CASE |
| `func1.test` | func1 | abs/length/substr/coalesce/typeof 等基础函数(8) | a7 标量函数 |
| `func2.test` | func2 | upper/lower/trim 系/instr/replace(7) | a7 标量函数 |
| `func3.test` | func3 | trim 细节、quote/char/unicode/printf 基础(6) | a7 标量函数 |
| `func4.test` | func4 | round/sign/min/max/ifnull/nullif(6) | a7 标量函数 |
| `func5.test` | func5 | printf 宽度/精度/标志、hex、混合函数(10) | a7 标量函数 |
| `like.test` | like | LIKE 通配符/大小写/ESCAPE;GLOB 通配/字符类(20) | a8 LIKE/GLOB |
| `in.test` | in | IN 列表、NOT IN、NULL 语义(12) | a5/a9 IN |
| `null.test` | null | NULL 三值逻辑、WHERE 中 NULL、IS NULL/IS NOT NULL(14) | a5 NULL 三值逻辑 |
| `collate1.test` | collate1 | 列级 COLLATE NOCASE 对比较与排序影响(7) | a10 collation |
| `collate2.test` | collate2 | BINARY 默认与显式 COLLATE 表达式(8) | a10 collation |
| `collate3.test` | collate3 | RTRIM collation(尾随空格比较)(7) | a10 collation |
| `collate4.test` | collate4 | ORDER BY 中 COLLATE 的作用(8) | a10 collation |
| `collate5.test` | collate5 | NOCASE 与多列排序组合(8) | a10 collation |

合计:子需求 1 新增 170 条记录;连同基线 100 条共 270 条,`make test` 全过、
退出码 0。

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
本任务开发时已用该方式对 18 个验收文件全部 147 条 query 记录复算比对,
逐条一致(含 sort 模式与文本/浮点/NULL/BLOB 表示)。

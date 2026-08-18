# test/ 夹具与官方 sqllogictest 套件的对应关系

> vendor 固定 commit:sqlite.org/sqllogictest trunk
> `db57eba95d7c412bb413da5480c8be24`(见 `vendor/sqllogictest/VENDOR.md`)。
>
> 本目录夹具按「需求口径:以 sqlite3 3.46.1 期望值重构的 test/ 夹具」构建,
> 避免验收口径漂移。所有期望值由 sqlite3 3.46.1 实际执行产出(statement
> error 模式按本引擎真实报错文本书写,运行器以 re.search 匹配)。
> 生成器:`tools/gen_fixtures.py`(`python3 tools/gen_fixtures.py` 可复现)。

## 逐文件清单(子需求 0 基线 + 子需求 1 + 子需求 2 验收)

### 子需求 0 基线(7 文件,100 条)

| 夹具文件 | 官方对应 | 内容 | 覆盖能力 |
|---|---|---|---|
| `select1.test` | `select1.test` 表结构与 30 行数据逐条对应(1 CREATE + 30 INSERT);7 条查询与官方逐字一致(官方哈希);10 条额外查询按最小内核重构 | t1(a..e INTEGER),30 行 | CREATE TABLE / INSERT / SELECT / WHERE / ORDER BY / LIMIT |
| `create.test` | 按 select1 的 CREATE TABLE 形态扩展 | 多种类型列(INTEGER/TEXT/REAL/NUMERIC/BLOB、VARCHAR(n)) | CREATE TABLE |
| `insert.test` | 按 select1 的 INSERT 形态扩展 | 整行/多行/列清单/部分列 | INSERT |
| `select.test` | select1 的列引用投影场景 | 常量(无 FROM)、单列/多列引用 | SELECT 常量与列引用 |
| `where.test` | select1 的 WHERE 场景 | 比较六种 + AND/OR/NOT | 简单 WHERE |
| `orderby.test` | select1 的 ORDER BY 1 场景 | 列名/序号、ASC/DESC | ORDER BY |
| `limit.test` | select1 中 LIMIT 场景(官方多在算术查询里,重构为纯列引用) | LIMIT 截断、与 WHERE/ORDER BY 组合 | LIMIT |

### 子需求 1 验收(18 文件,955 条)

全部使用官方 select1.test 的 t1 表结构(a,b,c,d,e INTEGER,30 行)或
按官方场景自建的小表;查询覆盖本子需求验收 [a2]~[a10] 的能力点。

| 夹具文件 | 官方对应 | 内容 | 覆盖能力(验收 id) |
|---|---|---|---|
| `types.test` | `types.test` 场景(存储类/亲和/typeof) | 无类型列与五类显式列;亲和转换;字面量(blob/指数/边界);跨存储类比较 | [a2] 类型亲和与存储类转换 |
| `cast.test` | `cast.test` 场景 | CAST 到 INTEGER/REAL/TEXT/BLOB/NUMERIC;前缀解析;int64 截断;CAST 亲和参与比较 | [a6] CAST |
| `expr1.test` | `expr1.test` 场景(算术) | + - * / % \|\|;优先级;一元;文本转数值;除零;int64 溢出;类型保持 | [a4] 算术与类型转换 |
| `expr2.test` | `expr2.test` 场景(比较) | 六种比较 + ==;IS/ISNOT/ISNULL/NOTNULL;列亲和比较;WHERE 组合 | [a4] 比较与类型排序规则 |
| `expr3.test` | `expr3.test` 场景(逻辑/混合) | AND/OR/NOT 三值;真值转换;无 FROM 常量投影 + WHERE;CASE | [a5] 逻辑与三值逻辑;[a9] CASE |
| `func1.test` | `func1.test` 场景 | abs/length/substr/coalesce/ifnull/nullif/typeof;参数个数错误 | [a7] 标量函数 |
| `func2.test` | `func2.test` 场景 | upper/lower/hex/quote/round/sign/unicode/char | [a7] 标量函数 |
| `func3.test` | `func3.test` 场景 | min/max 标量(多参)/replace/instr/trim/ltrim/rtrim;错误 | [a7] 标量函数 |
| `func4.test` | `func4.test` 场景 | printf/like/glob 函数形式 | [a7] 标量函数;[a8] LIKE/GLOB |
| `func5.test` | `func5.test` 场景 | 函数嵌套组合 | [a7] 标量函数 |
| `like.test` | `like.test` 场景 | LIKE 通配符/大小写/ESCAPE/BLOB 恒 false/NOT LIKE | [a8] LIKE |
| `in.test` | `in.test` 场景 | IN/NOT IN 列表;NULL 语义;亲和 | [a5] IN 的 NULL 语义;[a9] IN |
| `null.test` | `null.test` 场景 | NULL 在比较/算术/逻辑/IN/BETWEEN/CASE/IS 中的传播 | [a5] NULL 三值逻辑 |
| `collate1.test` | `collate1.test` 场景 | 列级 COLLATE(BINARY/NOCASE/RTRIM);比较;ORDER BY | [a10] collation |
| `collate2.test` | `collate2.test` 场景 | NOCASE 排序与比较;显式 COLLATE | [a10] collation |
| `collate3.test` | `collate3.test` 场景 | RTRIM 排序与比较 | [a10] collation |
| `collate4.test` | `collate4.test` 场景 | 表达式级 COLLATE;IN/BETWEEN/|| 与 COLLATE 组合 | [a10] collation |
| `collate5.test` | `collate5.test` 场景 | 混合 collation 多列排序 | [a10] collation |

### 子需求 2 验收(7 文件,157 条)

覆盖本子需求验收能力点:DML(INSERT 多行/缺省值/NULL、UPDATE 含表达式
赋值与 WHERE、DELETE 含 WHERE)与 SELECT 进阶(WHERE 谓词、ORDER BY 含
collation、LIMIT/OFFSET、DISTINCT)。

| 夹具文件 | 官方对应 | 内容 | 覆盖能力(验收 id) |
|---|---|---|---|
| `insert1.test` | `insert1-5.test` 场景重构 | 多行、列清单、省略列→NULL、DEFAULT VALUES、列级 DEFAULT(含亲和转换)、显式 NULL、INSERT 错误 | INSERT(多行、缺省值、NULL) |
| `update1.test` | `update1-3.test` 场景重构 | 无 WHERE 全表、WHERE 过滤、表达式赋值、多列赋值、交换赋值(基于原行)、无匹配、亲和转换、collation 参与 WHERE、UPDATE 错误 | UPDATE(含表达式赋值与 WHERE) |
| `delete1.test` | `delete1-4.test` 场景重构 | WHERE 过滤、无匹配、无 WHERE 全删、DELETE 错误 | DELETE(含 WHERE) |
| `select2.test` | `select2.test` t1 数据逐条对应(官方 30 行含 NULL) | WHERE 谓词(IS NULL/IS NOT NULL/比较/AND/OR)、ORDER BY + LIMIT/OFFSET(含逗号形式、LIMIT -1、LIMIT 0、OFFSET 表达式) | SELECT 进阶(WHERE/LIMIT/OFFSET) |
| `select3.test` | `select3.test` 场景重构 | DISTINCT 单列/多列/表达式;NULL 去重;int/float 视为相同;collation 参与 DISTINCT;DISTINCT+WHERE+LIMIT/OFFSET | SELECT 进阶(DISTINCT) |
| `select4.test` | `select4.test` 场景重构(a1..a5 多列表) | ORDER BY 多列/方向;LIMIT/OFFSET 组合(含逗号形式、表达式、LIMIT -1、LIMIT 0);文本 collation 排序(NOCASE/BINARY/DESC) | SELECT 进阶(ORDER BY collation + LIMIT/OFFSET) |
| `select5.test` | `select5.test` 官方全连接 → 重构为单表组合 | DISTINCT+WHERE+ORDER BY+LIMIT/OFFSET 组合;LIKE/BETWEEN 谓词;常量投影 + LIMIT/OFFSET/DISTINCT | SELECT 进阶组合 |

## 与官方文件的差异口径(重构说明)

- 官方 expr/func/like/in/collate 系列使用 select1 的 t1 表(1 CREATE + 30
  INSERT,逐字保留);查询用例按本模块支持范围挑选/改写(官方用例大量依赖
  子查询、聚合、连接等范围外特性)。
- 官方 like/in/collate 系列中的部分语句为多语句 statement 记录,本夹具
  按单语句记录书写;运行器对单语句记录逐条执行,语义等价。
- `statement error` 记录的模式按本引擎真实报错文本书写(如
  `wrong number of arguments`、`no such function`),不照抄官方文案;
  该类记录的功能是验证"该语句确实失败",模式匹配只做防呆。
- 官方 func 系列含聚合用例(count/sum/avg 等),聚合属后续子需求范围,
  本夹具不构造聚合查询;min/max 仅使用标量多参形式。
- 官方 select5.test 全部为多表连接查询,连接属后续子需求范围;本夹具的
  `select5.test` 按官方 select5 的查询形态(组合 WHERE/ORDER BY/LIMIT/
  DISTINCT)重构为单表用例,期望值仍由 sqlite3 3.46.1 产出。
- 官方 insert/update/delete 系列存在 `UPDATE ... LIMIT`、`INSERT OR
  REPLACE` 等本子需求范围外形态(对应官方编译选项/约束特性),本夹具不
  构造;DML 错误记录(值数不匹配/未知列/未知表)模式按本引擎真实报错
  文本书写。

## 期望值产出方式

```bash
python3 tools/gen_fixtures.py
```

生成器对每条 query 记录在 sqlite3 3.46.1 中实际执行,按 sqllogictest
协议格式化期望值(R→%.3f、I→%d、T→文本,NULL→NULL、空串→(empty));
statement ok 记录同样在 sqlite3 中执行确认成功。环境自带
sqlite3 3.46.1(`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`)。

# vendor 记录:官方 sqllogictest 套件

## 来源与固定 commit

- 上游:SQLite 官方 sqllogictest(fossil 仓库)https://www.sqlite.org/sqllogictest
- 固定 checkin(trunk 顶):`db57eba95d7c412bb413da5480c8be24`
  - 提交信息:"Several minor doc typo fixes from BrickViking."
  - 作者:stephan;分支:trunk
  - 抓取时间:2026-08-18(本任务开始日)
- 抓取方式:因 fossil 仓库 zip 下载需登录,采用逐文件 HTTP 下载上游
  `doc/<checkin>/test/*.test` 原文,字节原样落盘,未做任何改写。

## 目录与文件

```
vendor/sqllogictest/
├── VENDOR.md        # 本文件
├── select1.test     # 官方 test/select1.test(257,999 字节)
├── select2.test     # 官方 test/select2.test(238,643 字节)
├── select3.test     # 官方 test/select3.test(855,728 字节)
├── select4.test     # 官方 test/select4.test(1,194,685 字节)
└── select5.test     # 官方 test/select5.test(702,577 字节)
```

MD5(与上游 doc/<checkin>/test/ 原文一致):

| 文件 | MD5 |
|---|---|
| select1.test | 5abb3919c4f0133828c5db53977e097f |
| select2.test | 073d3a395ad5e377096be3241c9c3af7 |
| select3.test | 8560cac98a5c6b6c92cac523bca8142b |
| select4.test | 23bf3102b0dd5f0559a42b0aeafa5f60 |
| select5.test | 02585a5fbd75c0ebc495221cc28e27c0 |

## 复现命令

```bash
# 需要能访问 sqlite.org(与上游 fossil 一致)
curl -sL -o vendor/sqllogictest/select1.test \
  "https://www.sqlite.org/sqllogictest/doc/db57eba95d7c412bb413da5480c8be24/test/select1.test"
# select2..select5 同理
```

## 本模块如何使用 vendor

`test/` 下的夹具按官方场景重构:表结构与数据行取自官方 select1.test
(1 条 CREATE TABLE + 30 条 INSERT,逐条对应),查询用例限制在最小内核范围
(常量/列引用/WHERE 比较/ORDER BY/LIMIT),期望值由 sqlite3 3.46.1 实际执行
产出;其中 7 条与官方 select1.test 完全相同的查询直接沿用官方哈希期望值。
对应关系见 `test/FIXTURES.md`。

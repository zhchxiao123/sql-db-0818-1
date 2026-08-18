"""递归下降解析器:把 Token 流变成 AST。

支持语句:
- CREATE TABLE name(col TYPE, ...)  — 基础形态,列定义 + 类型名
- INSERT INTO name [(col,...)] VALUES(expr,...)[,(expr,...)...]
- SELECT expr[,expr...] [FROM name] [WHERE expr] [ORDER BY col[ASC|DESC],...] [LIMIT n]

表达式(最小内核):
- 字面量(整数/浮点/字符串/blob/NULL)
- 列引用(标识符)
- 比较 = != <> < <= > >=
- 布尔组合 AND / OR / NOT,可用括号分组
- 一元 +/- (数值字面量符号)

范围外特性直接报解析错误:连接、子查询、聚合、函数、CASE、LIKE、IN、
BETWEEN、CAST、索引、视图、触发器、DISTINCT、UPDATE/DELETE。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ast
from .tokenizer import SqlLexError, Token, tokenize

# 比较运算符(二元,优先级低于 AND/OR 之上的算术——本子集无算术)
_CMP_OPS = {"=", "!=", "<>", "<", "<=", ">", ">="}
_AND_OR = {"AND", "OR"}

# 子句关键字:在表达式位置出现即为语法错误(SQLite 保留字语义)
_CLAUSE_KEYWORDS = {
    "FROM",
    "WHERE",
    "ORDER",
    "LIMIT",
    "GROUP",
    "HAVING",
    "VALUES",
    "INTO",
    "TABLE",
    "CREATE",
    "INSERT",
    "SELECT",
    "BY",
    "ASC",
    "DESC",
}


class SqlParseError(Exception):
    """解析错误:SQL 语法不合法。"""


class _Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ token 工具
    def peek(self) -> Optional[Token]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("SQL 意外结束")
        self.pos += 1
        return tok

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def is_kw(self, kw: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "ident" and tok.text == kw

    def is_sym(self, sym: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "symbol" and tok.text == sym

    def accept_kw(self, kw: str) -> bool:
        if self.is_kw(kw):
            self.pos += 1
            return True
        return False

    def accept_sym(self, sym: str) -> bool:
        if self.is_sym(sym):
            self.pos += 1
            return True
        return False

    def expect_kw(self, kw: str) -> None:
        if not self.accept_kw(kw):
            tok = self.peek()
            got = tok.text if tok else "文件结束"
            raise SqlParseError(f"期望关键字 {kw},得到 {got!r}")

    def expect_sym(self, sym: str) -> None:
        if not self.accept_sym(sym):
            tok = self.peek()
            got = tok.text if tok else "文件结束"
            raise SqlParseError(f"期望符号 {sym},得到 {got!r}")

    # ------------------------------------------------------------ 语句入口
    def parse_statement(self) -> ast.Statement:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("空语句")
        if tok.kind == "ident":
            kw = tok.text
            if kw == "CREATE":
                return self._parse_create()
            if kw == "INSERT":
                return self._parse_insert()
            if kw == "SELECT":
                return self._parse_select()
            raise SqlParseError(f"不支持的语句类型 {kw}")
        raise SqlParseError(f"语句必须以关键字开始,得到 {tok.text!r}")

    # ------------------------------------------------------------ CREATE TABLE
    def _parse_create(self) -> ast.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        table = self._expect_ident()
        self.expect_sym("(")
        columns: List[ast.ColumnDef] = []
        while True:
            name = self._expect_ident()
            type_name = self._parse_type_name()
            from .storage import affinity_of_type

            columns.append(
                ast.ColumnDef(name=name, type_name=type_name, affinity=affinity_of_type(type_name))
            )
            if self.accept_sym(","):
                continue
            break
        self.expect_sym(")")
        return ast.CreateTable(table=table, columns=columns)

    def _parse_type_name(self) -> str:
        """类型名:标识符 + 可选 (n[,m])。如 INTEGER、VARCHAR(10)、DECIMAL(10,2)。"""
        tok = self.peek()
        if tok is None or tok.kind != "ident":
            raise SqlParseError("期望列类型")
        self.pos += 1
        name = tok.text
        if self.is_sym("("):
            self.pos += 1
            depth = 1
            parts: List[str] = []
            while not self.at_end() and depth > 0:
                t = self.next()
                if t.kind == "symbol" and t.text == "(":
                    depth += 1
                elif t.kind == "symbol" and t.text == ")":
                    depth -= 1
                    if depth == 0:
                        break
                parts.append(t.text)
            if depth != 0:
                raise SqlParseError(f"类型 {name} 的括号未闭合")
            return f"{name}({','.join(parts)})"
        return name

    # ------------------------------------------------------------ INSERT
    def _parse_insert(self) -> ast.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self._expect_ident()
        columns: Optional[List[str]] = None
        if self.is_sym("("):
            self.pos += 1
            columns = []
            while True:
                columns.append(self._expect_ident())
                if self.accept_sym(","):
                    continue
                break
            self.expect_sym(")")
        self.expect_kw("VALUES")
        rows: List[List[ast.Expr]] = []
        while True:
            self.expect_sym("(")
            row: List[ast.Expr] = []
            while True:
                row.append(self._parse_expr())
                if self.accept_sym(","):
                    continue
                break
            self.expect_sym(")")
            rows.append(row)
            if self.accept_sym(","):
                continue
            break
        return ast.Insert(table=table, columns=columns, rows=rows)

    # ------------------------------------------------------------ SELECT
    def _parse_select(self) -> ast.Select:
        self.expect_kw("SELECT")
        projections: List[ast.Expr] = []
        while True:
            projections.append(self._parse_expr())
            if self.accept_sym(","):
                continue
            break
        table: Optional[str] = None
        if self.accept_kw("FROM"):
            table = self._expect_ident()
        where: Optional[ast.Expr] = None
        if self.accept_kw("WHERE"):
            where = self._parse_expr()
        order_by: List[ast.OrderItem] = []
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                order_by.append(self._parse_order_item())
                if self.accept_sym(","):
                    continue
                break
        limit: Optional[int] = None
        if self.accept_kw("LIMIT"):
            tok = self.next()
            if tok.kind != "number" or not isinstance(tok.value, int):
                raise SqlParseError("LIMIT 需要整数")
            limit = tok.value
        return ast.Select(
            projections=projections,
            table=table,
            where=where,
            order_by=order_by,
            limit=limit,
        )

    def _parse_order_item(self) -> ast.OrderItem:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("ORDER BY 缺少表达式")
        if tok.kind == "number" and isinstance(tok.value, int):
            self.pos += 1
            expr: ast.Expr = ast.Literal(tok.value)  # 序号按字面量存,执行期解释
        else:
            expr = self._parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        return ast.OrderItem(expr=expr, desc=desc)

    # ------------------------------------------------------------ 表达式
    # 优先级(低→高):OR → AND → NOT → 比较 → 一元 → 原子
    def _parse_expr(self) -> ast.Expr:
        return self._parse_or()

    def _parse_or(self) -> ast.Expr:
        left = self._parse_and()
        while self.is_kw("OR"):
            self.pos += 1
            right = self._parse_and()
            left = ast.BinaryOp("OR", left, right)
        return left

    def _parse_and(self) -> ast.Expr:
        left = self._parse_not()
        while self.is_kw("AND"):
            self.pos += 1
            right = self._parse_not()
            left = ast.BinaryOp("AND", left, right)
        return left

    def _parse_not(self) -> ast.Expr:
        if self.is_kw("NOT"):
            self.pos += 1
            operand = self._parse_not()
            return ast.UnaryOp("NOT", operand)
        return self._parse_cmp()

    def _parse_cmp(self) -> ast.Expr:
        left = self._parse_unary()
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "symbol" and tok.text in _CMP_OPS:
                self.pos += 1
                right = self._parse_unary()
                left = ast.BinaryOp(tok.text, left, right)
                continue
            break
        return left

    def _parse_unary(self) -> ast.Expr:
        tok = self.peek()
        if tok is not None and tok.kind == "symbol" and tok.text in ("-", "+"):
            self.pos += 1
            operand = self._parse_unary()
            return ast.UnaryOp(tok.text, operand)
        return self._parse_atom()

    def _parse_atom(self) -> ast.Expr:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("表达式意外结束")
        if tok.kind == "number":
            self.pos += 1
            return ast.Literal(tok.value)
        if tok.kind == "string":
            self.pos += 1
            return ast.Literal(tok.value)
        if tok.kind == "blob":
            self.pos += 1
            return ast.Literal(tok.value)
        if tok.kind == "ident":
            if tok.text == "NULL":
                self.pos += 1
                return ast.Literal(None)
            if tok.text == "TRUE":
                self.pos += 1
                return ast.Literal(1)
            if tok.text == "FALSE":
                self.pos += 1
                return ast.Literal(0)
            # 子句关键字不能作为裸表达式(SQLite 保留字语义)
            if tok.text in _CLAUSE_KEYWORDS:
                raise SqlParseError(f"意外的关键字 {tok.text}")
            # 列引用(本子集不支持函数/子查询/表限定)
            self.pos += 1
            return ast.ColumnRef(tok.text)
        if tok.kind == "symbol" and tok.text == "(":
            self.pos += 1
            expr = self._parse_expr()
            self.expect_sym(")")
            return expr
        raise SqlParseError(f"无法识别的表达式起始 {tok.text!r}")

    # ------------------------------------------------------------ 标识符
    def _expect_ident(self) -> str:
        tok = self.next()
        if tok.kind != "ident":
            raise SqlParseError(f"期望标识符,得到 {tok.text!r}")
        return tok.text


def parse(sql: str) -> ast.Statement:
    """解析一条 SQL 语句。

    Args:
        sql: SQL 语句文本。

    Returns:
        对应 AST。

    Raises:
        SqlLexError: 词法错误。
        SqlParseError: 语法错误。
    """
    tokens = tokenize(sql)
    # 去掉末尾分号
    while tokens and tokens[-1].kind == "symbol" and tokens[-1].text == ";":
        tokens = tokens[:-1]
    if not tokens:
        raise SqlParseError("空语句")
    parser = _Parser(tokens)
    stmt = parser.parse_statement()
    if not parser.at_end():
        tok = parser.peek()
        raise SqlParseError(f"语句结束后还有内容 {tok.text!r}")
    return stmt

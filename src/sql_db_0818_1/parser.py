"""递归下降解析器:把 Token 流变成 AST。

支持语句:
- CREATE TABLE name(col TYPE [COLLATE name], ...) — 列定义 + 类型名 + 列级排序规则
- INSERT INTO name [(col,...)] VALUES(expr,...)[,(expr,...)...]
- SELECT expr[,expr...] [FROM name] [WHERE expr] [ORDER BY expr [COLLATE c] [ASC|DESC],...] [LIMIT n]

表达式(子需求 1):
- 字面量(整数/浮点/字符串/blob/NULL/TRUE/FALSE)
- 列引用(标识符)
- 算术:+ - * / % ||(优先级:|| > * / % > + -)
- 比较:= == != <> < <= > >=、IS [NOT]、ISNULL/NOTNULL
- LIKE/GLOB([NOT], 可选 ESCAPE)、IN([NOT], 列表)、BETWEEN([NOT])
- 布尔组合 AND / OR / NOT,可用括号分组
- CAST(expr AS type)、标量函数调用 name(args)、CASE [base] WHEN..THEN..ELSE..END
- COLLATE 后缀(绑定强于 ||,弱于一元)

范围外特性直接报解析错误:连接、子查询、聚合、索引、视图、触发器、DISTINCT、
UPDATE/DELETE。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ast
from .tokenizer import SqlLexError, Token, tokenize
from .storage import affinity_of_type

# 比较/集合运算符(二元,优先级低于算术之上)
_CMP_OPS = {"=", "==", "!=", "<>", "<", "<=", ">", ">="}
_AND_OR = {"AND", "OR"}
_ARITH_HIGH = {"*", "/", "%"}  # 高于 + -
_CONCAT = {"||"}

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
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "AS",
    "AND",
    "OR",
    "NOT",
    "IS",
    "IN",
    "LIKE",
    "GLOB",
    "BETWEEN",
    "ESCAPE",
    "ISNULL",
    "NOTNULL",
    "COLLATE",
    "UNION",
    "JOIN",
    "ON",
    "USING",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "CROSS",
    "DISTINCT",
    "ALL",
    "EXISTS",
    "CASE",
    "CAST",
    "PRIMARY",
    "KEY",
    "UNIQUE",
    "CHECK",
    "DEFAULT",
    "REFERENCES",
    "CONSTRAINT",
    "FOREIGN",
}

# 聚合/窗口函数等本子集不支持
_AGGREGATES = {"COUNT", "SUM", "AVG", "TOTAL", "GROUP_CONCAT"}


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
            raise SqlParseError("syntax error at end of input")
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
            got = tok.text if tok else "end of input"
            raise SqlParseError(f'near "{got}": syntax error (expected {kw})')

    def expect_sym(self, sym: str) -> None:
        if not self.accept_sym(sym):
            tok = self.peek()
            got = tok.text if tok else "end of input"
            raise SqlParseError(f'near "{got}": syntax error (expected {sym})')

    def _syntax(self) -> SqlParseError:
        tok = self.peek()
        got = tok.text if tok else "end of input"
        return SqlParseError(f'near "{got}": syntax error')

    # ------------------------------------------------------------ 语句入口
    def parse_statement(self) -> ast.Statement:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("empty statement")
        if tok.kind == "ident":
            kw = tok.text
            if kw == "CREATE":
                return self._parse_create()
            if kw == "INSERT":
                return self._parse_insert()
            if kw == "SELECT":
                return self._parse_select()
            raise SqlParseError(f'near "{kw}": syntax error')
        raise SqlParseError(f'near "{tok.text}": syntax error')

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
            collation = "BINARY"
            if self.accept_kw("COLLATE"):
                collation = self._expect_ident()
            columns.append(
                ast.ColumnDef(
                    name=name,
                    type_name=type_name,
                    affinity=affinity_of_type(type_name),
                    collation=collation,
                )
            )
            if self.accept_sym(","):
                continue
            break
        self.expect_sym(")")
        return ast.CreateTable(table=table, columns=columns)

    def _parse_type_name(self) -> str:
        """类型名:标识符 + 可选 (n[,m])。如 INTEGER、VARCHAR(10)、DECIMAL(10,2)。

        允许缺省类型(SQLite:`a, b, c` 无类型列 → BLOB 亲和)。
        """
        tok = self.peek()
        if tok is None or tok.kind != "ident":
            return ""  # 无类型列
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
                raise SqlParseError(f"unclosed parenthesis in type {name}")
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
            if self.is_sym("*"):
                self.pos += 1
                projections.append(ast.Literal("*"))  # SELECT * 展开标志
            else:
                proj = self._parse_expr()
                # 投影别名:expr [AS] alias —— 解析但丢弃(本子集不用列名)
                if self.accept_kw("AS"):
                    self._expect_ident()
                elif self._is_projection_alias():
                    self.pos += 1
                projections.append(proj)
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
                raise SqlParseError("LIMIT requires an integer")
            limit = tok.value
        return ast.Select(
            projections=projections,
            table=table,
            where=where,
            order_by=order_by,
            limit=limit,
        )

    def _is_projection_alias(self) -> bool:
        """投影别名(省略 AS):下一个 token 是标识符且不是子句关键字/排序方向。"""
        tok = self.peek()
        if tok is None or tok.kind != "ident":
            return False
        return tok.text not in _CLAUSE_KEYWORDS and tok.text not in ("ASC", "DESC")

    def _parse_order_item(self) -> ast.OrderItem:
        tok = self.peek()
        if tok is None:
            raise SqlParseError("ORDER BY requires an expression")
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
    # 优先级(低→高):OR → AND → NOT → 比较/IN/LIKE/GLOB/BETWEEN/IS →
    #               + - (二元) → * / % → || → COLLATE → 一元 - + → 原子
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
        left = self._parse_additive()
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "symbol" and tok.text in _CMP_OPS:
                self.pos += 1
                right = self._parse_additive()
                op = "=" if tok.text == "==" else tok.text
                left = ast.BinaryOp(op, left, right)
                continue
            if tok is not None and tok.kind == "ident":
                kw = tok.text
                if kw == "IS":
                    self.pos += 1
                    neg = self.accept_kw("NOT")
                    right = self._parse_additive()
                    left = ast.BinaryOp("IS NOT" if neg else "IS", left, right)
                    continue
                if kw == "ISNULL":
                    self.pos += 1
                    left = ast.BinaryOp("IS", left, ast.Literal(None))
                    continue
                if kw == "NOTNULL":
                    self.pos += 1
                    left = ast.BinaryOp("IS NOT", left, ast.Literal(None))
                    continue
                if kw == "NOT":
                    # NOT IN / NOT LIKE / NOT GLOB / NOT BETWEEN
                    save = self.pos
                    self.pos += 1
                    nxt = self.peek()
                    if nxt is not None and nxt.kind == "ident":
                        if nxt.text == "IN":
                            self.pos += 1
                            items = self._parse_in_list()
                            left = ast.InList(left, items, negated=True)
                            continue
                        if nxt.text == "LIKE":
                            self.pos += 1
                            pattern, escape = self._parse_like_rhs()
                            left = ast.Like(left, pattern, escape, negated=True)
                            continue
                        if nxt.text == "GLOB":
                            self.pos += 1
                            pattern = self._parse_additive()
                            left = ast.Glob(left, pattern, negated=True)
                            continue
                        if nxt.text == "BETWEEN":
                            self.pos += 1
                            low, high = self._parse_between_rhs()
                            left = ast.Between(left, low, high, negated=True)
                            continue
                    self.pos = save  # 不是集合运算符的 NOT,回退
                    break
                if kw == "IN":
                    self.pos += 1
                    items = self._parse_in_list()
                    left = ast.InList(left, items)
                    continue
                if kw == "LIKE":
                    self.pos += 1
                    pattern, escape = self._parse_like_rhs()
                    left = ast.Like(left, pattern, escape)
                    continue
                if kw == "GLOB":
                    self.pos += 1
                    pattern = self._parse_additive()
                    left = ast.Glob(left, pattern)
                    continue
                if kw == "BETWEEN":
                    self.pos += 1
                    low, high = self._parse_between_rhs()
                    left = ast.Between(left, low, high)
                    continue
            break
        # 比较级后缀 COLLATE:expr IN (...) COLLATE NOCASE 等(SQLite 允许,
        # COLLATE 作用于整个比较表达式)
        while self.is_kw("COLLATE"):
            self.pos += 1
            name = self._expect_ident()
            left = ast.Collate(left, name)
        return left

    def _parse_like_rhs(self) -> Tuple[ast.Expr, Optional[ast.Expr]]:
        pattern = self._parse_additive()
        escape: Optional[ast.Expr] = None
        if self.accept_kw("ESCAPE"):
            escape = self._parse_additive()
        return pattern, escape

    def _parse_between_rhs(self) -> Tuple[ast.Expr, ast.Expr]:
        low = self._parse_additive()
        self.expect_kw("AND")
        high = self._parse_additive()
        return low, high

    def _parse_in_list(self) -> List[ast.Expr]:
        self.expect_sym("(")
        items: List[ast.Expr] = []
        if self.is_sym(")"):
            self.pos += 1
            return items
        if self.is_kw("SELECT"):
            raise SqlParseError("subquery in IN is not supported")
        while True:
            items.append(self._parse_expr())
            if self.accept_sym(","):
                continue
            break
        self.expect_sym(")")
        return items

    def _parse_additive(self) -> ast.Expr:
        left = self._parse_multiplicative()
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "symbol" and tok.text in ("+", "-"):
                self.pos += 1
                right = self._parse_multiplicative()
                left = ast.BinaryOp(tok.text, left, right)
                continue
            break
        return left

    def _parse_multiplicative(self) -> ast.Expr:
        left = self._parse_concat()
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "symbol" and tok.text in _ARITH_HIGH:
                self.pos += 1
                right = self._parse_concat()
                left = ast.BinaryOp(tok.text, left, right)
                continue
            break
        return left

    def _parse_concat(self) -> ast.Expr:
        left = self._parse_collate()
        while self.is_sym("||"):
            self.pos += 1
            right = self._parse_collate()
            left = ast.BinaryOp("||", left, right)
        return left

    def _parse_collate(self) -> ast.Expr:
        expr = self._parse_unary()
        while self.is_kw("COLLATE"):
            self.pos += 1
            name = self._expect_ident()
            expr = ast.Collate(expr, name)
        return expr

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
            raise SqlParseError("unexpected end of expression")
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
            if tok.text == "CAST":
                self.pos += 1
                return self._parse_cast()
            if tok.text == "CASE":
                self.pos += 1
                return self._parse_case()
            # 函数调用:标识符紧跟 (
            if self._is_next_sym("("):
                self.pos += 1
                return self._parse_func_call(tok.text)
            # 子句关键字不能作为裸表达式(SQLite 保留字语义)
            if tok.text in _CLAUSE_KEYWORDS:
                raise SqlParseError(f'near "{tok.text}": syntax error')
            # 列引用
            self.pos += 1
            return ast.ColumnRef(tok.text)
        if tok.kind == "symbol" and tok.text == "(":
            self.pos += 1
            expr = self._parse_expr()
            self.expect_sym(")")
            return expr
        raise SqlParseError(f'near "{tok.text}": syntax error')

    def _is_next_sym(self, sym: str) -> bool:
        if self.pos + 1 < len(self.tokens):
            return self.tokens[self.pos + 1].kind == "symbol" and self.tokens[self.pos + 1].text == sym
        return False

    def _parse_func_call(self, name: str) -> ast.Expr:
        if name in _AGGREGATES:
            raise SqlParseError(f"aggregate function {name} is not supported")
        self.expect_sym("(")
        args: List[ast.Expr] = []
        if not self.is_sym(")"):
            while True:
                if self.is_sym("*"):
                    raise SqlParseError(f"* argument to {name} is not supported")
                args.append(self._parse_expr())
                if self.accept_sym(","):
                    continue
                break
        self.expect_sym(")")
        return ast.FuncCall(name=name, args=args)

    def _parse_cast(self) -> ast.Expr:
        self.expect_sym("(")
        expr = self._parse_expr()
        self.expect_kw("AS")
        # 类型名:一个或多个标识符,可选 (n[,m])
        parts: List[str] = []
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "ident" or tok.text in _CLAUSE_KEYWORDS:
                break
            parts.append(tok.text)
            self.pos += 1
            if self.is_sym("("):
                self.pos += 1
                depth = 1
                sub: List[str] = []
                while not self.at_end() and depth > 0:
                    t = self.next()
                    if t.kind == "symbol" and t.text == "(":
                        depth += 1
                    elif t.kind == "symbol" and t.text == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    sub.append(t.text)
                parts.append(f"({','.join(sub)})")
        if not parts:
            raise SqlParseError("CAST requires a type name")
        type_name = " ".join(parts)
        self.expect_sym(")")
        return ast.Cast(expr=expr, type_name=type_name, affinity=affinity_of_type(type_name))

    def _parse_case(self) -> ast.Expr:
        base: Optional[ast.Expr] = None
        if not self.is_kw("WHEN"):
            base = self._parse_expr()
        whens: List[Tuple[ast.Expr, ast.Expr]] = []
        while self.is_kw("WHEN"):
            self.pos += 1
            cond = self._parse_expr()
            self.expect_kw("THEN")
            result = self._parse_expr()
            whens.append((cond, result))
        if not whens:
            raise SqlParseError("CASE requires at least one WHEN")
        else_expr: Optional[ast.Expr] = None
        if self.accept_kw("ELSE"):
            else_expr = self._parse_expr()
        self.expect_kw("END")
        return ast.Case(base=base, whens=whens, else_expr=else_expr)

    # ------------------------------------------------------------ 标识符
    def _expect_ident(self) -> str:
        tok = self.next()
        if tok.kind != "ident":
            raise SqlParseError(f'near "{tok.text}": syntax error (expected identifier)')
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
        raise SqlParseError("empty statement")
    parser = _Parser(tokens)
    stmt = parser.parse_statement()
    if not parser.at_end():
        tok = parser.peek()
        raise SqlParseError(f'near "{tok.text}": syntax error')
    return stmt

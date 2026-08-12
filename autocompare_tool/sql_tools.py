from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope


Logger = Callable[[str], None]
SUPPORTED_DIALECTS = {
    "": "Tự động / SQL phổ thông",
    "tsql": "SQL Server (T-SQL)",
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "oracle": "Oracle",
    "sqlite": "SQLite",
    "bigquery": "BigQuery",
    "snowflake": "Snowflake",
    "spark": "Spark SQL",
    "databricks": "Databricks",
    "duckdb": "DuckDB",
}
DIALECT_ALIASES = {
    "auto": "",
    "generic": "",
    "sqlserver": "tsql",
    "sql server": "tsql",
    "postgresql": "postgres",
}


@dataclass(frozen=True)
class SqlFormatResult:
    formatted_sql: str
    statement_count: int
    dialect: str


@dataclass(frozen=True)
class SqlStatementInfo:
    index: int
    statement_type: str
    scope_count: int
    sql: str


@dataclass(frozen=True)
class SqlTableReference:
    statement_index: int
    scope_id: str
    scope_name: str
    depth: int
    qualified_name: str
    catalog: str
    schema: str
    name: str
    alias: str
    role: str
    source_type: str


@dataclass(frozen=True)
class SqlConditionInfo:
    statement_index: int
    scope_id: str
    scope_name: str
    depth: int
    clause: str
    expression: str
    referenced_aliases: list[str]
    referenced_columns: list[str]


@dataclass(frozen=True)
class SqlCteInfo:
    statement_index: int
    scope_id: str
    name: str
    columns: list[str]
    recursive: bool
    sql: str


@dataclass(frozen=True)
class SqlSubqueryInfo:
    statement_index: int
    scope_id: str
    scope_name: str
    depth: int
    subquery_type: str
    alias: str
    context: str
    sql: str


@dataclass(frozen=True)
class SqlProjectionInfo:
    statement_index: int
    scope_id: str
    scope_name: str
    depth: int
    position: int
    alias: str
    expression: str
    referenced_columns: list[str]


@dataclass(frozen=True)
class SqlClauseInfo:
    statement_index: int
    scope_id: str
    scope_name: str
    clause: str
    expression: str


@dataclass
class SqlAnalysisResult:
    formatted_sql: str
    statement_count: int
    dialect: str
    statements: list[SqlStatementInfo] = field(default_factory=list)
    tables: list[SqlTableReference] = field(default_factory=list)
    conditions: list[SqlConditionInfo] = field(default_factory=list)
    ctes: list[SqlCteInfo] = field(default_factory=list)
    subqueries: list[SqlSubqueryInfo] = field(default_factory=list)
    projections: list[SqlProjectionInfo] = field(default_factory=list)
    clauses: list[SqlClauseInfo] = field(default_factory=list)


@dataclass(frozen=True)
class _ScopeInfo:
    scope: Scope | None
    expression: exp.Expression
    scope_id: str
    name: str
    kind: str
    depth: int


def format_sql(sql_text: str, dialect: str = "", log: Logger | None = None) -> SqlFormatResult:
    logger = log or (lambda _message: None)
    normalized_dialect = _normalize_dialect(dialect)
    expressions = _parse_sql(sql_text, normalized_dialect)
    formatted = _format_expressions(expressions, normalized_dialect)
    logger(f"Đã format {len(expressions)} câu lệnh SQL.")
    return SqlFormatResult(
        formatted_sql=formatted,
        statement_count=len(expressions),
        dialect=normalized_dialect or "auto",
    )


def analyze_sql(sql_text: str, dialect: str = "", log: Logger | None = None) -> SqlAnalysisResult:
    logger = log or (lambda _message: None)
    normalized_dialect = _normalize_dialect(dialect)
    expressions = _parse_sql(sql_text, normalized_dialect)
    result = SqlAnalysisResult(
        formatted_sql=_format_expressions(expressions, normalized_dialect),
        statement_count=len(expressions),
        dialect=normalized_dialect or "auto",
    )

    for statement_index, expression in enumerate(expressions, start=1):
        _analyze_statement(result, expression, statement_index, normalized_dialect)

    logger(
        f"Đã phân tích {result.statement_count} câu lệnh: "
        f"{len(result.tables)} table/reference, {len(result.conditions)} điều kiện, "
        f"{len(result.ctes)} CTE và {len(result.subqueries)} subquery."
    )
    return result


def parse_sql_expressions(sql_text: str, dialect: str = "") -> list[exp.Expression]:
    return _parse_sql(sql_text, _normalize_dialect(dialect))


def normalize_sql_dialect(dialect: str) -> str:
    return _normalize_dialect(dialect)


def render_sql_expression(expression: exp.Expression, dialect: str = "", pretty: bool = False) -> str:
    normalized = _normalize_dialect(dialect)
    return _sql(expression, normalized, pretty=pretty)


def _parse_sql(sql_text: str, dialect: str) -> list[exp.Expression]:
    value = str(sql_text).strip()
    if not value:
        raise ValueError("Vui lòng nhập câu SQL cần xử lý.")
    try:
        parsed = sqlglot.parse(
            value,
            read=dialect or None,
            error_level=ErrorLevel.RAISE,
        )
    except ParseError as exc:
        if exc.errors:
            first = exc.errors[0]
            description = first.get("description", "Lỗi cú pháp")
            line = first.get("line", "?")
            column = first.get("col", "?")
            highlight = first.get("highlight", "")
            near = f" gần “{highlight}”" if highlight else ""
            raise ValueError(
                f"SQL không hợp lệ tại dòng {line}, cột {column}{near}: {description}."
            ) from exc
        raise ValueError(f"SQL không hợp lệ: {exc}") from exc

    expressions = [expression for expression in parsed if expression is not None]
    if not expressions:
        raise ValueError("Không tìm thấy câu lệnh SQL hợp lệ để xử lý.")
    return expressions


def _normalize_dialect(dialect: str) -> str:
    normalized = str(dialect or "").strip().lower()
    normalized = DIALECT_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_DIALECTS:
        raise ValueError(f"SQL dialect không được hỗ trợ: {dialect}.")
    return normalized


def _format_expressions(expressions: list[exp.Expression], dialect: str) -> str:
    return ";\n\n".join(_sql(expression, dialect, pretty=True) for expression in expressions)


def _analyze_statement(
    result: SqlAnalysisResult,
    expression: exp.Expression,
    statement_index: int,
    dialect: str,
) -> None:
    walk_order = {id(node): index for index, node in enumerate(expression.walk())}
    scopes = list(traverse_scope(expression))
    scope_infos = _build_scope_infos(expression, scopes, statement_index, walk_order)
    root_scope = min(scope_infos, key=lambda item: item.depth)

    result.statements.append(
        SqlStatementInfo(
            index=statement_index,
            statement_type=expression.key.upper(),
            scope_count=len(scope_infos),
            sql=_sql(expression, dialect, pretty=True),
        )
    )

    for table in expression.find_all(exp.Table):
        scope_info = _scope_for_node(table, scope_infos) or root_scope
        result.tables.append(_table_info(table, scope_info, statement_index, dialect))

    _collect_conditions(result, expression, statement_index, dialect, scope_infos, walk_order)
    _collect_ctes(result, expression, statement_index, dialect, scope_infos)
    _collect_subqueries(result, statement_index, dialect, scope_infos)
    _collect_projections(result, expression, statement_index, dialect, scope_infos)
    _collect_clauses(result, expression, statement_index, dialect, scope_infos, walk_order)


def _build_scope_infos(
    expression: exp.Expression,
    scopes: list[Scope],
    statement_index: int,
    walk_order: dict[int, int],
) -> list[_ScopeInfo]:
    if not scopes:
        return [
            _ScopeInfo(
                scope=None,
                expression=expression,
                scope_id=f"S{statement_index}.Q1",
                name="Main statement",
                kind="ROOT",
                depth=0,
            )
        ]

    ordered = sorted(scopes, key=lambda scope: walk_order.get(id(scope.expression), 0))
    result: list[_ScopeInfo] = []
    for index, scope in enumerate(ordered, start=1):
        kind = scope.scope_type.name
        parent = scope.expression.parent
        if isinstance(parent, exp.CTE):
            name = f"CTE {parent.alias_or_name}"
        elif isinstance(parent, exp.Subquery) and parent.alias_or_name:
            name = f"Subquery {parent.alias_or_name}"
        elif isinstance(parent, exp.Exists):
            name = "EXISTS subquery"
        elif scope.parent is None:
            name = "Main query"
        else:
            name = f"{kind.title()} query"
        result.append(
            _ScopeInfo(
                scope=scope,
                expression=scope.expression,
                scope_id=f"S{statement_index}.Q{index}",
                name=name,
                kind=kind,
                depth=_scope_depth(scope),
            )
        )
    return result


def _scope_depth(scope: Scope) -> int:
    depth = 0
    parent = scope.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def _scope_for_node(node: exp.Expression, scope_infos: list[_ScopeInfo]) -> _ScopeInfo | None:
    ancestors: set[int] = set()
    current: exp.Expression | None = node
    while current is not None:
        ancestors.add(id(current))
        current = current.parent
    candidates = [item for item in scope_infos if id(item.expression) in ancestors]
    return max(candidates, key=lambda item: item.depth, default=None)


def _table_info(
    table: exp.Table,
    scope_info: _ScopeInfo,
    statement_index: int,
    dialect: str,
) -> SqlTableReference:
    alias = table.alias or ""
    source_type = "TABLE"
    if scope_info.scope is not None:
        source = scope_info.scope.sources.get(alias or table.name)
        if isinstance(source, Scope):
            source_type = "CTE_REFERENCE" if source.scope_type.name == "CTE" else "QUERY_REFERENCE"
    parts = [_sql(part, dialect) for part in table.parts]
    qualified_name = ".".join(parts) or _sql(table.this, dialect)
    return SqlTableReference(
        statement_index=statement_index,
        scope_id=scope_info.scope_id,
        scope_name=scope_info.name,
        depth=scope_info.depth,
        qualified_name=qualified_name,
        catalog=table.catalog or "",
        schema=table.db or "",
        name=table.name or qualified_name,
        alias=alias,
        role=_table_role(table),
        source_type=source_type,
    )


def _table_role(table: exp.Table) -> str:
    parent = table.parent
    if isinstance(parent, exp.Join):
        return _join_label(parent)
    if isinstance(parent, exp.From):
        return "FROM"

    current: exp.Expression | None = parent
    target_types: tuple[tuple[type[exp.Expression], str], ...] = (
        (exp.Insert, "INSERT TARGET"),
        (exp.Update, "UPDATE TARGET"),
        (exp.Delete, "DELETE TARGET"),
        (exp.Merge, "MERGE TARGET"),
        (exp.Create, "CREATE TARGET"),
    )
    while current is not None:
        for expression_type, label in target_types:
            if isinstance(current, expression_type) and _contains_identity(current.args.get("this"), table):
                return label
        if isinstance(current, exp.Join):
            return _join_label(current)
        if isinstance(current, exp.From):
            return "FROM"
        current = current.parent
    return type(parent).__name__.upper() if parent is not None else "REFERENCE"


def _contains_identity(root: Any, target: exp.Expression) -> bool:
    if not isinstance(root, exp.Expression):
        return False
    return any(node is target for node in root.walk())


def _join_label(join: exp.Join) -> str:
    parts = [join.args.get("method"), join.args.get("side"), join.args.get("kind"), "JOIN"]
    return " ".join(str(part).upper() for part in parts if part)


def _collect_conditions(
    result: SqlAnalysisResult,
    expression: exp.Expression,
    statement_index: int,
    dialect: str,
    scope_infos: list[_ScopeInfo],
    walk_order: dict[int, int],
) -> None:
    collected: list[tuple[int, int, SqlConditionInfo]] = []

    def add(origin: exp.Expression, clause: str, condition: exp.Expression) -> None:
        scope = _scope_for_node(origin, scope_infos) or scope_infos[0]
        for part_index, part in enumerate(_split_and(condition)):
            columns = _unique(_sql(column, dialect) for column in part.find_all(exp.Column))
            aliases = _unique(column.table for column in part.find_all(exp.Column) if column.table)
            collected.append(
                (
                    walk_order.get(id(origin), len(walk_order)),
                    part_index,
                    SqlConditionInfo(
                        statement_index=statement_index,
                        scope_id=scope.scope_id,
                        scope_name=scope.name,
                        depth=scope.depth,
                        clause=clause,
                        expression=_sql(part, dialect),
                        referenced_aliases=aliases,
                        referenced_columns=columns,
                    ),
                )
            )

    for where in expression.find_all(exp.Where):
        add(where, "WHERE", where.this)
    for having in expression.find_all(exp.Having):
        add(having, "HAVING", having.this)
    for qualify in expression.find_all(exp.Qualify):
        add(qualify, "QUALIFY", qualify.this)
    for join in expression.find_all(exp.Join):
        if join.args.get("on") is not None:
            add(join, f"{_join_label(join)} ON", join.args["on"])
        elif join.args.get("using"):
            using_sql = ", ".join(_sql(item, dialect) for item in join.args["using"])
            using_expression = exp.Var(this=f"({using_sql})")
            add(join, f"{_join_label(join)} USING", using_expression)
    for merge in expression.find_all(exp.Merge):
        if merge.args.get("on") is not None:
            add(merge, "MERGE ON", merge.args["on"])
    for connect in expression.find_all(exp.Connect):
        if connect.args.get("start") is not None:
            add(connect, "START WITH", connect.args["start"])
        if connect.args.get("connect") is not None:
            add(connect, "CONNECT BY", connect.args["connect"])
    for conditional in expression.find_all(exp.If):
        if conditional.this is not None:
            add(conditional, "CASE/IF WHEN", conditional.this)

    collected.sort(key=lambda item: (item[0], item[1]))
    result.conditions.extend(item[2] for item in collected)


def _split_and(condition: exp.Expression) -> list[exp.Expression]:
    if isinstance(condition, exp.And):
        return [*_split_and(condition.this), *_split_and(condition.expression)]
    return [condition]


def _collect_ctes(
    result: SqlAnalysisResult,
    expression: exp.Expression,
    statement_index: int,
    dialect: str,
    scope_infos: list[_ScopeInfo],
) -> None:
    for cte in expression.find_all(exp.CTE):
        scope = _scope_for_node(cte.this, scope_infos) or scope_infos[0]
        with_expression = cte.parent if isinstance(cte.parent, exp.With) else None
        result.ctes.append(
            SqlCteInfo(
                statement_index=statement_index,
                scope_id=scope.scope_id,
                name=cte.alias_or_name,
                columns=list(cte.alias_column_names),
                recursive=bool(with_expression and with_expression.args.get("recursive")),
                sql=_sql(cte.this, dialect, pretty=True),
            )
        )


def _collect_subqueries(
    result: SqlAnalysisResult,
    statement_index: int,
    dialect: str,
    scope_infos: list[_ScopeInfo],
) -> None:
    for scope in scope_infos:
        if scope.kind in {"ROOT", "CTE"}:
            continue
        parent = scope.expression.parent
        alias = parent.alias_or_name if isinstance(parent, exp.Subquery) else ""
        if isinstance(parent, exp.Exists):
            subquery_type = "EXISTS"
        elif isinstance(parent, exp.Subquery) and isinstance(parent.parent, (exp.From, exp.Join)):
            subquery_type = "DERIVED TABLE"
        elif scope.kind == "UNION":
            subquery_type = "SET BRANCH"
        else:
            subquery_type = "SUBQUERY"
        result.subqueries.append(
            SqlSubqueryInfo(
                statement_index=statement_index,
                scope_id=scope.scope_id,
                scope_name=scope.name,
                depth=scope.depth,
                subquery_type=subquery_type,
                alias=alias,
                context=_query_context(scope.expression),
                sql=_sql(scope.expression, dialect, pretty=True),
            )
        )


def _query_context(query: exp.Expression) -> str:
    current = query.parent
    while current is not None:
        if isinstance(current, exp.CTE):
            return f"CTE {current.alias_or_name}"
        if isinstance(current, exp.Join):
            return _join_label(current)
        if isinstance(current, exp.From):
            return "FROM"
        if isinstance(current, exp.Where):
            return "WHERE"
        if isinstance(current, exp.Having):
            return "HAVING"
        if isinstance(current, exp.Qualify):
            return "QUALIFY"
        if isinstance(current, exp.Select):
            return "SELECT"
        current = current.parent
    return "STATEMENT"


def _collect_projections(
    result: SqlAnalysisResult,
    expression: exp.Expression,
    statement_index: int,
    dialect: str,
    scope_infos: list[_ScopeInfo],
) -> None:
    for select in expression.find_all(exp.Select):
        scope = _scope_for_node(select, scope_infos) or scope_infos[0]
        for position, projection in enumerate(select.expressions, start=1):
            result.projections.append(
                SqlProjectionInfo(
                    statement_index=statement_index,
                    scope_id=scope.scope_id,
                    scope_name=scope.name,
                    depth=scope.depth,
                    position=position,
                    alias=projection.alias or "",
                    expression=_sql(projection, dialect),
                    referenced_columns=_unique(
                        _sql(column, dialect) for column in projection.find_all(exp.Column)
                    ),
                )
            )


def _collect_clauses(
    result: SqlAnalysisResult,
    expression: exp.Expression,
    statement_index: int,
    dialect: str,
    scope_infos: list[_ScopeInfo],
    walk_order: dict[int, int],
) -> None:
    collected: list[tuple[int, SqlClauseInfo]] = []
    clause_types: tuple[tuple[type[exp.Expression], str], ...] = (
        (exp.Group, "GROUP BY"),
        (exp.Order, "ORDER BY"),
        (exp.Limit, "LIMIT / TOP / FETCH"),
        (exp.Offset, "OFFSET"),
    )
    for expression_type, label in clause_types:
        for clause in expression.find_all(expression_type):
            scope = _scope_for_node(clause, scope_infos) or scope_infos[0]
            collected.append(
                (
                    walk_order.get(id(clause), len(walk_order)),
                    SqlClauseInfo(
                        statement_index=statement_index,
                        scope_id=scope.scope_id,
                        scope_name=scope.name,
                        clause=label,
                        expression=_sql(clause, dialect),
                    ),
                )
            )
    collected.sort(key=lambda item: item[0])
    result.clauses.extend(item[1] for item in collected)


def _sql(expression: exp.Expression, dialect: str, pretty: bool = False) -> str:
    options: dict[str, Any] = {"pretty": pretty}
    if dialect:
        options["dialect"] = dialect
    return expression.sql(**options)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

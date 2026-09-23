"""Row participation through SQL scopes without changing their cardinality.

Each scope carries a boolean witness for one candidate source key. Unlike
projecting keys through DISTINCT/GROUP BY, this preserves intermediate rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.pushdown_projections import pushdown_projections
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.schema import MappingSchema

from .sql_recursive_lineage import mark_recursive_ctes, recursive_source, recursive_witnesses
from .sql_pivot_lineage import lower_pivots
from .sql_lineage_normalize import distinct_on_queries, explicit_joins

if TYPE_CHECKING:
    from .database_io import TableMetadata
    from .sql_tools import SqlTableReference


def _column(alias, name):
    return exp.column(name, table=alias, quoted=True)


def _value(expression):
    return expression.this if isinstance(expression, exp.Alias) else expression


def _flag(condition):
    return exp.Case().when(condition, exp.Literal.number(1)).else_(exp.Literal.number(0))


def _equal(left, right):
    return exp.or_(exp.EQ(this=left.copy(), expression=right.copy()),
                   exp.and_(exp.Is(this=left.copy(), expression=exp.Null()),
                            exp.Is(this=right.copy(), expression=exp.Null())))


def _window_function(node):
    while isinstance(node, (exp.Filter, exp.IgnoreNulls, exp.RespectNulls)):
        node = node.this
    return node


def _scopes(statement):
    order = {id(node): index for index, node in enumerate(statement.walk())}
    return sorted(traverse_scope(statement), key=lambda scope: order[id(scope.expression)])


def _unique_source_aliases(statement):
    identifiers = {node.name.casefold() for node in statement.find_all(exp.Identifier)}
    prefix = "__ac_scope"
    while any(name.startswith(prefix) for name in identifiers):
        prefix += "_"
    changes = []
    scopes = list(traverse_scope(statement))
    by_expression = {id(scope.expression): scope for scope in scopes}
    bindings = {}
    counter = 0
    for scope in scopes:
        bindings[id(scope)] = {}
        for alias, (node, _source) in scope.selected_sources.items():
            owner = node.parent if isinstance(node, (exp.Select, exp.SetOperation)) else node
            alias_node = owner.args.get("alias")
            if alias_node is None:
                continue
            counter += 1
            replacement = f"{prefix}_{counter}"
            bindings[id(scope)][alias] = replacement
            changes.append((alias_node, replacement))
    for column in statement.find_all(exp.Column):
        parent = column.parent
        while parent is not None and id(parent) not in by_expression:
            parent = parent.parent
        scope = by_expression.get(id(parent))
        while scope is not None:
            replacement = bindings[id(scope)].get(column.table)
            if replacement:
                column.set("table", exp.to_identifier(replacement, quoted=True))
                break
            scope = scope.parent
    for alias_node, replacement in changes:
        alias_node.set("this", exp.to_identifier(replacement, quoted=True))


def participation_key_trace(
    statement: exp.Expression,
    table_ref: SqlTableReference,
    metadata: TableMetadata,
    dialect: str,
    table_metadata: Sequence[TableMetadata] = (),
) -> tuple[exp.Select, list[str]]:
    clone = statement.copy()
    options = clone.args.pop("options", None)
    scopes = _scopes(clone)
    target = next((scope for index, scope in enumerate(scopes, 1)
                   if table_ref.scope_id == f"S{table_ref.statement_index}.Q{index}"), None)
    selected = target.selected_sources.get(table_ref.alias or table_ref.name) if target else None
    if selected is None and target is not None:
        source = target.sources.get(table_ref.alias or table_ref.name)
        if isinstance(source, exp.Table):
            selected = (source,source)
    if not selected or not isinstance(selected[1], exp.Table):
        raise ValueError("Cannot resolve the physical source occurrence.")
    selected[1].meta["ac_source_target"] = True
    source_table = selected[1].copy()
    source_table.set("pivots", None)
    mark_recursive_ctes(clone)
    scopes = _scopes(clone)

    schema = MappingSchema(dialect=dialect)
    metadata_by_name = {(item.schema.casefold(), item.name.casefold()): item
                        for item in [metadata, *table_metadata]}
    for scope in scopes:
        for source in scope.sources.values():
            if not isinstance(source, exp.Table):
                continue
            item = metadata_by_name.get((source.db.casefold(), source.name.casefold()))
            if item is None:
                matches = [item for (_schema, name), item in metadata_by_name.items()
                           if name == source.name.casefold()]
                item = matches[0] if len(matches) == 1 else None
            if item is not None and item.columns:
                source.meta["ac_physical_columns"] = {column.name.casefold(): column.name for column in item.columns}
                schema.add_table(source, {column.name: "UNKNOWN" for column in item.columns}, match_depth=False)
            source.meta["ac_physical_name"] = {key: value.copy() for key in ("this", "db", "catalog")
                                                if (value := source.args.get(key)) is not None}
    clone = explicit_joins(clone)

    # Qualify before adding witness columns, so SELECT * never captures them.
    for pivot in clone.find_all(exp.Pivot):
        if not pivot.args.get("unpivot"):
            for field in pivot.args.get("fields") or []:
                for item in field.expressions:
                    value = item.this if isinstance(item, exp.Alias) else item
                    if isinstance(value, exp.Column):
                        value.replace(exp.Literal.string(value.name))
    try:
        clone = qualify(clone, dialect=dialect, schema=schema, infer_schema=True,
                        canonicalize_table_aliases=False)
    except Exception as exc:
        raise ValueError(f"Cannot resolve source columns: {exc}") from exc
    # Normalization is for resolving aliases, not renaming physical identifiers
    # in databases that use case-sensitive collations.
    for scope in traverse_scope(clone):
        for alias, (_node, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table):
                continue
            for key, value in source.meta.get("ac_physical_name", {}).items():
                source.set(key, value.copy())
            columns = source.meta.get("ac_physical_columns", {})
            for column in scope.columns:
                if column.table == alias and column.name.casefold() in columns:
                    column.set("this", exp.to_identifier(columns[column.name.casefold()], quoted=True))
    if any(item.is_star for query in clone.find_all(exp.Select) for item in query.expressions):
        raise ValueError("SELECT * source tracing requires metadata for every referenced table.")
    clone = lower_pivots(clone)
    clone = distinct_on_queries(clone)
    _unique_source_aliases(clone)
    # Inline using lexical scopes, including nested WITH and reused CTEs.
    for scope in traverse_scope(clone):
        for _alias, (node, source) in scope.selected_sources.items():
            if isinstance(node, exp.Table) and isinstance(source, Scope) and not node.meta.get("ac_recursive"):
                node.replace(exp.Subquery(this=source.expression.copy(), alias=node.args["alias"].copy()))
    recursive_ctes = [cte.copy() for cte in clone.find_all(exp.CTE) if cte.meta.get("ac_recursive")]
    for query in clone.find_all(exp.Query):
        query.set("with_", None)
    if not recursive_ctes:
        clone = pushdown_projections(clone, schema=schema, dialect=dialect)

    tracer = _ParticipationTrace(clone, [column.name for column in metadata.columns if column.is_primary_key])
    definitions = recursive_witnesses(recursive_ctes, tracer, source_table)
    if isinstance(clone, exp.Select):
        names = set()
        for item in clone.expressions:
            if item.alias_or_name in names:
                item.set("alias", exp.to_identifier(tracer.name("output"), quoted=True))
            names.add(item.alias_or_name)
    traced = tracer.annotate(clone)
    result_alias = tracer.name("result")
    witness = exp.select("1").from_(traced.subquery(result_alias)).where(
        exp.EQ(this=_column(result_alias, tracer.marker), expression=exp.Literal.number(1)))
    source_table.set("alias", exp.TableAlias(this=exp.to_identifier(tracer.candidate, quoted=True)))
    key_aliases = [f"__ac_pk_{index}" for index in range(1, len(tracer.keys) + 1)]
    trace = exp.select(*[exp.alias_(_column(tracer.candidate, key), output, quoted=True)
                         for key, output in zip(tracer.keys, key_aliases)]).from_(source_table)
    trace = trace.where(exp.Exists(this=witness))
    if definitions:
        trace.set("with_", exp.With(expressions=definitions, recursive=True))
    if options:
        trace.set("options", options)
    return trace, key_aliases


class _ParticipationTrace:
    def __init__(self, statement, keys):
        identifiers = {node.name.casefold() for node in statement.find_all(exp.Identifier)}
        self.prefix = "__ac_witness"
        while any(name.startswith(self.prefix) for name in identifiers):
            self.prefix += "_"
        self.counter = 0
        self.marker = self.name("used")
        self.candidate = self.name("candidate")
        self.keys = keys
        self.candidate_columns = keys
        self.recursive = {}

    def name(self, suffix):
        self.counter += 1
        return f"{self.prefix}_{suffix}_{self.counter}"

    def annotate(self, query):
        if isinstance(query, exp.Lateral):
            inner = query.this
            if not isinstance(inner, exp.Subquery):
                raise ValueError("Table-valued functions require their underlying query definition.")
            inner.set("this", self.annotate(inner.this))
            return query
        if isinstance(query, exp.Subquery):
            return self.annotate(query.this)
        if isinstance(query, exp.SetOperation):
            result = self.set_operation(query)
            if not result.args.get("limit") and not result.args.get("offset"):
                result.set("order", None)
            return result
        if not isinstance(query, exp.Select):
            raise ValueError(f"Unsupported source query: {query.key}")

        scope = traverse_scope(query)[-1]
        flags = []
        # A witness is an extra value, never an extra joined row.
        for alias, (node, source) in scope.selected_sources.items():
            if isinstance(source, exp.Table):
                if source.meta.get("ac_recursive"):
                    node.replace(recursive_source(node, self))
                    flags.append(exp.EQ(this=_column(alias, self.marker), expression=exp.Literal.number(1)))
                elif source.meta.get("ac_recursive_step"):
                    flags.append(exp.EQ(this=_column(alias, self.marker), expression=exp.Literal.number(1)))
                elif source.meta.get("ac_source_target"):
                    flags.append(exp.and_(*[exp.EQ(this=_column(alias, key),
                                                   expression=_column(self.candidate, candidate))
                                           for key, candidate in zip(self.keys, self.candidate_columns)]))
            elif isinstance(source, Scope):
                annotated = self.annotate(source.expression.copy())
                source.expression.replace(annotated)
                flags.append(exp.EQ(this=_column(alias, self.marker), expression=exp.Literal.number(1)))

        # Keep scalar/EXISTS/IN queries unchanged in their original positions.
        # Their separate witness has the same correlations to the current row.
        for child in scope.subquery_scopes:
            annotated = self.annotate(child.expression.copy())
            child_alias = self.name("subquery")
            exists = exp.select("1").from_(annotated.subquery(child_alias)).where(
                exp.EQ(this=_column(child_alias, self.marker), expression=exp.Literal.number(1)))
            condition = exp.Exists(this=exists)
            parent = child.expression.parent
            if isinstance(parent, exp.Subquery) and isinstance(parent.parent, exp.In):
                in_node = parent.parent
                # Positive IN only uses matching values; NOT IN also depends on
                # nonmatches and NULLs. Keep those evaluated dependency rows.
                if not isinstance(in_node.parent, exp.Not):
                    values = in_node.this.expressions if isinstance(in_node.this,exp.Tuple) else [in_node.this]
                    exists = exists.where(exp.and_(*[exp.EQ(this=_column(child_alias, name), expression=value.copy())
                                                    for name,value in zip(annotated.named_selects[:-1],values)]))
                    condition = exp.Exists(this=exists)
            guard = self.branch_guard(child.expression, query)
            flags.append(exp.and_(guard, condition) if guard is not None else condition)

        condition = exp.or_(*flags) if flags else exp.false()
        local_nodes = list(query.walk(prune=lambda node: node is not query and isinstance(node, exp.Query)))
        windows = [node for node in local_nodes if isinstance(node, exp.Window)]
        aggregates = [node for node in local_nodes if isinstance(node, exp.AggFunc)
                      and not any(node is _window_function(window.this) for window in windows)]
        group = query.args.get("group")
        if group or aggregates:
            query, marker = self.row_stage(query, condition)
            condition = exp.EQ(this=exp.Max(this=marker), expression=exp.Literal.number(1))
            windows = list(query.find_all(exp.Window))
        if windows:
            query, condition = self.window_witness(query, condition, windows, bool(group or aggregates))

        query.set("expressions", [*query.expressions, exp.alias_(_flag(condition), self.marker, quoted=True)])
        if query.args.get("distinct"):
            if query.args["distinct"].args.get("on"):
                raise ValueError("DISTINCT ON source tracing is not supported.")
            query = self.collapse_distinct(query)
        # SQL Server disallows ORDER BY in derived queries without TOP/OFFSET.
        if not query.args.get("limit") and not query.args.get("offset"):
            query.set("order", None)
        return query

    def row_stage(self, query, condition):
        scope = traverse_scope(query)[-1]
        aliases = set(scope.selected_sources)
        columns = {column.sql(): column.copy() for column in scope.columns if column.table in aliases}
        mapping = {key: self.name("column") for key in columns}
        alias = self.name("rows")
        inner = query.copy()
        for clause in ("group", "having", "qualify", "distinct", "order", "limit", "offset"):
            inner.set(clause, None)
        inner.set("expressions", [
            *[exp.alias_(column, mapping[key], quoted=True) for key, column in columns.items()],
            exp.alias_(_flag(condition), self.marker, quoted=True),
        ])
        outer = query.copy()
        for clause in ("from_", "joins", "where"):
            outer.set(clause, None)
        outer = outer.transform(lambda node: _column(alias, mapping[node.sql()]) if isinstance(node, exp.Column) and node.sql() in mapping else node)
        outer.set("from_", exp.From(this=inner.subquery(alias)))
        return outer, _column(alias, self.marker)

    def window_witness(self, query, condition, windows, grouped):
        """Evaluate participation with the database's own window/frame engine."""
        stage = query.copy()
        for clause in ("qualify", "distinct", "order", "limit", "offset"):
            stage.set(clause, None)
        outer = query.copy()
        for clause in ("from_", "joins", "where", "group", "having"):
            outer.set(clause, None)
        alias = self.name("window_input")
        atoms = {}
        group = query.args.get("group")
        for item in group.expressions if group else []:
            atoms[item.sql()] = item.copy()
        def outside_input(node):
            return (node is not outer and isinstance(node, exp.Query)) or node.sql() in atoms
        for node in outer.walk(prune=outside_input):
            window = node.find_ancestor(exp.Window)
            if grouped and isinstance(node, exp.AggFunc) and (window is None or node is not _window_function(window.this)):
                atoms[node.sql()] = node.copy()
            elif isinstance(node, exp.Column):
                atoms[node.sql()] = node.copy()
        mapping = {key: self.name("value") for key in atoms}
        def remap(node):
            name = mapping.get(node.sql()) if not isinstance(node, exp.Identifier) else None
            return _column(alias, name) if name else node
        outer = outer.transform(remap)
        stage.set("expressions", [
            *[exp.alias_(item, mapping[key], quoted=True) for key, item in atoms.items()],
            exp.alias_(_flag(condition), self.marker, quoted=True),
        ])
        marker = _column(alias, self.marker)
        flags = [exp.EQ(this=marker.copy(), expression=exp.Literal.number(1))]
        offset_inputs = []
        for window in windows:
            witness = window.copy().transform(remap)
            function = _window_function(window.this)
            if isinstance(function, (exp.RowNumber, exp.Rank, exp.DenseRank)):
                witness.set("spec", exp.WindowSpec(kind="RANGE", start="UNBOUNDED", start_side="PRECEDING", end="CURRENT ROW"))
                replacement = exp.Max(this=marker.copy())
            elif isinstance(function, (exp.PercentRank, exp.CumeDist, exp.Ntile)):
                witness.set("order", None)
                witness.set("spec", None)
                replacement = exp.Max(this=marker.copy())
            elif isinstance(function, (exp.Lag, exp.Lead)):
                # Keep the intervening rows too: dropping them changes offsets
                # when the extracted data is imported and the SQL is replayed.
                position = self.name("position")
                positions = window.copy()
                positions.set("this", exp.RowNumber())
                positions.set("spec", None)
                stage.select(exp.alias_(positions, position, quoted=True), copy=False)
                other = self.name("offset_rows")
                offset = (function.args.get("offset") or exp.Literal.number(1)).copy().transform(remap)
                current = _column(alias, position)
                boundary = (exp.Sub if isinstance(function, exp.Lag) else exp.Add)(this=current.copy(), expression=exp.Paren(this=offset))
                if window.this.find(exp.IgnoreNulls):
                    boundary_name = self.name("offset_boundary")
                    boundary_window = window.copy().transform(remap)
                    boundary_function = function.copy().transform(remap)
                    boundary_function.set("this", exp.Case().when(
                        exp.Not(this=exp.Is(this=function.this.copy().transform(remap), expression=exp.Null())),
                        current.copy(),
                    ).else_(exp.Null()))
                    boundary_function.set("default", exp.Null())
                    boundary_function.set("offset", offset.copy())
                    boundary_window.set("this", exp.IgnoreNulls(this=boundary_function))
                    offset_inputs.append(exp.alias_(boundary_window, boundary_name, quoted=True))
                    boundary = exp.Coalesce(this=_column(alias, boundary_name), expressions=[
                        exp.Literal.number(0) if isinstance(function, exp.Lag) else _column(other, position),
                    ])
                low, high = (boundary, current) if isinstance(function, exp.Lag) else (current, boundary)
                matches = [
                    _equal(item.copy().transform(remap), item.copy().transform(remap).transform(
                        lambda node: _column(other, node.name) if isinstance(node, exp.Column) and node.table == alias else node))
                    for item in window.args.get("partition_by") or []
                ]
                matches.extend([
                    exp.Between(this=_column(other, position), low=low, high=high),
                    exp.EQ(this=_column(other, self.marker), expression=exp.Literal.number(1)),
                ])
                flags.append(exp.Exists(this=exp.select("1").from_(stage.copy().subquery(other)).where(exp.and_(*matches))))
                continue
            else:
                replacement = exp.Max(this=marker.copy())
                spec = witness.args.get("spec")
                if spec:
                    spec.set("exclude", None)
                    if spec.args.get("kind") == "ROWS":
                        if spec.args.get("start_side") == "FOLLOWING":
                            spec.set("start", "CURRENT ROW")
                            spec.set("start_side", None)
                        if spec.args.get("end_side") == "PRECEDING":
                            spec.set("end", "CURRENT ROW")
                            spec.set("end_side", None)
            witness.set("this", replacement)
            flags.append(exp.EQ(this=witness, expression=exp.Literal.number(1)))
        if offset_inputs:
            input_alias = self.name("offset_input")
            inputs = [item.transform(lambda node: _column(input_alias, node.name)
                      if isinstance(node, exp.Column) and node.table == alias else node) for item in offset_inputs]
            stage = exp.select(*[_column(input_alias, name) for name in stage.named_selects], *inputs).from_(stage.subquery(input_alias))
        outer.set("from_", exp.From(this=stage.subquery(alias)))
        return outer, exp.or_(*flags)

    def branch_guard(self, child, query):
        guards = []
        current = child
        while current.parent is not None and current.parent is not query:
            parent = current.parent
            if isinstance(parent, exp.Case):
                branches = parent.args.get("ifs") or []
                operand = parent.this
                for branch in branches:
                    condition = exp.EQ(this=operand.copy(), expression=branch.this.copy()) if operand else branch.this.copy()
                    if current is branch:
                        # A subquery used to evaluate WHEN is needed even when
                        # that WHEN is false. Only guard the THEN expression.
                        if not any(node is child for node in branch.this.walk()):
                            guards.append(condition)
                        break
                    guards.append(exp.EQ(this=_flag(condition), expression=exp.Literal.number(0)))
            current = parent
        return exp.and_(*guards) if guards else None

    def collapse_distinct(self, query):
        names = query.named_selects[:-1]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate projection names require explicit SQL aliases for DISTINCT tracing.")
        order, limit, offset = (query.args.get(key) for key in ("order", "limit", "offset"))
        query.set("distinct", None)
        for key in ("order", "limit", "offset"):
            query.set(key, None)
        alias = self.name("distinct")
        result = exp.select(*[_column(alias, name) for name in names],
                            exp.alias_(exp.Max(this=_column(alias, self.marker)), self.marker, quoted=True))
        result = result.from_(query.subquery(alias)).group_by(*[_column(alias, name) for name in names])
        if order:
            mappings = {_value(item).sql(): item.alias_or_name for item in query.expressions[:-1]}
            rewritten = order.copy()
            for item in rewritten.expressions:
                value = item.this
                if value.sql() in mappings:
                    item.set("this", _column(alias, mappings[value.sql()]))
                elif isinstance(value, exp.Column) and value.name in names:
                    item.set("this", _column(alias, value.name))
                elif not isinstance(value, exp.Literal):
                    raise ValueError("DISTINCT ordering must reference a projected column.")
            result.set("order", rewritten)
        result.set("limit", limit)
        result.set("offset", offset)
        return result

    def set_operation(self, query):
        original = query.copy()
        left = self.annotate(query.this.copy())
        right = self.annotate(query.expression.copy())
        if query.args.get("by_name"):
            names = list(dict.fromkeys([*left.named_selects[:-1],*right.named_selects[:-1]]))
            def align(branch):
                alias = self.name("by_name")
                return exp.select(*[
                    exp.alias_(_column(alias,name) if name in branch.named_selects else exp.Null(),name,quoted=True)
                    for name in [*names,self.marker]
                ]).from_(branch.subquery(alias))
            left,right = align(left),align(right)
            query.set("by_name",False)
        if isinstance(query, exp.Union):
            query.set("this", left)
            query.set("expression", right)
            distinct = query.args.get("distinct") is not False
            query.set("distinct", False)
            if not distinct:
                return query
            alias = self.name("union")
            names = left.named_selects[:-1]
            wrapped = exp.select(*[_column(alias, name) for name in names], _column(alias, self.marker))
            for key in ("order", "limit", "offset"):
                wrapped.set(key, query.args.get(key))
                query.set(key, None)
            wrapped = wrapped.from_(query.subquery(alias))
            wrapped.set("distinct", exp.Distinct())
            return self.collapse_distinct(wrapped)

        alias = self.name("set")
        flags = []
        branches = [left, right] if isinstance(query, exp.Intersect) or query.args.get("distinct") is False else [left]
        for branch in branches:
            branch_alias = self.name("branch")
            matching = exp.select("1").from_(branch.subquery(branch_alias)).where(
                exp.and_(*[_equal(_column(alias, output), _column(branch_alias, name))
                           for output, name in zip(original.named_selects, branch.named_selects[:-1])],
                         exp.EQ(this=_column(branch_alias, self.marker), expression=exp.Literal.number(1))))
            flags.append(exp.Exists(this=matching))
        if not original.args.get("limit") and not original.args.get("offset"):
            original.set("order", None)
        return exp.select(*[_column(alias, name) for name in original.named_selects],
                          exp.alias_(_flag(exp.or_(*flags)), self.marker, quoted=True)).from_(original.subquery(alias))

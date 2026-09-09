"""Carry source keys through relational projections without changing predicates."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


def projection_key_trace(statement, table_ref, key_columns):
    scopes = list(traverse_scope(statement))
    walk_order = {id(node): index for index, node in enumerate(statement.walk())}
    scopes.sort(key=lambda scope: walk_order[id(scope.expression)])
    scope_by_id = {
        f"S{table_ref.statement_index}.Q{index}": scope
        for index, scope in enumerate(scopes, 1)
    }
    target = scope_by_id.get(table_ref.scope_id)
    if target is None:
        raise ValueError("Cannot resolve the source query scope.")
    root = scopes[0]
    alias = table_ref.alias or table_ref.name
    selected = target.selected_sources.get(alias)
    if not selected or not isinstance(selected[1], exp.Table):
        raise ValueError("Source is not a physical table in its query scope.")

    # Adding keys is valid for relational projections, but not cardinality/order
    # operators or scalar subqueries whose arity and correlation must be retained.
    for scope in scopes:
        query = scope.expression
        if not isinstance(query, exp.Select):
            raise ValueError("Set operations require branch-specific source lineage.")
        for clause in ("group", "having", "qualify", "limit", "offset"):
            if query.args.get(clause):
                raise ValueError(f"{clause.upper()} requires cardinality-aware source lineage.")
    if any(isinstance(node, (exp.AggFunc, exp.Window, exp.Pivot)) for node in statement.walk()):
        raise ValueError("Aggregate/window/pivot requires cardinality-aware source lineage.")
    if any(node.args.get("recursive") for node in statement.find_all(exp.With)):
        raise ValueError("Recursive CTE requires recursive source lineage.")
    if any(join.args.get("method") == "NATURAL" for join in statement.find_all(exp.Join)):
        raise ValueError("NATURAL JOIN requires schema-aware source lineage.")
    if any(scope.subquery_scopes for scope in scopes):
        raise ValueError("Scalar/EXISTS/IN subqueries require correlated source lineage.")
    if any(query.args.get("with_") for query in statement.find_all(exp.Select) if query is not statement):
        raise ValueError("Nested WITH requires lexical CTE normalization.")

    def paths(scope, visited):
        if id(scope) in visited:
            raise ValueError("Recursive source dependency.")
        if scope is target:
            return [[(scope, alias)]]
        result = []
        for source_alias, (_node, source) in scope.selected_sources.items():
            if isinstance(source, Scope):
                for path in paths(source, visited | {id(scope)}):
                    result.append([(scope, source_alias), *path])
        return result

    routes = paths(root, set())
    if not routes:
        raise ValueError("Source has no relational path to the query result.")
    identifiers = {node.name.casefold() for node in statement.find_all(exp.Identifier)}
    prefix = "__ac_lineage"
    while any(name.startswith(prefix) for name in identifiers):
        prefix += "_"
    keys = [f"{prefix}_{index}" for index in range(len(key_columns))]
    branches = []
    # Separate branches cover every use of a shared CTE (including self joins).
    # Inline the traced CTE references so each branch has independent projections.
    for route in routes:
        clone = statement.copy()
        clone_scopes = list(traverse_scope(clone))
        clone_order = {id(node): index for index, node in enumerate(clone.walk())}
        clone_scopes.sort(key=lambda scope: clone_order[id(scope.expression)])
        mapped = {id(scope): clone_scopes[index] for index, scope in enumerate(scopes)}
        child_keys = list(key_columns)
        for level, (scope, source_alias) in enumerate(reversed(route)):
            copied_scope = mapped[id(scope)]
            query = copied_scope.expression
            output_keys = [f"{prefix}_{level}_{index}" for index in range(len(keys))]
            source_node = copied_scope.selected_sources[source_alias][0]
            if isinstance(source_node, exp.Select):
                source_node = source_node.parent
            source_identifier = source_node.args.get("alias")
            source_identifier = source_identifier.this if source_identifier else source_node.this
            projections = [
                exp.alias_(exp.Column(this=exp.to_identifier(name, quoted=True), table=source_identifier.copy()), output, quoted=True)
                for name, output in zip(child_keys, output_keys)
            ]
            if scope is root:
                query.set("expressions", [
                    exp.alias_(projection.this.copy(), key, quoted=True)
                    for projection, key in zip(projections, keys)
                ])
                query.set("distinct", exp.Distinct())
            else:
                query.set("expressions", [*query.expressions, *projections])
                parent = query.parent
                alias_node = parent.args.get("alias") if parent is not None else None
                if alias_node is not None and alias_node.args.get("columns"):
                    if any(item.is_star for item in query.expressions):
                        raise ValueError("Explicit column lists with SELECT * require schema expansion.")
                    alias_node.set("columns", [*alias_node.args["columns"], *[
                        exp.to_identifier(name, quoted=True) for name in output_keys
                    ]])
            query.set("order", None)
            child_keys = output_keys
        # A branch may have its own augmented CTE definitions. Convert CTE uses
        # to derived queries bottom-up before combining branches with UNION.
        for scope in list(traverse_scope(clone)):
            for _alias, (node, source) in scope.selected_sources.items():
                if isinstance(source, Scope) and isinstance(node, exp.Table):
                    cte_alias = source.expression.parent.args.get("alias")
                    alias_node = node.args.get("alias")
                    if alias_node is None:
                        alias_node = exp.TableAlias(this=node.this.copy())
                    else:
                        alias_node = alias_node.copy()
                    if cte_alias is not None and cte_alias.args.get("columns"):
                        alias_node.set("columns", [column.copy() for column in cte_alias.args["columns"]])
                    inner = source.expression.copy()
                    if alias_node.args.get("columns"):
                        if any(item.is_star for item in inner.expressions):
                            raise ValueError("Explicit column lists with SELECT * require schema expansion.")
                        inner.set("expressions", [
                            exp.alias_(item.this.copy() if isinstance(item, exp.Alias) else item.copy(), name.name, quoted=True)
                            for item, name in zip(inner.expressions, alias_node.args["columns"])
                        ])
                        alias_node.set("columns", None)
                    node.replace(exp.Subquery(this=inner, alias=alias_node))
        for query in clone.find_all(exp.Select):
            query.set("with_", None)
        branches.append(clone)
    trace = branches[0]
    for branch in branches[1:]:
        trace = exp.Union(this=trace, expression=branch, distinct=True)
    return trace, keys

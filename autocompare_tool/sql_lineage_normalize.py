"""Normalize SQL surface syntax before row-participation tracing."""

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


def explicit_joins(statement):
    def names(source):
        if isinstance(source, exp.Table):
            return list(source.meta.get("ac_physical_columns", {}).values())
        result = source.expression.named_selects
        if "*" in result:
            return [name for _node, child in source.selected_sources.values() for name in names(child)]
        return result

    for scope in traverse_scope(statement):
        query = scope.expression
        if not isinstance(query, exp.Select) or not query.args.get("from_"):
            continue
        left = {}
        first = query.args["from_"].this.alias_or_name
        if first in scope.sources:
            left.update((name.casefold(), (first,name)) for name in names(scope.sources[first]))
        joins = []
        for join in query.args.get("joins") or []:
            alias = join.this.alias_or_name
            source = scope.sources.get(alias)
            columns = names(source) if source is not None else []
            if join.args.get("method") == "NATURAL":
                join.set("method", None)
                using = [exp.to_identifier(name, quoted=True) for name in columns if name.casefold() in left]
                if using:
                    join.set("using", using)
                else:
                    join.set("on", exp.true())
            if join.args.get("kind") in {"SEMI", "ANTI"}:
                predicate = join.args.get("on")
                if join.args.get("using"):
                    predicate = exp.and_(*[exp.EQ(
                        this=exp.column(left[name.name.casefold()][1], table=left[name.name.casefold()][0], quoted=True),
                        expression=exp.column(name.name,table=alias,quoted=True),
                    ) for name in join.args["using"]])
                subquery = exp.select("1").from_(join.this.copy())
                if predicate is not None:
                    subquery = subquery.where(predicate.copy())
                condition = exp.Exists(this=subquery)
                if join.args["kind"] == "ANTI":
                    condition = exp.Not(this=condition)
                query.where(condition,copy=False)
            else:
                joins.append(join)
                for name in columns:
                    left.setdefault(name.casefold(), (alias,name))
        query.set("joins", joins)
    return statement


def distinct_on_queries(statement):
    for query in reversed(list(statement.find_all(exp.Select))):
        distinct = query.args.get("distinct")
        if not distinct or not distinct.args.get("on"):
            continue
        aliases = {item.alias_or_name for item in query.expressions}
        def name(prefix):
            while prefix in aliases:
                prefix += "_"
            aliases.add(prefix)
            return prefix
        row_number = name("__ac_distinct_row")
        source_alias = name("__ac_distinct_input")
        columns = query.named_selects[:]
        mappings = {(item.this if isinstance(item,exp.Alias) else item).sql(): item.alias_or_name for item in query.expressions}
        order = query.args.get("order")
        final_order = order.copy() if order else None
        if final_order:
            for item in final_order.expressions:
                output = mappings.get(item.this.sql())
                if not output and isinstance(item.this,exp.Column) and not item.this.table and item.this.name in columns:
                    output = item.this.name
                if not output:
                    output = name("__ac_distinct_order")
                    query.select(exp.alias_(item.this.copy(),output,quoted=True),copy=False)
                item.set("this",exp.column(output,table=source_alias,quoted=True))
        projections = {item.alias_or_name: item.this if isinstance(item, exp.Alias) else item
                       for item in query.expressions}
        def resolve_output(node):
            if isinstance(node, exp.Column) and not node.table and node.name in projections:
                return projections[node.name].copy()
            return node
        window = exp.Window(
            this=exp.RowNumber(),
            partition_by=[item.copy().transform(resolve_output) for item in distinct.args["on"].expressions],
            order=order.copy().transform(resolve_output) if order else None,
        )
        query.select(exp.alias_(window,row_number,quoted=True),copy=False)
        limit, offset, with_ = (query.args.get(key) for key in ("limit","offset","with_"))
        for key in ("limit","offset","with_","distinct","order"):
            query.set(key,None)
        result = exp.select(*[exp.alias_(exp.column(column,table=source_alias,quoted=True),column,quoted=True) for column in columns]).from_(query.copy().subquery(source_alias))
        result = result.where(exp.EQ(this=exp.column(row_number,table=source_alias,quoted=True),expression=exp.Literal.number(1)))
        result.set("order",final_order)
        result.set("limit",limit)
        result.set("offset",offset)
        result.set("with_",with_)
        if query is statement:
            statement = result
        else:
            query.replace(result)
    return statement

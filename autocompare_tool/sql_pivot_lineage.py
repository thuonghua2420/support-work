"""Lower PIVOT/UNPIVOT to relational projections with explicit group members."""

from sqlglot import exp


def lower_pivots(statement):
    for pivot in reversed(list(statement.find_all(exp.Pivot))):
        source = pivot.parent
        alias = source.alias_or_name
        if isinstance(source, exp.Subquery):
            columns = source.this.named_selects
        else:
            columns = list(source.meta.get("ac_physical_columns", {}).values())
        if not columns:
            raise ValueError("PIVOT needs metadata for its input columns.")
        base = source.copy()
        base.set("pivots", None)
        if not base.args.get("alias"):
            base.set("alias", exp.TableAlias(this=exp.to_identifier(alias, quoted=True)))
        field = pivot.args["fields"][0]
        output_alias = pivot.args.get("alias") or source.args.get("alias")
        if pivot.args.get("unpivot"):
            consumed = {column.name.casefold() for item in field.expressions for column in item.find_all(exp.Column)}
            groups = [name for name in columns if name.casefold() not in consumed]
            branches = []
            output = pivot.expressions[0].name
            label = field.this.name
            for item in field.expressions:
                value = item.this if isinstance(item, exp.Alias) else item
                if not isinstance(value, exp.Column):
                    raise ValueError("UNPIVOT input must resolve to a column.")
                column = exp.column(value.name, table=alias, quoted=True)
                branch = exp.select(*[exp.alias_(exp.column(name, table=alias, quoted=True),name,quoted=True) for name in groups],
                    exp.alias_(exp.Literal.string(item.alias or value.name), label, quoted=True),
                    exp.alias_(column.copy(), output, quoted=True)).from_(base.copy())
                if not pivot.args.get("include_nulls"):
                    branch = branch.where(exp.Not(this=exp.Is(this=column, expression=exp.Null())))
                branches.append(branch)
            lowered = branches[0]
            for branch in branches[1:]:
                lowered = exp.Union(this=lowered, expression=branch, distinct=False)
        else:
            consumed = {column.name.casefold() for aggregate in pivot.expressions for column in aggregate.find_all(exp.Column)}
            consumed.update(column.name.casefold() for column in field.this.find_all(exp.Column))
            groups = [name for name in columns if name.casefold() not in consumed]
            outputs = [exp.alias_(exp.column(name, table=alias, quoted=True),name,quoted=True) for name in groups]
            names = iter(pivot.args["columns"])
            for item in field.expressions:
                value = item.this if isinstance(item, exp.Alias) else item
                if isinstance(value, exp.Column):
                    value = exp.Literal.string(value.name)
                condition = exp.EQ(this=field.this.copy(), expression=value.copy())
                condition = condition.transform(lambda node: exp.column(node.name,table=alias,quoted=True) if isinstance(node,exp.Column) else node)
                for aggregate in pivot.expressions:
                    expression = aggregate.this if isinstance(aggregate, exp.Alias) else aggregate
                    expression = expression.copy()
                    def conditional(node):
                        if isinstance(node, exp.Column):
                            return exp.Case().when(condition.copy(), exp.column(node.name,table=alias,quoted=True)).else_(exp.Null())
                        if isinstance(node, exp.Star):
                            return exp.Case().when(condition.copy(), exp.Literal.number(1)).else_(exp.Null())
                        return node
                    expression = expression.transform(conditional)
                    outputs.append(exp.alias_(expression,next(names).name,quoted=True))
            lowered = exp.select(*outputs).from_(base)
            if groups:
                lowered = lowered.group_by(*[exp.column(name,table=alias,quoted=True) for name in groups])
        source.replace(exp.Subquery(this=lowered,alias=output_alias.copy() if output_alias else None))
    return statement

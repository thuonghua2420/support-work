"""Preserve recursive results while carrying source participation along paths."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


def enable_recursive_ctes(statement):
    recursive = []
    for cte in statement.find_all(exp.CTE):
        if isinstance(cte.this, exp.SetOperation) and any(
            not table.db and not table.catalog and table.name.casefold() == cte.alias.casefold()
            for table in cte.this.find_all(exp.Table)
        ):
            cte.parent.set("recursive", True)
            recursive.append(cte)
    return recursive


def mark_recursive_ctes(statement):
    recursive = enable_recursive_ctes(statement)
    references = []
    for scope in traverse_scope(statement):
        for _node, source in scope.selected_sources.values():
            if isinstance(source, Scope):
                owner = source.expression.find_ancestor(exp.CTE)
                if owner is not None and any(owner is cte for cte in recursive):
                    references.append((_node, owner))
    identifiers = {node.name.casefold() for node in statement.find_all(exp.Identifier)}
    for index, cte in enumerate(recursive):
        name = f"__ac_recursive_{index}"
        while name.casefold() in identifiers:
            name += "_"
        identifiers.add(name.casefold())
        cte.meta["ac_recursive"] = name
        cte.args["alias"].set("this", exp.to_identifier(name, quoted=True))
        for node, owner in references:
            if owner is not cte:
                continue
            if node.args.get("alias") is None:
                node.set("alias", exp.TableAlias(this=node.this.copy()))
            node.set("this", exp.to_identifier(name, quoted=True))
            node.meta["ac_recursive"] = name


def recursive_witnesses(ctes, tracer, source_table):
    from .sql_row_lineage import _column

    definitions = []
    for cte in ctes:
        original_name = cte.alias
        trace_name = tracer.name("recursive_trace")
        columns = [column.name for column in (cte.args["alias"].args.get("columns") or [])] or cte.this.named_selects
        candidate_columns = [tracer.name("recursive_key") for _key in tracer.keys]
        tracer.recursive[original_name] = (trace_name, columns, candidate_columns)
        original = cte.copy()
        definitions.append(original)

        def build(branch):
            if isinstance(branch, exp.Union):
                result = branch.copy()
                result.set("this", build(branch.this))
                result.set("expression", build(branch.expression))
                return result
            branch = branch.copy()
            refs = [table for table in branch.find_all(exp.Table) if table.meta.get("ac_recursive") == original_name]
            saved_candidate, saved_columns = tracer.candidate, tracer.candidate_columns
            try:
                if refs:
                    if len(refs) != 1:
                        raise ValueError("Recursive member must have one self reference, as required by the SQL engine.")
                    reference = refs[0]
                    reference.set("this", exp.to_identifier(trace_name, quoted=True))
                    reference.meta.pop("ac_recursive", None)
                    reference.meta["ac_recursive_step"] = True
                    tracer.candidate = reference.alias_or_name
                    tracer.candidate_columns = candidate_columns
                    traced = tracer.annotate(branch)
                    keys = [_column(tracer.candidate, key) for key in candidate_columns]
                else:
                    candidate_alias = tracer.name("recursive_candidate")
                    candidate = source_table.copy()
                    candidate.meta.pop("ac_source_target", None)
                    candidate.set("alias", exp.TableAlias(this=exp.to_identifier(candidate_alias, quoted=True)))
                    tracer.candidate = candidate_alias
                    tracer.candidate_columns = tracer.keys
                    cardinality = any(isinstance(node, (exp.AggFunc, exp.Window, exp.Subquery)) for node in branch.walk()) or any(
                        branch.args.get(key) for key in ("group", "distinct", "limit", "offset"))
                    if cardinality:
                        inner = tracer.annotate(branch)
                        alias = tracer.name("recursive_seed")
                        lateral = exp.Lateral(this=inner.subquery(), alias=exp.TableAlias(this=exp.to_identifier(alias)), cross_apply=True)
                        traced = exp.select(*[_column(alias, name) for name in inner.named_selects]).from_(candidate)
                        traced.set("joins", [exp.Join(this=lateral)])
                    else:
                        branch = branch.join(candidate, join_type="CROSS")
                        traced = tracer.annotate(branch)
                    keys = [_column(candidate_alias, key) for key in tracer.keys]
                # Explicit output names remain stable across anchor/member aliases.
                outputs = traced.expressions
                traced.set("expressions", [
                    *[exp.alias_(item.this.copy() if isinstance(item, exp.Alias) else item.copy(), name, quoted=True)
                      for item, name in zip(outputs[:-1], columns)],
                    outputs[-1],
                    *[exp.alias_(key, name, quoted=True) for key, name in zip(keys, candidate_columns)],
                ])
                return traced
            finally:
                tracer.candidate, tracer.candidate_columns = saved_candidate, saved_columns

        traced = build(cte.this)
        definitions.append(exp.CTE(this=traced, alias=exp.TableAlias(
            this=exp.to_identifier(trace_name, quoted=True),
            columns=[exp.to_identifier(name, quoted=True) for name in [*columns, tracer.marker, *candidate_columns]],
        )))
    return definitions


def recursive_source(node, tracer):
    from .sql_row_lineage import _column, _equal, _flag

    name = node.meta["ac_recursive"]
    trace_name, columns, keys = tracer.recursive[name]
    alias = tracer.name("recursive_rows")
    witness_alias = tracer.name("recursive_path")
    original = node.copy()
    original.meta.pop("ac_recursive", None)
    original.set("alias", exp.TableAlias(this=exp.to_identifier(alias, quoted=True)))
    matches = [
        *[_equal(_column(witness_alias, column), _column(alias, column)) for column in columns],
        *[exp.EQ(this=_column(witness_alias, key), expression=_column(tracer.candidate, candidate))
          for key, candidate in zip(keys, tracer.candidate_columns)],
        exp.EQ(this=_column(witness_alias, tracer.marker), expression=exp.Literal.number(1)),
    ]
    witness = exp.select("1").from_(exp.Table(this=exp.to_identifier(trace_name, quoted=True),
        alias=exp.TableAlias(this=exp.to_identifier(witness_alias, quoted=True)))).where(exp.and_(*matches))
    query = exp.select(*[_column(alias, column) for column in columns],
                       exp.alias_(_flag(exp.Exists(this=witness)), tracer.marker, quoted=True)).from_(original)
    return exp.Subquery(this=query, alias=node.args["alias"].copy())

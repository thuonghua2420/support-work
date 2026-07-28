# Agents Workspace

This folder is the project memory for future agents and maintainers. Update it when the project shape changes, especially when workflows, folder rules, or DB/CSV behavior changes.

## File Map

- `project-context.md`: product purpose, users, current workflows, and domain terms.
- `architecture.md`: module responsibilities and data flow.
- `conventions.md`: coding, CSV, DB, Excel, and test conventions.
- `roadmap.md`: near-term cleanup and growth opportunities.
- `decisions.md`: lightweight decision log and ADR template.

## How To Use

1. Start with root `AGENTS.md`.
2. Read the relevant `.agents` file before changing behavior.
3. Keep docs close to the current code. Prefer exact module names and commands.
4. Add dated decisions when a change affects future design direction.

## Maintenance Rule

When code behavior changes, update at least one of:

- `README.md` for user-facing behavior.
- `.agents/project-context.md` for product/workflow behavior.
- `.agents/architecture.md` for module/data-flow behavior.
- `.agents/conventions.md` for rules future code should follow.
- `.agents/decisions.md` for tradeoffs or irreversible choices.

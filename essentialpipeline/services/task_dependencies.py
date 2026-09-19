"""
Task dependency graph helpers for EssentialPipeline (Decision 5).

TaskDependency has no application-level place it gets created yet other
than Flask-Admin's raw CRUD, and nothing validates the edges it forms.
Without a check, a cyclic dependency (A depends on B depends on A) isn't
an infinite loop - execute_task() only looks at direct dependencies - but
it is an unsatisfiable deadlock: every task in the cycle requires another
task in the same cycle to have already succeeded, so none of them can
ever run. This is meant to be called before a TaskDependency is created.
"""


def creates_cycle(task_id: int, depends_on_task_id: int) -> bool:
    """
    Would adding "task_id depends on depends_on_task_id" create a cycle?

    True if depends_on_task_id already (transitively) depends on task_id,
    or if they're the same task (a 1-node cycle).
    """
    from essentialpipeline import db
    from essentialpipeline.models import TaskDependency

    if task_id == depends_on_task_id:
        return True

    # Callers (Flask-Admin's on_model_change in particular) may invoke this
    # with a not-yet-persisted TaskDependency already pending on the
    # session - querying here would otherwise autoflush that half-built
    # row and fail on its not-yet-set columns.
    with db.session.no_autoflush:
        visited = set()
        frontier = [depends_on_task_id]
        while frontier:
            current = frontier.pop()
            if current == task_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            deps = TaskDependency.query.filter_by(task_id=current).all()
            frontier.extend(d.depends_on_task_id for d in deps)

    return False


def different_projects(task_id: int, depends_on_task_id: int) -> bool:
    """
    A task depending on another task outside its own project doesn't fit
    this app's model - a project's pipeline is scoped to its own tasks
    (Decision 8) - so this is rejected alongside cycles, in the same
    validation pass.
    """
    from essentialpipeline import db
    from essentialpipeline.models import Task

    with db.session.no_autoflush:
        task = Task.query.get(task_id)
        depends_on = Task.query.get(depends_on_task_id)

    if not task or not depends_on:
        return False
    return task.project_id != depends_on.project_id

from core.tasks import (
    BacktestTaskDefinition,
    TaskAction,
    TaskStateMachine,
    TaskStatus,
)


def test_tasks_package_exports_task_domain() -> None:
    assert BacktestTaskDefinition.__name__ == "BacktestTaskDefinition"
    assert TaskAction.START.value == "start"
    assert TaskStateMachine.default().can(TaskStatus.CREATED, "start")

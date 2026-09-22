from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


TASK_STATES = {
    "pending",
    "blocked",
    "ready",
    "queued",
    "running",
    "generated",
    "approved",
    "committed",
    "failed",
    "cancelled",
    "stale",
}
DEPENDENCY_STATES = {"generated", "approved", "committed"}
GENERATOR_KINDS = {"text", "image", "deterministic"}

_STATE_RANK = {
    "pending": 0,
    "blocked": 0,
    "ready": 0,
    "queued": 0,
    "running": 0,
    "generated": 1,
    "approved": 2,
    "committed": 3,
    "failed": -1,
    "cancelled": -1,
    "stale": -1,
}


class GenerationPlanError(ValueError):
    pass


class GenerationPlanCycleError(GenerationPlanError):
    def __init__(self, task_keys: Iterable[str]) -> None:
        keys = sorted(set(task_keys))
        self.task_keys = keys
        super().__init__(
            "Generation plan contains a dependency cycle involving: "
            + ", ".join(keys)
        )


@dataclass(slots=True, frozen=True)
class GenerationDependency:
    task_key: str
    required_state: str = "generated"

    def __post_init__(self) -> None:
        if self.required_state not in DEPENDENCY_STATES:
            raise GenerationPlanError(
                f"Unsupported dependency state: {self.required_state}"
            )


@dataclass(slots=True)
class GenerationTaskDefinition:
    key: str
    generator_kind: str
    target_kind: str
    label: str = ""
    target_key: str | None = None
    prompt: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    dependencies: list[GenerationDependency] = field(default_factory=list)

    def validate(self) -> None:
        if not self.key.strip():
            raise GenerationPlanError("Task key cannot be empty")
        if self.generator_kind not in GENERATOR_KINDS:
            raise GenerationPlanError(
                f"Unsupported generator kind for {self.key}: "
                f"{self.generator_kind}"
            )
        if not self.target_kind.strip():
            raise GenerationPlanError(
                f"Target kind cannot be empty for task {self.key}"
            )
        seen: set[str] = set()
        for dependency in self.dependencies:
            if dependency.task_key == self.key:
                raise GenerationPlanError(
                    f"Task {self.key} cannot depend on itself"
                )
            if dependency.task_key in seen:
                raise GenerationPlanError(
                    f"Task {self.key} repeats dependency "
                    f"{dependency.task_key}"
                )
            seen.add(dependency.task_key)


@dataclass(slots=True)
class GenerationPlanDefinition:
    name: str
    tasks: list[GenerationTaskDefinition]
    source_kind: str | None = None
    source_id: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    def task_map(self) -> dict[str, GenerationTaskDefinition]:
        result: dict[str, GenerationTaskDefinition] = {}
        for task in self.tasks:
            task.validate()
            if task.key in result:
                raise GenerationPlanError(
                    f"Duplicate generation task key: {task.key}"
                )
            result[task.key] = task
        return result

    def validate(self) -> None:
        tasks = self.task_map()
        if not self.name.strip():
            raise GenerationPlanError("Generation plan name cannot be empty")
        for task in tasks.values():
            for dependency in task.dependencies:
                if dependency.task_key not in tasks:
                    raise GenerationPlanError(
                        f"Task {task.key} depends on missing task "
                        f"{dependency.task_key}"
                    )
        topological_layers(self.tasks)


def _definition_dependencies(
    tasks: Iterable[GenerationTaskDefinition],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    incoming: dict[str, set[str]] = {}
    outgoing: dict[str, set[str]] = {}

    for task in tasks:
        incoming.setdefault(task.key, set())
        outgoing.setdefault(task.key, set())

    for task in tasks:
        for dependency in task.dependencies:
            incoming[task.key].add(dependency.task_key)
            outgoing[dependency.task_key].add(task.key)

    return incoming, outgoing


def topological_layers(
    tasks: Iterable[GenerationTaskDefinition],
) -> list[list[str]]:
    task_list = list(tasks)
    incoming, outgoing = _definition_dependencies(task_list)

    ready = sorted(
        key for key, dependencies in incoming.items()
        if not dependencies
    )
    layers: list[list[str]] = []
    visited: set[str] = set()

    while ready:
        layer = ready
        layers.append(layer)
        next_ready: set[str] = set()

        for key in layer:
            visited.add(key)
            for child in outgoing[key]:
                incoming[child].discard(key)
                if not incoming[child]:
                    next_ready.add(child)

        ready = sorted(next_ready - visited)

    if len(visited) != len(incoming):
        raise GenerationPlanCycleError(
            key for key in incoming if key not in visited
        )
    return layers


def dependency_satisfied(
    actual_state: str,
    required_state: str,
) -> bool:
    if required_state not in DEPENDENCY_STATES:
        raise GenerationPlanError(
            f"Unsupported dependency state: {required_state}"
        )
    return _STATE_RANK.get(actual_state, -1) >= _STATE_RANK[required_state]


def ready_task_keys(
    tasks: Iterable[Mapping[str, Any]],
    dependencies: Mapping[str, list[Mapping[str, Any]]],
) -> list[str]:
    by_key = {
        str(task["task_key"]): task
        for task in tasks
    }
    ready: list[str] = []

    for key, task in by_key.items():
        if task.get("status") not in {
            "pending",
            "blocked",
            "ready",
            "stale",
        }:
            continue

        requirements = dependencies.get(key, [])
        if all(
            dep["task_key"] in by_key
            and dependency_satisfied(
                str(by_key[dep["task_key"]]["status"]),
                str(dep["required_state"]),
            )
            for dep in requirements
        ):
            ready.append(key)

    return sorted(ready)


def descendant_keys(
    root_key: str,
    dependencies: Mapping[str, list[Mapping[str, Any]]],
) -> list[str]:
    children: dict[str, set[str]] = {}
    for task_key, requirements in dependencies.items():
        for dependency in requirements:
            children.setdefault(str(dependency["task_key"]), set()).add(
                task_key
            )

    found: set[str] = set()
    pending = list(children.get(root_key, set()))
    while pending:
        key = pending.pop()
        if key in found:
            continue
        found.add(key)
        pending.extend(children.get(key, set()) - found)

    return sorted(found)

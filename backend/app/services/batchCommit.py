from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class BatchCommitError(RuntimeError):
    pass


@dataclass(slots=True)
class BatchCommitResult:
    metadata: dict[str, Any] = field(default_factory=dict)


class BatchTaskCommitter(Protocol):
    """Publishes one approved generation result into canonical domain state."""

    def commit(
        self,
        *,
        plan: dict[str, Any],
        task: dict[str, Any],
    ) -> BatchCommitResult:
        ...


class NoopBatchCommitter:
    """Test/explicit artifact committer.

    This is intentionally not used automatically. Callers must opt into it.
    It is appropriate only when the generated result itself is the final
    artifact and no canonical StoryStudio domain write is required.
    """

    def commit(
        self,
        *,
        plan: dict[str, Any],
        task: dict[str, Any],
    ) -> BatchCommitResult:
        return BatchCommitResult(
            metadata={
                "mode": "noop",
                "task_key": task["task_key"],
            }
        )

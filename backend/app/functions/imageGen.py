from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.managers.aiManager import AIGeneratorManager
from app.schemas import WorkflowMappings
from app.services.runtimes import RuntimeFailure
from app.services.workflow import inject_workflow, validate_workflow


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class ImageGenerationRequest:
    positive_prompt: str
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    make_transparent: bool = False
    seed: int | None = None
    steps: int | None = None
    guidance: float | None = None
    checkpoint: str | None = None


@dataclass(slots=True, frozen=True)
class ImageWorkflow:
    """Validated ComfyUI workflow with normal and optional transparent outputs."""

    graph: dict[str, Any]
    mappings: WorkflowMappings

    @property
    def normal_output_node_id(self) -> str:
        return self.mappings.image_output.node_id

    @property
    def transparent_output_node_id(self) -> str | None:
        mapping = self.mappings.transparent_image_output
        return mapping.node_id if mapping is not None else None

    def output_node(self, make_transparent: bool) -> str:
        if not make_transparent:
            return self.normal_output_node_id
        if not self.transparent_output_node_id:
            raise RuntimeFailure(
                "Transparent image generation was requested, but this workflow "
                "does not define a transparent image output."
            )
        return self.transparent_output_node_id


def _inject_output_prefix(
    graph: dict[str, Any],
    output_node_id: str,
    filename_prefix: str | None,
) -> dict[str, Any]:
    rendered = copy.deepcopy(graph)
    if not filename_prefix:
        return rendered

    output = rendered.get(output_node_id, {})
    inputs = output.get("inputs", {})
    class_type = str(output.get("class_type", "")).replace("_", "").lower()
    if "filename_prefix" in inputs or "saveimage" in class_type:
        output.setdefault("inputs", {})
        output["inputs"]["filename_prefix"] = filename_prefix
    return rendered


async def generate_image(
    manager: AIGeneratorManager,
    workflow: ImageWorkflow,
    request: ImageGenerationRequest,
    *,
    cancel_event: asyncio.Event | None = None,
    progress: ProgressCallback | None = None,
    filename_prefix: str | None = None,
) -> list[tuple[bytes, str]]:
    """Run one generic image workflow and return raw generated image bytes.

    Persistence is intentionally excluded. The scheduler/ImageManager decides
    where files belong and which DB records should be updated.
    """
    cancel_event = cancel_event or asyncio.Event()

    async with manager.image_session(
        reason="validated image workflow requires exclusive GPU ownership"
    ) as comfy:
        mapping_errors = validate_workflow(
            workflow.graph,
            workflow.mappings,
            await comfy.object_info(),
        )
        if mapping_errors:
            raise RuntimeFailure(
                "Workflow validation failed: " + "; ".join(mapping_errors)
            )

        values: dict[str, Any] = {
            "positive_prompt": request.positive_prompt,
            "negative_prompt": request.negative_prompt,
            "width": request.width,
            "height": request.height,
            "seed": request.seed,
            "steps": request.steps,
            "guidance": request.guidance,
            "checkpoint": request.checkpoint,
        }
        rendered = inject_workflow(
            workflow.graph,
            workflow.mappings,
            {key: value for key, value in values.items() if value is not None},
        )

        output_node_id = workflow.output_node(request.make_transparent)
        rendered = _inject_output_prefix(
            rendered,
            output_node_id,
            filename_prefix,
        )

        async def emit(update: dict[str, Any]) -> None:
            if progress is not None:
                await progress(update)

        return await comfy.run_workflow(
            rendered,
            output_node_id,
            emit,
            cancel_event,
        )

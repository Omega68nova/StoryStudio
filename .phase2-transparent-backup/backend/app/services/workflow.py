from __future__ import annotations

import copy
from typing import Any

from app.schemas import WorkflowMappings


class WorkflowValidationError(ValueError):
    pass


def _expand_ui_subgraphs(source: dict[str, Any]) -> dict[str, Any]:
    definitions = {
        str(item.get("id")): item
        for item in ((source.get("definitions") or {}).get("subgraphs") or source.get("subgraphs") or [])
        if isinstance(item, dict) and item.get("id")
    }
    if not definitions:
        return source
    nodes = [copy.deepcopy(node) for node in source.get("nodes") or []]
    links = [copy.deepcopy(link) for link in source.get("links") or []]
    for instance in list(nodes):
        definition = definitions.get(str(instance.get("type")))
        if not definition or int(instance.get("mode", 0) or 0) == 4:
            continue
        instance_id = str(instance["id"])
        incoming = {int(link[4]): (str(link[1]), int(link[2])) for link in links if isinstance(link, list) and len(link) >= 5 and str(link[3]) == instance_id}
        output_sources: dict[int, tuple[str, int]] = {}
        for link in definition.get("links") or []:
            if not isinstance(link, dict):
                continue
            if int(link.get("target_id", 0)) == -20:
                output_sources[int(link.get("target_slot", 0))] = (f"{instance_id}:{link['origin_id']}", int(link.get("origin_slot", 0)))
        rewritten = []
        for link in links:
            if not isinstance(link, list) or len(link) < 5:
                rewritten.append(link)
                continue
            if str(link[3]) == instance_id:
                continue
            if str(link[1]) == instance_id:
                replacement = output_sources.get(int(link[2]))
                if replacement:
                    link[1], link[2] = replacement
            rewritten.append(link)
        links = rewritten
        nodes.remove(instance)
        for inner in definition.get("nodes") or []:
            clone = copy.deepcopy(inner)
            clone["id"] = f"{instance_id}:{inner['id']}"
            nodes.append(clone)
        for link in definition.get("links") or []:
            if not isinstance(link, dict) or int(link.get("target_id", 0)) == -20:
                continue
            origin_id = int(link.get("origin_id", 0))
            source_endpoint = incoming.get(int(link.get("origin_slot", 0))) if origin_id == -10 else (f"{instance_id}:{origin_id}", int(link.get("origin_slot", 0)))
            if source_endpoint is None:
                continue
            links.append([
                f"{instance_id}:{link.get('id')}", source_endpoint[0], source_endpoint[1],
                f"{instance_id}:{link.get('target_id')}", int(link.get("target_slot", 0)), link.get("type"),
            ])
            target_id, target_slot = f"{instance_id}:{link.get('target_id')}", int(link.get("target_slot", 0))
            target = next((item for item in nodes if str(item.get("id")) == target_id), None)
            if target and target_slot < len(target.get("inputs") or []):
                target["inputs"][target_slot]["link"] = f"{instance_id}:{link.get('id')}"
    expanded = copy.deepcopy(source)
    expanded["nodes"], expanded["links"] = nodes, links
    return expanded


def normalize_workflow_graph(
    source: dict[str, Any], object_info: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str]:
    """Return API prompt data, converting an editable ComfyUI graph when needed."""
    if not isinstance(source.get("nodes"), list):
        return copy.deepcopy(source), "api"
    if object_info is None:
        raise WorkflowValidationError(
            "This is a ComfyUI UI workflow. Start ComfyUI so StoryStudio can convert it, "
            "or export it with Workflow > Export (API)."
        )
    source = _expand_ui_subgraphs(source)
    nodes = {str(node.get("id")): node for node in source["nodes"] if isinstance(node, dict) and node.get("id") is not None}
    links: dict[Any, tuple[str, int]] = {}
    for link in source.get("links") or []:
        if isinstance(link, list) and len(link) >= 3:
            links[link[0]] = (str(link[1]), int(link[2]))
        elif isinstance(link, dict):
            link_id = link.get("id")
            origin_id = link.get("origin_id", link.get("origin_node_id"))
            if link_id is not None and origin_id is not None:
                links[link_id] = (str(origin_id), int(link.get("origin_slot", 0)))

    def resolve_source(node_id: str, output_slot: int, visited: set[str] | None = None) -> tuple[str, int]:
        node = nodes.get(node_id)
        if not node:
            raise WorkflowValidationError(f"Workflow link references missing node '{node_id}'")
        if int(node.get("mode", 0) or 0) != 4:
            return node_id, output_slot
        visited = set(visited or ())
        if node_id in visited:
            raise WorkflowValidationError(f"Bypass cycle involving node '{node_id}'")
        visited.add(node_id)
        outputs = node.get("outputs") or []
        output = outputs[output_slot] if output_slot < len(outputs) else {}
        candidates = [item for item in (node.get("inputs") or []) if item.get("link") is not None and item.get("type") == output.get("type")]
        if not candidates:
            raise WorkflowValidationError(f"Cannot resolve bypassed node '{node_id}' output {output_slot}")
        preferred = next((item for item in candidates if item.get("name") == output.get("name")), candidates[min(output_slot, len(candidates) - 1)])
        upstream = links.get(preferred.get("link"))
        if not upstream:
            raise WorkflowValidationError(f"Bypassed node '{node_id}' has a disconnected input")
        return resolve_source(upstream[0], upstream[1], visited)

    converted: dict[str, Any] = {}
    primitive_types = {"STRING", "INT", "FLOAT", "BOOLEAN"}
    for node_id, node in nodes.items():
        mode = int(node.get("mode", 0) or 0)
        if mode != 0:
            continue
        class_type = str(node.get("type", ""))
        metadata = object_info.get(class_type)
        if not isinstance(metadata, dict):
            raise WorkflowValidationError(f"ComfyUI does not currently provide node type '{class_type}'")
        inputs: dict[str, Any] = {}
        for item in node.get("inputs") or []:
            if not isinstance(item, dict) or item.get("link") is None:
                continue
            upstream = links.get(item["link"])
            if not upstream:
                raise WorkflowValidationError(f"Node '{node_id}' input '{item.get('name', '')}' has a missing link")
            inputs[str(item.get("name", ""))] = list(resolve_source(upstream[0], upstream[1]))
        widgets = list(node.get("widgets_values") or [])
        widget_index = 0
        metadata_inputs = metadata.get("input") or {}
        ordered = [*(metadata_inputs.get("required") or {}).items(), *(metadata_inputs.get("optional") or {}).items()]
        for input_name, specification in ordered:
            kind = specification[0] if isinstance(specification, list) and specification else None
            if not isinstance(kind, list) and kind not in primitive_types:
                continue
            if widget_index >= len(widgets):
                continue
            value = widgets[widget_index]
            widget_index += 1
            if input_name == "seed" and widget_index < len(widgets):
                control = widgets[widget_index]
                if control is None or (isinstance(control, str) and control in {"fixed", "increment", "decrement", "randomize"}):
                    widget_index += 1
            if input_name not in inputs:
                inputs[input_name] = value
        converted[node_id] = {"class_type": class_type, "inputs": inputs}
    if not converted:
        raise WorkflowValidationError("The UI workflow contains no active executable nodes")
    return converted, "ui"


def prune_workflow_graph(graph: dict[str, Any], output_node_id: str) -> dict[str, Any]:
    if output_node_id not in graph:
        return graph
    required: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in required or node_id not in graph:
            return
        required.add(node_id)
        for value in (graph[node_id].get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
                visit(str(value[0]))

    visit(output_node_id)
    return {node_id: node for node_id, node in graph.items() if node_id in required}


def validate_workflow(
    graph: dict[str, Any], mappings: WorkflowMappings, object_info: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    occupied: dict[tuple[str, str], str] = {}
    expected_types = {
        "positive_prompt": {"STRING"}, "negative_prompt": {"STRING"},
        "seed": {"INT"}, "width": {"INT"}, "height": {"INT"}, "steps": {"INT"},
        "guidance": {"FLOAT", "INT"}, "checkpoint": {"STRING", "ENUM"},
    }
    if not graph:
        return ["Workflow graph is empty"]
    for name, mapping in mappings.model_dump().items():
        if mapping is None:
            continue
        node_id = mapping["node_id"]
        node = graph.get(node_id)
        if not isinstance(node, dict):
            errors.append(f"{name}: node '{node_id}' does not exist")
            continue
        if name == "image_output":
            if object_info is not None:
                metadata = object_info.get(node.get("class_type"))
                if metadata is None:
                    errors.append(f"{name}: unknown node type '{node.get('class_type', '')}'")
                elif metadata.get("output_node") is False:
                    errors.append(
                        f"{name}: node '{node_id}' is not a terminal output node; map SaveImage or another output node"
                    )
            continue
        input_name = mapping.get("input_name")
        if not input_name:
            errors.append(f"{name}: an input name is required")
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or input_name not in inputs:
            errors.append(f"{name}: input '{input_name}' is absent from node '{node_id}'")
        if object_info is not None:
            class_type = node.get("class_type")
            if class_type not in object_info:
                errors.append(f"{name}: unknown node type '{class_type or ''}'")
            else:
                definitions = object_info[class_type].get("input", {})
                specification = (definitions.get("required", {}) | definitions.get("optional", {})).get(input_name)
                if specification:
                    raw_type = specification[0] if isinstance(specification, list) else specification
                    actual_type = "ENUM" if isinstance(raw_type, list) else str(raw_type)
                    if actual_type not in expected_types.get(name, {actual_type}):
                        errors.append(f"{name}: input '{input_name}' is {actual_type}, expected {', '.join(sorted(expected_types[name]))}")
        slot = (node_id, str(input_name))
        if slot in occupied:
            errors.append(f"{name}: reuses node/input already mapped by {occupied[slot]}")
        else:
            occupied[slot] = name
    return errors


def inject_workflow(
    graph: dict[str, Any], mappings: WorkflowMappings, values: dict[str, Any]
) -> dict[str, Any]:
    errors = validate_workflow(graph, mappings)
    if errors:
        raise WorkflowValidationError("; ".join(errors))
    rendered = copy.deepcopy(graph)
    mapping_values = mappings.model_dump()
    for name, value in values.items():
        mapping = mapping_values.get(name)
        if mapping is None or value is None or name == "image_output":
            continue
        rendered[mapping["node_id"]]["inputs"][mapping["input_name"]] = value
    return rendered

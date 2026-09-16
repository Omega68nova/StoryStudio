import pytest

from app.schemas import WorkflowMappings
from app.services.workflow import WorkflowValidationError, inject_workflow, normalize_workflow_graph, prune_workflow_graph, validate_workflow


def mappings() -> WorkflowMappings:
    return WorkflowMappings.model_validate({
        "positive_prompt": {"node_id": "6", "input_name": "text"},
        "image_output": {"node_id": "9"},
        "seed": {"node_id": "3", "input_name": "seed"},
    })


def test_injection_clones_graph() -> None:
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
    }
    rendered = inject_workflow(graph, mappings(), {"positive_prompt": "new", "seed": 42})
    assert rendered["6"]["inputs"]["text"] == "new"
    assert rendered["3"]["inputs"]["seed"] == 42
    assert graph["6"]["inputs"]["text"] == "old"


def test_missing_mapped_input_is_actionable() -> None:
    graph = {"6": {"class_type": "CLIPTextEncode", "inputs": {}}, "9": {"class_type": "SaveImage", "inputs": {}}}
    errors = validate_workflow(graph, mappings())
    assert any("input 'text'" in error for error in errors)
    with pytest.raises(WorkflowValidationError):
        inject_workflow(graph, mappings(), {"positive_prompt": "new"})


def test_ui_workflow_conversion_and_output_pruning() -> None:
    source = {
        "nodes": [
            {"id": 6, "type": "Text", "mode": 0, "inputs": [], "outputs": [{"name": "STRING", "type": "STRING", "links": [1]}], "widgets_values": ["old"]},
            {"id": 3, "type": "Sampler", "mode": 0, "inputs": [{"name": "prompt", "type": "STRING", "link": 1}], "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}], "widgets_values": [7]},
            {"id": 9, "type": "SaveImage", "mode": 0, "inputs": [{"name": "images", "type": "IMAGE", "link": 2}], "outputs": [], "widgets_values": ["output"]},
            {"id": 10, "type": "SaveImage", "mode": 0, "inputs": [], "outputs": [], "widgets_values": ["unrelated"]},
        ],
        "links": [[1, 6, 0, 3, 0, "STRING"], [2, 3, 0, 9, 0, "IMAGE"]],
    }
    info = {
        "Text": {"input": {"required": {"text": ["STRING", {}]}}},
        "Sampler": {"input": {"required": {"prompt": ["STRING"], "seed": ["INT", {}]}}},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}}},
    }
    graph, source_format = normalize_workflow_graph(source, info)
    graph = prune_workflow_graph(graph, "9")
    assert source_format == "ui" and set(graph) == {"3", "6", "9"}
    assert graph["6"]["inputs"]["text"] == "old"
    assert graph["3"]["inputs"]["prompt"] == ["6", 0]


def test_ui_workflow_needs_running_comfy_metadata() -> None:
    with pytest.raises(WorkflowValidationError, match="Start ComfyUI"):
        normalize_workflow_graph({"nodes": [], "links": []})


def test_mapping_types_and_collisions_are_rejected() -> None:
    graph = {
        "6": {"class_type": "Text", "inputs": {"text": "old"}},
        "3": {"class_type": "Sampler", "inputs": {"seed": 1, "cfg": 1.0}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
    }
    info = {
        "Text": {"input": {"required": {"text": ["STRING", {}]}}},
        "Sampler": {"input": {"required": {"seed": ["INT", {}], "cfg": ["FLOAT", {}]}}},
        "SaveImage": {"output_node": True, "input": {"required": {"images": ["IMAGE", {}]}}},
    }
    invalid = WorkflowMappings.model_validate({
        "positive_prompt": {"node_id": "6", "input_name": "text"},
        "negative_prompt": {"node_id": "6", "input_name": "text"},
        "width": {"node_id": "3", "input_name": "cfg"},
        "image_output": {"node_id": "9"},
    })
    errors = validate_workflow(graph, invalid, info)
    assert any("reuses node/input" in error for error in errors)
    assert any("width" in error and "FLOAT" in error for error in errors)


def test_cfg_mapping_accepts_float_and_terminal_output() -> None:
    graph = {
        "6": {"class_type": "Text", "inputs": {"text": "old"}},
        "3": {"class_type": "Sampler", "inputs": {"cfg": 1.0}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
    }
    info = {
        "Text": {"input": {"required": {"text": ["STRING", {}]}}},
        "Sampler": {"input": {"required": {"cfg": ["FLOAT", {}]}}},
        "SaveImage": {"output_node": True, "input": {"required": {"images": ["IMAGE", {}]}}},
    }
    configured = WorkflowMappings.model_validate({
        "positive_prompt": {"node_id": "6", "input_name": "text"},
        "guidance": {"node_id": "3", "input_name": "cfg"},
        "image_output": {"node_id": "9"},
    })
    assert validate_workflow(graph, configured, info) == []

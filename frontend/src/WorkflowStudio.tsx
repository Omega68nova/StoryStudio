import { useEffect, useMemo, useState } from "react";
import { Button, IconButton, MenuItem, TextField, Tooltip } from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import VerifiedOutlinedIcon from "@mui/icons-material/VerifiedOutlined";
import { api } from "./api";
import type { WorkflowMappings, WorkflowPreset } from "./types";

export function WorkflowStudio({
  workflows,
  reload,
  fail,
}: {
  workflows: WorkflowPreset[];
  reload: () => Promise<void>;
  fail: (message: string) => void;
}) {
  const [graph, setGraph] = useState<Record<string, unknown> | null>(null);
  const [metadata, setMetadata] = useState<Record<string, any>>({});
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [mappings, setMappings] = useState<
    Record<string, { node_id: string; input_name: string }>
  >({
    positive_prompt: { node_id: "", input_name: "" },
    image_output: { node_id: "", input_name: "" },
    transparent_image_output: { node_id: "", input_name: "" },
  });
  const fields = [
    "positive_prompt",
    "image_output",
    "transparent_image_output",
    "negative_prompt",
    "seed",
    "width",
    "height",
    "steps",
    "guidance",
    "checkpoint",
  ];
  useEffect(() => {
    if (!graph) return;
    api<Record<string, any>>("/workflows/metadata")
      .then(setMetadata)
      .catch(() => setMetadata({}));
  }, [graph]);
  async function readFile(file: File) {
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, any>;
      setGraph(parsed);
      setName(file.name.replace(/\.json$/i, ""));
      setEditingId(null);
      if (Array.isArray(parsed.nodes)) {
        const nodes = parsed.nodes as Array<Record<string, any>>;
        const byTitle = (pattern: RegExp) =>
          nodes.find((node) =>
            pattern.test(String(node.title ?? node.type ?? "")),
          );
        const withInput = (name: string) =>
          nodes.find(
            (node) =>
              Array.isArray(node.inputs) &&
              node.inputs.some(
                (input: Record<string, unknown>) => input.name === name,
              ),
          );
        const outputs = nodes
          .filter((node) => node.type === "SaveImage")
          .sort((a, b) => Number(b.id) - Number(a.id));
        const positive = byTitle(/(^|\b)(posi|positive)(\b|$)/i),
          negative = byTitle(/(^|\b)(nega|negative)(\b|$)/i);
        const seed = withInput("seed"),
          dimensions = withInput("width");
        setMappings({
          positive_prompt: {
            node_id: String(positive?.id ?? ""),
            input_name: "text",
          },
          image_output: {
            node_id: String(outputs[0]?.id ?? ""),
            input_name: "",
          },
          transparent_image_output: {
            node_id: "",
            input_name: "",
          },
          negative_prompt: {
            node_id: String(negative?.id ?? ""),
            input_name: "text",
          },
          seed: { node_id: String(seed?.id ?? ""), input_name: "seed" },
          width: { node_id: String(dimensions?.id ?? ""), input_name: "width" },
          height: {
            node_id: String(dimensions?.id ?? ""),
            input_name: "height",
          },
          steps: {
            node_id: String(withInput("steps")?.id ?? ""),
            input_name: "steps",
          },
          guidance: {
            node_id: String(withInput("cfg")?.id ?? ""),
            input_name: "cfg",
          },
          checkpoint: {
            node_id: String(withInput("ckpt_name")?.id ?? ""),
            input_name: "ckpt_name",
          },
        });
      }
    } catch {
      fail("That file is not valid JSON.");
    }
  }
  async function save() {
    if (!graph) return;
    const compact = Object.fromEntries(
      Object.entries(mappings)
        .filter(([, value]) => value.node_id)
        .map(([key, value]) => [
          key,
          ["image_output", "transparent_image_output"].includes(key)
            ? { node_id: value.node_id }
            : value,
        ]),
    ) as WorkflowMappings;
    try {
      await api(editingId ? `/workflows/${editingId}` : "/workflows", {
        method: editingId ? "PUT" : "POST",
        body: JSON.stringify({ name, graph, mappings: compact }),
      });
      setGraph(null);
      setEditingId(null);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  function editPreset(workflow: WorkflowPreset) {
    setEditingId(workflow.id);
    setName(workflow.name);
    setGraph(workflow.source_graph ?? workflow.graph);
    setMappings(
      Object.fromEntries(
        fields.map((field) => {
          const value = workflow.mappings[field as keyof WorkflowMappings];
          return [
            field,
            {
              node_id: value?.node_id ?? "",
              input_name: value?.input_name ?? "",
            },
          ];
        }),
      ),
    );
  }
  const uiFormat = Array.isArray(
    (graph as Record<string, unknown> | null)?.nodes,
  );
  const nodeCount = uiFormat
    ? ((graph as Record<string, any>).nodes as unknown[]).length
    : Object.keys(graph ?? {}).length;
  type MappingChoice = {
    value: string;
    nodeId: string;
    inputName: string;
    label: string;
    type: string;
  };
  const mappingChoices = useMemo(() => {
    const choices: MappingChoice[] = [];
    if (!graph) return choices;
    const sourceNodes: Array<Record<string, any>> = uiFormat
      ? ((graph as Record<string, any>).nodes ?? [])
      : Object.entries(graph).map(([id, node]) => ({
          id,
          ...(node as Record<string, any>),
        }));
    for (const node of sourceNodes) {
      const nodeId = String(node.id);
      const className = String(node.type ?? node.class_type ?? "Unknown");
      const title = String(
        node.title ??
          node._meta?.title ??
          metadata[className]?.display_name ??
          className,
      );
      const definitions = metadata[className]?.input ?? {};
      const metadataInputs = Object.entries({
        ...(definitions.required ?? {}),
        ...(definitions.optional ?? {}),
      }).map(([inputName, definition]) => {
        const rawType = Array.isArray(definition) ? definition[0] : definition;
        return {
          name: inputName,
          type: Array.isArray(rawType) ? "ENUM" : String(rawType ?? "UNKNOWN"),
        };
      });
      const uiInputs = Array.isArray(node.inputs)
        ? node.inputs.map((input: Record<string, any>) => ({
            name: String(input.name ?? ""),
            type: String(input.type ?? "UNKNOWN"),
          }))
        : [];
      const apiInputs =
        !uiFormat && node.inputs && typeof node.inputs === "object"
          ? Object.keys(node.inputs).map((inputName) => ({
              name: inputName,
              type: "UNKNOWN",
            }))
          : [];
      const inputs = metadataInputs.length
        ? metadataInputs
        : uiInputs.length
          ? uiInputs
          : apiInputs;
      for (const input of inputs)
        choices.push({
          value: `${nodeId}\u001f${input.name}`,
          nodeId,
          inputName: input.name,
          type: input.type.toUpperCase(),
          label: `${nodeId} · ${title} · ${className} · ${input.name} (${input.type})`,
        });
      if (
        metadata[className]?.output_node === true ||
        /saveimage|previewimage|output/i.test(className)
      )
        choices.push({
          value: nodeId,
          nodeId,
          inputName: "",
          type: "OUTPUT",
          label: `${nodeId} · ${title} · ${className} (terminal output)`,
        });
    }
    return choices;
  }, [graph, metadata, uiFormat]);
  function compatible(field: string, choice: MappingChoice) {
    if (["image_output", "transparent_image_output"].includes(field))
      return choice.type === "OUTPUT";
    if (choice.type === "OUTPUT") return false;
    if (["positive_prompt", "negative_prompt"].includes(field))
      return ["STRING", "UNKNOWN"].includes(choice.type);
    if (["seed", "width", "height", "steps"].includes(field))
      return ["INT", "INTEGER", "UNKNOWN"].includes(choice.type);
    if (field === "guidance")
      return ["FLOAT", "INT", "INTEGER", "NUMBER", "UNKNOWN"].includes(
        choice.type,
      );
    if (field === "checkpoint")
      return ["STRING", "ENUM", "UNKNOWN"].includes(choice.type);
    return true;
  }
  function mappingValue(field: string) {
    const value = mappings[field];
    return !value?.node_id
      ? ""
      : ["image_output", "transparent_image_output"].includes(field)
        ? value.node_id
        : `${value.node_id}\u001f${value.input_name ?? ""}`;
  }
  function selectMapping(field: string, value: string) {
    if (!value) {
      setMappings({ ...mappings, [field]: { node_id: "", input_name: "" } });
      return;
    }
    const [node_id, input_name = ""] = value.split("\u001f");
    setMappings({ ...mappings, [field]: { node_id, input_name } });
  }
  return (
    <div className="page">
      <header className="page-header">
        <p className="eyebrow">IMAGE PIPELINE</p>
        <h1>ComfyUI workflows</h1>
        <p>
          Import API-format or editable UI-format JSON, then confirm the field
          mappings.
        </p>
      </header>
      <div className="workflow-grid">
        <section className="panel">
          <h2>Imported presets</h2>
          {!workflows.length && <p className="muted">No workflows yet.</p>}
          {workflows.map((workflow) => (
            <article className="workflow-row" key={workflow.id}>
              <div>
                <strong>{workflow.name}</strong>
                <small className={workflow.validation_status}>
                  {workflow.validation_status}
                </small>
              </div>
              <span className="row-actions">
                <Tooltip title="Edit workflow">
                  <IconButton
                    aria-label={`Edit ${workflow.name}`}
                    onClick={() => editPreset(workflow)}
                  >
                    <EditOutlinedIcon />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Validate workflow">
                  <IconButton
                    aria-label={`Validate ${workflow.name}`}
                    onClick={async () => {
                      try {
                        await api(`/workflows/${workflow.id}/validate`, {
                          method: "POST",
                        });
                        await reload();
                      } catch (cause) {
                        fail(errorMessage(cause));
                      }
                    }}
                  >
                    <VerifiedOutlinedIcon />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Delete workflow">
                  <IconButton
                    aria-label={`Delete ${workflow.name}`}
                    color="error"
                    onClick={async () => {
                      try {
                        await api(`/workflows/${workflow.id}`, {
                          method: "DELETE",
                        });
                        await reload();
                      } catch (cause) {
                        fail(errorMessage(cause));
                      }
                    }}
                  >
                    <DeleteOutlineIcon />
                  </IconButton>
                </Tooltip>
              </span>
            </article>
          ))}
        </section>
        <section className="panel import-panel">
          <h2>{editingId ? "Edit workflow preset" : "Import workflow JSON"}</h2>
          <input
            type="file"
            accept="application/json,.json"
            onChange={(e) =>
              e.target.files?.[0] && void readFile(e.target.files[0])
            }
          />
          {graph && (
            <div className="mapping-form">
              <TextField
                size="small"
                label="Preset name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <p>
                {nodeCount} nodes found ·{" "}
                {uiFormat
                  ? "UI format; conversion uses the running ComfyUI node metadata"
                  : "API format"}
              </p>
              <p className="mapping-help">
                Image output is the normal terminal SaveImage/output node.
                Transparent image output is optional and should point to the
                terminal node whose image already has its background removed.
                ComfyUI history uses its node ID; no output socket number is needed.
              </p>
              {fields.map((field) => {
                const choices = mappingChoices.filter((choice) =>
                  compatible(field, choice),
                );
                const selected = mappingValue(field);
                const known =
                  !selected ||
                  choices.some((choice) => choice.value === selected);
                return (
                  <TextField
                    key={field}
                    select
                    size="small"
                    fullWidth
                    required={["positive_prompt", "image_output"].includes(
                      field,
                    )}
                    label={field === "guidance" ? "CFG scale" : humanize(field)}
                    value={selected}
                    onChange={(e) => selectMapping(field, e.target.value)}
                    helperText={
                      field === "guidance"
                        ? "Controls prompt influence. Leave unmapped to retain the workflow default (often 1 for turbo models)."
                        : undefined
                    }
                  >
                    <MenuItem value="">
                      <em>Not mapped</em>
                    </MenuItem>
                    {!known && (
                      <MenuItem value={selected}>
                        {mappings[field].node_id} ·{" "}
                        {mappings[field].input_name || "terminal output"} (saved
                        mapping)
                      </MenuItem>
                    )}
                    {choices.map((choice) => (
                      <MenuItem
                        key={`${field}-${choice.value}`}
                        value={choice.value}
                      >
                        {choice.label}
                      </MenuItem>
                    ))}
                  </TextField>
                );
              })}
              <details>
                <summary>Injected workflow preview</summary>
                <pre>
                  {JSON.stringify(
                    Object.fromEntries(
                      Object.entries(mappings).filter(
                        ([, value]) => value.node_id,
                      ),
                    ),
                    null,
                    2,
                  )}
                </pre>
              </details>
              <div className="button-row">
                {editingId && (
                  <Button
                    onClick={() => {
                      setGraph(null);
                      setEditingId(null);
                    }}
                  >
                    Cancel
                  </Button>
                )}
                <Button
                  variant="contained"
                  disabled={
                    !name ||
                    !mappings.positive_prompt?.node_id ||
                    !mappings.image_output?.node_id
                  }
                  onClick={save}
                >
                  {editingId
                    ? "Update workflow preset"
                    : "Save workflow preset"}
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}


function humanize(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function errorMessage(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}


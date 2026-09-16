import type { StoryNode } from "./types";

export function storyPath(nodes: StoryNode[], leafId: string | null): StoryNode[] {
  if (!leafId) return [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const path: StoryNode[] = [];
  const seen = new Set<string>();
  let current = byId.get(leafId);
  while (current && !seen.has(current.id)) {
    path.push(current);
    seen.add(current.id);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return path.reverse();
}

export function newestLeaf(nodes: StoryNode[]): string | null {
  if (!nodes.length) return null;
  const parents = new Set(nodes.map((node) => node.parent_id).filter(Boolean));
  return [...nodes].reverse().find((node) => !parents.has(node.id))?.id ?? nodes.at(-1)!.id;
}

export function childCount(nodes: StoryNode[], nodeId: string): number {
  return nodes.filter((node) => node.parent_id === nodeId).length;
}


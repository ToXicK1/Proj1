import { Background, Controls, ReactFlow, type Connection, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { StageSpec } from "../api";
import { layout } from "./graph";

interface Props {
  stages: StageSpec[];
  selected: string | null;
  readOnly: boolean;
  onSelect: (id: string) => void;
  onConnect: (from: string, to: string) => void;
  onDisconnect: (from: string, to: string) => void;
}

export function WorkflowCanvas({ stages, selected, readOnly, onSelect, onConnect, onDisconnect }: Props) {
  const nodes = useMemo<Node[]>(() => {
    const places = new Map(layout(stages).map((p) => [p.id, p]));
    return stages.map((s) => ({
      id: s.id,
      position: { x: places.get(s.id)?.x ?? 0, y: places.get(s.id)?.y ?? 0 },
      data: { label: s.name || s.id },
      selected: s.id === selected,
      deletable: false,
      sourcePosition: "right" as Node["sourcePosition"],
      targetPosition: "left" as Node["targetPosition"],
    }));
  }, [stages, selected]);
  const edges = useMemo<Edge[]>(() => {
    const ids = new Set(stages.map((s) => s.id));
    return stages.flatMap((s) => (s.depends_on ?? []).filter((d) => ids.has(d)).map((d) => ({
      id: `${d}->${s.id}`,
      source: d,
      target: s.id,
    })));
  }, [stages]);

  return (
    <>
    {!readOnly && <p className="muted">Drag from one stage to another to link them. Click a line to remove it.</p>}
    <div className="canvas" role="group" aria-label="Workflow diagram">
      <ReactFlow
        key={nodes.map((n) => `${n.id}:${n.position.x}:${n.position.y}`).join("|")} // refit when the shape changes
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
        colorMode="system"
        nodesDraggable={false}
        nodesConnectable={!readOnly}
        edgesReconnectable={false}
        deleteKeyCode={null}
        onNodeClick={(_, node) => onSelect(node.id)}
        onConnect={(c: Connection) => c.source && c.target && onConnect(c.source, c.target)}
        onEdgeClick={(_, edge) => { if (!readOnly) onDisconnect(edge.source, edge.target); }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
    </>
  );
}

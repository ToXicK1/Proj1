import {
  Background, Controls, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges,
  type Connection, type Edge, type EdgeChange, type Node, type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useState } from "react";

/** A process-flow diagram: steps, decisions, start and end, connected by labelled arrows. The editable definition
 * (nodes with positions, edges) is what gets saved as the record's new version, never a picture. */
export interface FlowDefinition {
  nodes: { id: string; type: "start" | "task" | "decision" | "end"; label: string; x: number; y: number }[];
  edges: { id: string; from: string; to: string; label: string }[];
}

const SHAPES: Record<FlowDefinition["nodes"][number]["type"], string> = {
  start: "Start", task: "Step", decision: "Decision", end: "End",
};

export function asFlow(value: unknown): FlowDefinition {
  const v = (value ?? {}) as Partial<FlowDefinition>;
  return {
    nodes: Array.isArray(v.nodes) ? v.nodes.filter((n) => n && typeof n.id === "string") : [],
    edges: Array.isArray(v.edges) ? v.edges.filter((e) => e && typeof e.from === "string" && typeof e.to === "string") : [],
  };
}

const toNodes = (flow: FlowDefinition): Node[] => flow.nodes.map((n) => ({
  id: n.id, position: { x: n.x, y: n.y }, data: { label: n.label, kind: n.type },
  className: `flow-node flow-${n.type}`,
}));
const toEdges = (flow: FlowDefinition): Edge[] => flow.edges.map((e) => ({
  id: e.id, source: e.from, target: e.to, label: e.label || undefined,
}));

export function FlowEditor({ value, onChange, readOnly = false }: {
  value: unknown; onChange?: (flow: FlowDefinition) => void; readOnly?: boolean;
}) {
  const initial = asFlow(value);
  const [nodes, setNodes] = useState<Node[]>(toNodes(initial));
  const [edges, setEdges] = useState<Edge[]>(toEdges(initial));
  const [kind, setKind] = useState<FlowDefinition["nodes"][number]["type"]>("task");
  const [label, setLabel] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const emit = (ns: Node[], es: Edge[]) => onChange?.({
    nodes: ns.map((n) => ({ id: n.id, type: (n.data as { kind: FlowDefinition["nodes"][number]["type"] }).kind,
      label: String((n.data as { label: string }).label), x: Math.round(n.position.x), y: Math.round(n.position.y) })),
    edges: es.map((e) => ({ id: e.id, from: e.source, to: e.target, label: typeof e.label === "string" ? e.label : "" })),
  });

  return (
    <div className="stack-sm">
      {!readOnly && (
        <div className="actions" aria-label="Diagram tools">
          <label>Shape<select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            {Object.entries(SHAPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="grow">Label<input value={label} onChange={(e) => setLabel(e.target.value)} /></label>
          <button type="button" disabled={!label.trim()} onClick={() => {
            const id = `n${Date.now().toString(36)}`;
            const next = [...nodes, { id, position: { x: 40 + nodes.length * 30, y: 40 + nodes.length * 40 },
              data: { label: label.trim(), kind }, className: `flow-node flow-${kind}` }];
            setNodes(next);
            setLabel("");
            emit(next, edges);
          }}>Add {SHAPES[kind].toLowerCase()}</button>
          <button type="button" className="secondary" disabled={!selected} onClick={() => {
            const ns = nodes.filter((n) => n.id !== selected);
            const es = edges.filter((e) => e.id !== selected && e.source !== selected && e.target !== selected);
            setNodes(ns); setEdges(es); setSelected(null); emit(ns, es);
          }}>Remove selected</button>
        </div>
      )}
      <div className="flow-canvas" role="img" aria-label={`Process diagram with ${nodes.length} shapes and ${edges.length} arrows`}>
        <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={!readOnly} nodesConnectable={!readOnly}
          elementsSelectable={!readOnly}
          onNodesChange={(changes: NodeChange[]) => {
            const next = applyNodeChanges(changes, nodes);
            setNodes(next);
            if (changes.some((c) => c.type === "position" && !c.dragging)) emit(next, edges);
          }}
          onEdgesChange={(changes: EdgeChange[]) => { const next = applyEdgeChanges(changes, edges); setEdges(next); emit(nodes, next); }}
          onConnect={(c: Connection) => {
            const tag = window.prompt("Label for this arrow (optional, for example Yes or No)") ?? "";
            const next = addEdge({ ...c, id: `e${Date.now().toString(36)}`, label: tag || undefined }, edges);
            setEdges(next);
            emit(nodes, next);
          }}
          onSelectionChange={({ nodes: ns, edges: es }) => setSelected(ns[0]?.id ?? es[0]?.id ?? null)}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <details className="small"><summary>Read the diagram as text</summary>
        <ol>{nodes.map((n) => (
          <li key={n.id}>{SHAPES[(n.data as { kind: keyof typeof SHAPES }).kind]}: {String((n.data as { label: string }).label)}
            {edges.filter((e) => e.source === n.id).map((e) => ` → ${String(nodes.find((x) => x.id === e.target)?.data.label ?? "?")}${e.label ? ` (${String(e.label)})` : ""}`).join("")}
          </li>
        ))}</ol>
      </details>
    </div>
  );
}

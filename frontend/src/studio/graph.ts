import type { StageSpec, WorkflowSpecDto } from "../api";

export interface Placed {
  id: string;
  x: number;
  y: number;
}

/** Columns follow dependency depth. Positions are derived, so they are never stored in the workflow. */
export function layout(stages: StageSpec[]): Placed[] {
  const byId = new Map(stages.map((s) => [s.id, s]));
  const depth = new Map<string, number>();
  const visit = (id: string, path: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (path.has(id)) return 0; // a cycle is reported by validation; it must not hang the drawing
    const next = new Set(path).add(id);
    const deps = (byId.get(id)?.depends_on ?? []).filter((d) => byId.has(d));
    const value = deps.length ? Math.max(...deps.map((d) => visit(d, next))) + 1 : 0;
    depth.set(id, value);
    return value;
  };
  const rows = new Map<number, number>();
  return stages.map((stage) => {
    const column = visit(stage.id, new Set());
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    return { id: stage.id, x: column * 230, y: row * 90 };
  });
}

function withStages(spec: WorkflowSpecDto, stages: StageSpec[]): WorkflowSpecDto {
  return { ...spec, stages };
}

export function addDependency(spec: WorkflowSpecDto, from: string, to: string): WorkflowSpecDto {
  if (from === to) return spec;
  return withStages(spec, spec.stages.map((s) =>
    s.id === to && !(s.depends_on ?? []).includes(from) ? { ...s, depends_on: [...(s.depends_on ?? []), from] } : s));
}

export function removeDependency(spec: WorkflowSpecDto, from: string, to: string): WorkflowSpecDto {
  return withStages(spec, spec.stages.map((s) =>
    s.id === to ? { ...s, depends_on: (s.depends_on ?? []).filter((d) => d !== from) } : s));
}

export function renameStage(spec: WorkflowSpecDto, from: string, to: string): WorkflowSpecDto {
  return withStages(spec, spec.stages.map((s) => ({
    ...s,
    id: s.id === from ? to : s.id,
    depends_on: (s.depends_on ?? []).map((d) => (d === from ? to : d)),
  })));
}

export function removeStage(spec: WorkflowSpecDto, id: string): WorkflowSpecDto {
  return withStages(spec, spec.stages.filter((s) => s.id !== id).map((s) => ({
    ...s,
    depends_on: (s.depends_on ?? []).filter((d) => d !== id),
  })));
}

export function nextStageId(spec: WorkflowSpecDto): string {
  let n = spec.stages.length + 1;
  while (spec.stages.some((s) => s.id === `stage_${n}`)) n += 1;
  return `stage_${n}`;
}

export interface PolicyDraft {
  type: string;
  roles: string[];
  minApprovers: number;
}

export function readPolicy(raw: Record<string, unknown> | null | undefined): PolicyDraft {
  if (!raw) return { type: "single", roles: ["project_owner"], minApprovers: 1 };
  const steps = (raw.steps as { role: string }[] | undefined)?.map((s) => s.role);
  const roles = steps ?? (raw.roles as string[] | undefined) ?? (raw.role ? [raw.role as string] : []);
  return { type: String(raw.type), roles, minApprovers: Number(raw.min_approvers ?? 1) };
}

export function writePolicy(p: PolicyDraft): Record<string, unknown> {
  if (p.type === "single") return { type: "single", role: p.roles[0] ?? "project_owner" };
  if (p.type === "role_based") return { type: p.type, roles: p.roles, min_approvers: p.minApprovers };
  if (p.type === "sequential") return { type: p.type, steps: p.roles.map((role) => ({ role })) };
  return { type: p.type, roles: p.roles };
}

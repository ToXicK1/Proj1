import { request } from "../api";

export type Provenance = "confirmed" | "assumption" | "ai_suggestion" | "open_question";

export interface KindFieldDto { name: string; type: "text" | "enum" | "list" | "int" | "json"; required: boolean; choices: string[] }
export interface KindDto { key: string; department: string; prefix: string; label: string; fields: KindFieldDto[] }

export interface VersionDto {
  id: string; number: number; title: string; body: Record<string, unknown>; provenance: Provenance; sha256: string;
  author_type: "human" | "ai"; author: string | null; reason: string; sources: unknown[]; created_at: string;
}
export interface LinkDto {
  id: string; type: string; direction: "in" | "out";
  item: { id: string; key: string; title: string; kind: string; department: string };
}
export interface CommentDto {
  id: string; version: number; anchor: Record<string, unknown> | null; body: string; author_type: "human" | "ai";
  author: string; resolved: boolean; created_at: string;
}
export interface ItemDto {
  id: string; key: string; kind: string; department: string; title: string; status: string; provenance: Provenance;
  version: number; latest_version: number; body: Record<string, unknown>; updated_at: string;
  versions?: VersionDto[]; links?: LinkDto[]; comments?: CommentDto[]; can_edit?: boolean; view?: "approved";
}
export interface PackageDto {
  id: string; department: string; number: number; title: string; status: string; sha256: string; note: string;
  items: { item_id: string; key: string; kind: string; title: string; version_id: string; number: number; sha256: string }[];
  submitted_by: string | null; submitted_at: string; decided_by: string | null; decided_at: string | null;
  decision_note: string;
  /** The lifecycle step this package is the deliverable of, if any: deciding it decides the step. */
  step: string | null;
  /** RD-19: the submitter changed content in it, so another professional of the department must approve. */
  edited_by_submitter: boolean;
}
export interface HandoffDto {
  id: string; from: string; to: string; status: string; note: string; reply: string; sender: string | null;
  sent_at: string; replied_by: string | null; replied_at: string | null;
  package: { id: string; number: number; title: string; sha256: string; items: PackageDto["items"] };
}
export interface TeamCardDto {
  profile: string; title: string; people: string[]; ai_lead: string | null; visible: boolean; can_edit: boolean;
  work: { records: number; approved: number; draft: number; in_review: number; to_confirm: number;
    incoming_handoffs: number; packages_awaiting_decision: number };
  started?: boolean; steps?: number; steps_done?: number; awaiting_approval?: number;
  current?: { name: string; status: string; note: string | null } | null;
  issues?: { stage: string; kind: string; text: string }[];
}

const base = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/work`;
const id = encodeURIComponent;

export const workApi = {
  kinds: (p: string) => request<{ items: KindDto[] }>("GET", `${base(p)}/kinds`),
  team: (p: string) => request<{ departments: TeamCardDto[]; kind: string }>("GET", `${base(p)}/team`),
  items: (p: string, department: string, query: Record<string, string>) => {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== "")).toString();
    return request<{ items: ItemDto[]; can_edit: boolean; view: string }>(
      "GET", `${base(p)}/${id(department)}/items${qs ? `?${qs}` : ""}`);
  },
  item: (p: string, itemId: string) => request<ItemDto>("GET", `${base(p)}/items/${id(itemId)}`),
  create: (p: string, department: string, body: { kind: string; title: string; body: Record<string, unknown>;
    provenance: Exclude<Provenance, "ai_suggestion">; reason?: string }) =>
    request<ItemDto>("POST", `${base(p)}/${id(department)}/items`, body),
  edit: (p: string, itemId: string, body: { expected_version: number; title?: string; body?: Record<string, unknown>;
    provenance?: Exclude<Provenance, "ai_suggestion">; reason?: string }) =>
    request<ItemDto>("PUT", `${base(p)}/items/${id(itemId)}`, body),
  archive: (p: string, itemId: string, archived: boolean, reason = "") =>
    request<ItemDto>("POST", `${base(p)}/items/${id(itemId)}/archive`, { archived, reason }),
  compare: (p: string, itemId: string, a: number, b: number) =>
    request<{ changes: { field: string; before: unknown; after: unknown }[] }>(
      "GET", `${base(p)}/items/${id(itemId)}/compare?a=${a}&b=${b}`),
  link: (p: string, itemId: string, to: string, type: string) =>
    request<{ links: LinkDto[] }>("POST", `${base(p)}/items/${id(itemId)}/links`, { to_item_id: to, link_type: type }),
  unlink: (p: string, linkId: string) => request("DELETE", `${base(p)}/links/${id(linkId)}`),
  comment: (p: string, itemId: string, body: string, version?: number, anchor?: Record<string, unknown>) =>
    request<{ items: CommentDto[] }>("POST", `${base(p)}/items/${id(itemId)}/comments`, { body, version, anchor }),
  resolve: (p: string, commentId: string) => request("POST", `${base(p)}/comments/${id(commentId)}/resolve`),
  traceability: (p: string) => request<{ items: { id: string; key: string; kind: string; department: string;
    title: string; status: string }[]; links: { from: string; to: string; type: string }[] }>(
    "GET", `${base(p)}/traceability`),
  packages: (p: string, department: string) =>
    request<{ items: PackageDto[] }>("GET", `${base(p)}/${id(department)}/packages`),
  submit: (p: string, department: string, title: string, itemIds: string[], note: string) =>
    request<PackageDto>("POST", `${base(p)}/${id(department)}/packages`, { title, item_ids: itemIds, note }),
  decide: (p: string, packageId: string, decision: "approve" | "request_changes", note: string) =>
    request<PackageDto>("POST", `${base(p)}/packages/${id(packageId)}/decision`, { decision, note }),
  handOff: (p: string, packageId: string, to: string, note: string) =>
    request<HandoffDto>("POST", `${base(p)}/packages/${id(packageId)}/handoffs`, { to_department: to, note }),
  handoffs: (p: string, department: string) =>
    request<{ items: HandoffDto[] }>("GET", `${base(p)}/${id(department)}/handoffs`),
  reply: (p: string, handoffId: string, action: "acknowledge" | "request_clarification", reply: string) =>
    request<HandoffDto>("POST", `${base(p)}/handoffs/${id(handoffId)}/reply`, { action, reply }),
};

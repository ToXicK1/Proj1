import { request, uploadFile } from "../api";

export interface AttachmentDto {
  id: string; filename: string; content_type: string; size_bytes: number; uploaded_by: string | null; created_at: string;
}

export type Provenance = "confirmed" | "assumption" | "ai_suggestion" | "open_question" | "system_draft";

export interface KindFieldDto { name: string; type: "text" | "enum" | "list" | "int" | "json"; required: boolean; choices: string[] }
export interface KindDto { key: string; department: string; prefix: string; label: string; fields: KindFieldDto[] }

export interface VersionDto {
  id: string; number: number; title: string; body: Record<string, unknown>; provenance: Provenance; sha256: string;
  author_type: "human" | "ai" | "system"; author: string | null; reason: string; sources: unknown[]; created_at: string;
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

export interface AssistantExchangeDto {
  id: string; department: string; asked_by: string | null; item: { id: string; key: string } | null; question: string;
  status: "pending" | "answered" | "failed"; answer: string; failure: string; created_at: string; answered_at: string | null;
  proposals: { kind: string; title: string; body: Record<string, unknown>; added: string | null }[];
}

export interface StepDto {
  key: string; name: string; status: string; kind: "records" | "review" | "owner_input" | "ai";
  failure_reason: string | null;
  records: { id: string; key: string; kind: string; title: string; provenance: Provenance; status: string; version: number }[];
  send_back_to: string[];
  owner: { asked: boolean; status: string | null; question: string | null; answer: string | null; answered: boolean } | null;
  change_requests: { comment: string; status: string; at: string }[];
}

const base = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/work`;
const id = encodeURIComponent;

/** P4: the Project Brief, its approved packages, and whether delivery has started from it. */
export interface BriefStatusDto {
  brief: ItemDto | null; edited_by_pm: boolean; intake_validated: boolean; kickoff_held: boolean; started: boolean;
  is_project_manager: boolean; is_admin: boolean; has_project_manager: boolean; kind_of_work: string | null;
  team_gaps: string[];
  approved_packages: { id: string; number: number; title: string; sha256: string; brief: PackageDto["items"][number];
    client_status: string | null; client_note: string }[];
}

/** The project kickoff: the checklist, the kickoff record, and the kind of work. */
export interface KickoffDto {
  checklist: { key: string; label: string; ok: boolean }[]; ready: boolean; kickoff: ItemDto | null;
  scope: string | null; scope_locked: boolean; scopes: { key: string; label: string }[]; can_edit: boolean;
}

/** The PM's Tasks page. */
export interface PmTasksDto {
  todos: { kind: string; text: string; module: string; urgent: boolean }[];
  departments: { started: boolean; attention: string[]; steps: { stage: string; number: string; name: string;
    department: string; department_title: string; status: string; raw_status: string; people: string[]; note: string | null }[] };
  assigned: { available: boolean; arrives_in: string };
}

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
    provenance: Exclude<Provenance, "ai_suggestion" | "system_draft">; reason?: string }) =>
    request<ItemDto>("POST", `${base(p)}/${id(department)}/items`, body),
  edit: (p: string, itemId: string, body: { expected_version: number; title?: string; body?: Record<string, unknown>;
    provenance?: Exclude<Provenance, "ai_suggestion" | "system_draft">; reason?: string }) =>
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
  submit: (p: string, department: string, title: string, itemIds: string[], note: string, stageKey?: string) =>
    request<PackageDto>("POST", `${base(p)}/${id(department)}/packages`,
      { title, item_ids: itemIds, note, stage_key: stageKey ?? null }),
  ask: (p: string, department: string, question: string, itemId: string | null) =>
    request<AssistantExchangeDto>("POST", `${base(p)}/${id(department)}/assistant`, { question, item_id: itemId }),
  assistantHistory: (p: string, department: string) =>
    request<{ items: AssistantExchangeDto[] }>("GET", `${base(p)}/${id(department)}/assistant`),
  addProposal: (p: string, exchangeId: string, index: number) =>
    request<AssistantExchangeDto>("POST", `${base(p)}/assistant/${id(exchangeId)}/proposals/${index}`),
  attachments: (p: string, itemId: string) =>
    request<{ items: AttachmentDto[] }>("GET", `${base(p)}/items/${id(itemId)}/attachments`),
  attach: (p: string, itemId: string, file: File) =>
    uploadFile<AttachmentDto>(`${base(p)}/items/${id(itemId)}/attachments?filename=${encodeURIComponent(file.name)}`, file),
  attachmentUrl: (p: string, attachmentId: string) => `${base(p)}/attachments/${id(attachmentId)}`,
  analyse: (p: string, meetingId: string) =>
    request<AssistantExchangeDto>("POST", `${base(p)}/items/${id(meetingId)}/analysis`),
  analyses: (p: string, meetingId: string) =>
    request<{ items: AssistantExchangeDto[] }>("GET", `${base(p)}/items/${id(meetingId)}/analysis`),
  clientForm: (p: string) =>
    request<{ answers: { field: string; label: string; value: string; tag: string | null }[]; status: string | null }>(
      "GET", `${base(p)}/client-form`),
  kickoff: (p: string) => request<KickoffDto>("GET", `${base(p)}/kickoff`),
  holdKickoff: (p: string, body: { held_at: string; attendees: string[]; agenda: string[]; notes: string; communication: string }) =>
    request<ItemDto>("POST", `${base(p)}/kickoff`, body),
  changeScope: (p: string, scope: string, reason: string) =>
    request<KickoffDto>("PUT", `${base(p)}/kickoff/scope`, { scope, reason }),
  pmTasks: (p: string) => request<PmTasksDto>("GET", `${base(p)}/pm/tasks`),
  brief: (p: string) => request<BriefStatusDto>("GET", `${base(p)}/brief`),
  assembleBrief: (p: string) => request<{ item: ItemDto; kept_pm_edits: boolean }>("POST", `${base(p)}/brief/assemble`),
  startFromBrief: (p: string, packageId: string, note: string, reason = "") =>
    request<{ started: boolean; handoff: HandoffDto }>("POST", `${base(p)}/brief/start`, { package_id: packageId, note, reason }),
  steps: (p: string, department: string) =>
    request<{ items: StepDto[]; can_edit: boolean }>("GET", `${base(p)}/${id(department)}/steps`),
  sendBack: (p: string, reviewKey: string, step: string, note: string) =>
    request("POST", `${base(p)}/steps/${id(reviewKey)}/send-back`, { step, note }),
  decide: (p: string, packageId: string, decision: "approve" | "request_changes", note: string) =>
    request<PackageDto>("POST", `${base(p)}/packages/${id(packageId)}/decision`, { decision, note }),
  handOff: (p: string, packageId: string, to: string, note: string) =>
    request<HandoffDto>("POST", `${base(p)}/packages/${id(packageId)}/handoffs`, { to_department: to, note }),
  handoffs: (p: string, department: string) =>
    request<{ items: HandoffDto[] }>("GET", `${base(p)}/${id(department)}/handoffs`),
  reply: (p: string, handoffId: string, action: "acknowledge" | "request_clarification", reply: string) =>
    request<HandoffDto>("POST", `${base(p)}/handoffs/${id(handoffId)}/reply`, { action, reply }),
};

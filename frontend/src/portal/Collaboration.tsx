import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api, type DepartmentStatusDto, type PersonDto, type ScopeDto, type TeamMessageDto, type TicketDto } from "../api";
import { PROFILES } from "./roles";
import { leadingTarget, mentionsIn, suggestions, type Who } from "./chatTargets";
import { Avatar, EmptyState, IdentityTag, Skeleton, StatusPill, When, type Tone } from "../components/ui";

function problem(err: unknown): string {
  return err instanceof ApiError ? err.message : "That did not work. Please try again.";
}

export const STEP_LABELS: Record<string, [string, Tone]> = {
  NOT_STARTED: ["Not started", "neutral"],
  READY: ["Starting", "progress"],
  RUNNING: ["AI working", "progress"],
  AI_COMPLETED: ["Checking", "progress"],
  VALIDATING: ["Checking", "progress"],
  AWAITING_HUMAN_REVIEW: ["Awaiting approval", "pending"],
  CHANGES_REQUESTED: ["Changes requested", "warning"],
  APPROVED: ["Approved", "success"],
  COMPLETED: ["Completed", "success"],
  BLOCKED: ["Blocked", "blocked"],
  FAILED: ["Stopped", "error"],
  REJECTED: ["Rejected", "error"],
};

/** What the department is doing right now, and exactly what is stuck and why. */
export function DepartmentStatus({ projectId, profile, tick }: { projectId: string; profile: string; tick: number }) {
  const [status, setStatus] = useState<DepartmentStatusDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.departmentStatus(projectId, profile).then(setStatus).catch((e: unknown) => setError(problem(e)));
  }, [projectId, profile, tick]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!status) return <Skeleton title={false} />;
  return (
    <section className="stack-sm" aria-label={`${status.title} status`}>
      <div className="row">
        <h2>What is happening</h2>
        <StatusPill label={status.issues.length ? `${status.issues.length} need attention` : "On track"}
          tone={status.issues.length ? "blocked" : "success"} />
      </div>
      <p className="muted">
        People: {status.people.length
          ? status.people.map((name) => <IdentityTag key={name} kind="human">{name}</IdentityTag>)
          : "nobody assigned yet"}
      </p>
      {status.issues.length > 0 && (
        <ul className="issues" aria-label="Issues">
          {status.issues.map((issue) => <li key={`${issue.stage}-${issue.kind}`} className={`issue issue-${issue.kind}`}>{issue.text}</li>)}
        </ul>
      )}
      {!status.started && <p className="muted">{status.summary}</p>}
      <ul className="list">
        {status.steps.map((step) => {
          const [label, tone] = STEP_LABELS[step.status] ?? [step.status, "neutral"];
          return (
            <li key={step.stage} className="stack-sm">
              <div className="row">
                <span><strong>{step.number} {step.name}</strong></span>
                <span className="actions">
                  {step.status === "RUNNING" && <IdentityTag kind="ai">working</IdentityTag>}
                  {step.slow && <StatusPill label="Slower than usual" tone="warning" />}
                  <StatusPill label={label} tone={tone} />
                </span>
              </div>
              {step.note && <span className="muted">{step.note}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export interface ChatSource {
  channels: { key: string; name: string }[];
  /** "mentions": @name notifies people in a shared discussion. "direct": @name switches to a private chat. */
  mode: "mentions" | "direct";
  load: (channel: string) => Promise<{ items: TeamMessageDto[] }>;
  post: (channel: string, body: string, opts: { mentions?: string[]; to?: string | null }) => Promise<unknown>;
  people: () => Promise<{ items: PersonDto[] }>;
}

/** The project's department discussion, shown inside a workspace. */
export function projectChat(projectId: string, scope: ScopeDto): ChatSource {
  return {
    channels: scope.channels,
    mode: "mentions",
    load: (channel) => api.teamChat(projectId, channel),
    post: (channel, body, opts) => api.postTeamMessage(projectId, channel, body, opts.mentions ?? []),
    people: () => api.projectPeople(projectId),
  };
}

/** Team chat and direct messages. With no channels (owners, administrators) only direct messages are possible. */
export const globalChat = (channels: { key: string; name: string }[]): ChatSource => ({
  channels,
  mode: "direct",
  load: (channel) => api.globalMessages(channel),
  post: (channel, body, opts) => api.postGlobalMessage(channel, body, opts.to ?? null),
  people: () => api.globalPeople(),
});

/** A conversation. Every message names who wrote it; direct messages say who they went to. */
export function TeamChat({ source, tick, initial, label = "Message the team" }: {
  source: ChatSource; tick: number; initial?: string; label?: string;
}) {
  const grouped = source.channels.length > 0;
  const [channel, setChannel] = useState(initial ?? source.channels[0]?.key ?? "direct");
  const [items, setItems] = useState<TeamMessageDto[] | null>(null);
  const [people, setPeople] = useState<PersonDto[] | null>(null);
  const [to, setTo] = useState<Who | null>(null); // stays on one person until @everyone or another @name
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { load: fetchMessages, post, people: fetchPeople, mode } = source;
  const load = useCallback(() => fetchMessages(channel).then((r) => setItems(r.items)), [fetchMessages, channel]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load, tick]);
  useEffect(() => { fetchPeople().then((r) => setPeople(r.items)).catch(() => setPeople([])); }, [fetchPeople]);
  const others: Who[] = (people ?? []).filter((p) => !p.is_you).map((p) => ({ user_id: p.user_id, name: p.name }));
  const channelName = source.channels.find((c) => c.key === channel)?.name ?? "";
  const hints = suggestions(body, others, mode === "direct" && grouped);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    const typed = body;
    const clear = () => setBody((now) => (now === typed ? "" : now)); // keep anything typed while sending
    let target = to;
    let text = body.trim();
    if (mode === "direct") {
      const lead = leadingTarget(body, others);
      if (!lead.target && body.trimStart().startsWith("@")) {
        // Never fall back to the whole channel for something meant for one person.
        setError(`Nobody you can message is called ${body.trim().split(/\s+/)[0]}. Pick a name from the suggestions.`);
        return;
      }
      if (lead.target === "everyone") {
        if (!grouped) { setError("There is no group chat for your role. Start with @name to message someone."); return; }
        target = null;
      } else if (lead.target) {
        target = lead.target;
      }
      text = lead.rest;
      setTo(target);
      if (!text) { clear(); return; } // only switched who the chat goes to
      if (!target && !grouped) { setError("Start with @name to choose who to message."); return; }
    }
    try {
      await post(channel, text, mode === "direct" ? { to: target?.user_id ?? null }
        : { mentions: mentionsIn(text, others).map((p) => p.user_id) });
      clear();
      await load();
    } catch (err) {
      setError(problem(err));
    }
  }

  const head = (m: TeamMessageDto) => {
    const author = `${m.author}${m.mine ? " (you)" : ""}`;
    if (!m.direct) return author;
    return m.mine ? `${author} → ${m.to}` : `${author} → you`;
  };

  const channelList = grouped && source.channels.length > 1 && !initial;
  return (
    <div className={channelList ? "chat chat-with-channels" : "chat"}>
      {channelList && (
        <div className="channel-list" role="tablist" aria-label="Chat channels" aria-orientation="vertical">
          {source.channels.map((c) => (
            <button key={c.key} type="button" role="tab" aria-selected={channel === c.key}
              className={channel === c.key ? "channel selected" : "channel"} onClick={() => setChannel(c.key)}>
              <span aria-hidden="true">#</span> {c.name}
            </button>
          ))}
        </div>
      )}
      <div className="chat-main">
        {items === null ? <Skeleton title={false} />
          : items.length === 0 && <EmptyState title="No messages yet.">Start the conversation.</EmptyState>}
        <ul className="messages" aria-label="Team messages">
          {items?.map((m) => (
            <li key={m.id} className={`message ${m.mine ? "mine" : ""} message-${m.author_type} ${m.mentions_me ? "mentions-me" : ""} ${m.direct ? "message-direct" : ""}`}>
              <Avatar name={m.author} kind={m.author_type} />
              <div className="message-content">
                <div className="message-head">
                  <strong className="message-author">{head(m)}</strong>
                  {m.author_type === "ai" && <IdentityTag kind="ai" />}
                  {m.direct && <StatusPill label="Direct" tone="info" />}
                  {!m.direct && m.mentions_me && <StatusPill label="Mentioned you" tone="info" />}
                  <When at={m.created_at} />
                  {m.direct && !m.mine && m.author_id && (
                    <button type="button" className="link-button" onClick={() => setTo({ user_id: m.author_id!, name: m.author })}>
                      Reply to {m.author}
                    </button>
                  )}
                </div>
                <div className="message-text">{m.body}</div>
                {m.mentions.length > 0 && <div className="muted small">{m.author} mentioned {m.mentions.map((n) => `@${n}`).join(", ")}</div>}
              </div>
            </li>
          ))}
        </ul>
        {error && <p role="alert" className="error">{error}</p>}
        <form className="composer" onSubmit={(e) => void send(e)}>
          {mode === "direct" && (
            <p className={to ? "chat-target private" : "chat-target"} aria-live="polite">
              {to ? <>To <strong>{to.name}</strong> (only the two of you see this)</>
                : grouped ? <>To <strong>everyone in {channelName}</strong></> : <>Choose who to message with @name</>}
              {to && grouped && <button type="button" className="link-button" onClick={() => setTo(null)}>Back to everyone</button>}
            </p>
          )}
          <label className="composer-field">
            <span className="composer-label">{label}</span>
            <textarea required rows={2} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)}
              placeholder={mode === "direct"
                ? (to ? `Message ${to.name}` : grouped ? `Message everyone in ${channelName}, or start with @name` : "Start with @name")
                : "Write a message"}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (body.trim() && people !== null) void send(); } }} />
          </label>
          {hints.length > 0 && (
            <div className="actions" role="group" aria-label="People you can name">
              {hints.map((h) => <button key={h.label} type="button" className="chip" onClick={() => setBody(h.insert)}>{h.label}</button>)}
            </div>
          )}
          <div className="composer-foot">
            <p className="hint">
              {mode === "direct"
                ? grouped ? "Type @name to talk to one person; it stays that way until you type @everyone or another @name."
                  : "Type @name to talk to one person; it stays that way until you name someone else."
                : "Type @name to notify someone. Enter sends; Shift+Enter starts a new line."}
            </p>
            <button type="submit" disabled={!body.trim() || people === null}>Send</button>
          </div>
        </form>
      </div>
    </div>
  );
}

const TICKET_TONES: Record<string, Tone> = {
  open: "progress", ai_resolved: "success", awaiting_professional: "pending", resolved: "success", closed: "neutral",
};
const TICKET_LABELS: Record<string, string> = {
  open: "AI checking", ai_resolved: "Answered by AI", awaiting_professional: "Waiting for a professional",
  resolved: "Resolved", closed: "Closed",
};

function TicketDetail({ projectId, ticket, onChange }: { projectId: string; ticket: TicketDto; onChange: () => void }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function run(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      setNote("");
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }
  const act = (action: string) => run(() => api.ticketAction(projectId, ticket.id, action, note));
  const open = ticket.status !== "resolved" && ticket.status !== "closed";
  return (
    <article className="stack-sm ticket-detail" aria-label={`Ticket ${ticket.number}`}>
      <div className="row">
        <h3>#{ticket.number} {ticket.title}</h3>
        <StatusPill label={TICKET_LABELS[ticket.status] ?? ticket.status} tone={TICKET_TONES[ticket.status]} />
      </div>
      <p className="muted">{ticket.kind} · {ticket.department}{ticket.assignee ? ` · assigned to ${ticket.assignee}` : ""} · raised by {ticket.raised_by}</p>
      <p>{ticket.body}</p>
      {ticket.ai_proposal && open && (
        <div className="notice proposal">
          <IdentityTag kind="ai">Proposal for your decision</IdentityTag>
          <p>{ticket.ai_proposal}</p>
        </div>
      )}
      <ul className="messages" aria-label="Ticket updates">
        {ticket.comments?.map((c, i) => (
          <li key={i} className={`message message-${c.author_type}`}>
            <div className="message-head"><IdentityTag kind={c.author_type}>{c.author}</IdentityTag></div>
            <div>{c.body}</div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="error">{error}</p>}
      <label>Add a note<textarea rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <div className="actions">
        <button type="button" className="secondary" disabled={!note.trim()}
          onClick={() => void run(() => api.ticketComment(projectId, ticket.id, note))}>Comment</button>
        {ticket.can_act && open && ticket.ai_proposal && (
          <button type="button" onClick={() => void act("approve_proposal")}>Approve proposal</button>
        )}
        {ticket.can_act && open && <button type="button" className="secondary" onClick={() => void act("resolve")}>Mark resolved</button>}
        {ticket.can_act && open && <button type="button" className="secondary" onClick={() => void act("close")}>Close</button>}
        {ticket.is_mine && ticket.status === "ai_resolved" && <button type="button" onClick={() => void act("accept")}>Accept answer</button>}
        {ticket.is_mine && (ticket.status === "ai_resolved" || ticket.status === "resolved") && (
          <button type="button" className="secondary" onClick={() => void act("reopen")}>Reopen</button>
        )}
      </div>
    </article>
  );
}

/** Tickets: anyone on the project raises one; the AI answers what it safely can; otherwise the professional decides. */
export function Tickets({ projectId, scope, tick, department }: {
  projectId: string; scope: ScopeDto; tick: number; department?: string;
}) {
  const [items, setItems] = useState<TicketDto[] | null>(null);
  const [selected, setSelected] = useState<TicketDto | null>(null);
  const [people, setPeople] = useState<PersonDto[]>([]);
  const [form, setForm] = useState({ title: "", body: "", kind: "question", profile: department ?? scope.profiles[0] ?? "business_analyst", assignee: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(async () => {
    const r = await api.tickets(projectId);
    setItems(department ? r.items.filter((t) => t.profile === department) : r.items);
  }, [projectId, department]);
  const openTicket = useCallback((id: string) => api.ticket(projectId, id).then(setSelected), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load, tick]);
  useEffect(() => { if (selected) void openTicket(selected.id).catch(() => undefined); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.projectPeople(projectId).then((r) => setPeople(r.items)).catch(() => setPeople([])); }, [projectId]);
  const departmentPeople = people.filter((p) => p.profiles.includes(form.profile));
  const targets = PROFILES.filter(([key]) => scope.kind === "owner" || scope.kind === "admin" || scope.kind === "manager" || scope.profiles.includes(key));

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const made = await api.createTicket(projectId, { ...form, assignee: form.assignee || null });
      setForm({ ...form, title: "", body: "", assignee: "" });
      setNotice(`Ticket #${made.number} raised. The AI team is checking it.`);
      await load();
      await openTicket(made.id);
    } catch (err) {
      setError(problem(err));
    }
  }

  const field = (name: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [name]: e.target.value });
  let list: ReactNode = <Skeleton title={false} />;
  if (items) {
    list = items.length === 0 ? <EmptyState title="No tickets yet.">Raise one when you have a question or something is wrong.</EmptyState> : (
      <ul className="list" aria-label="Tickets">
        {items.map((t) => (
          <li key={t.id} className="row">
            <button type="button" className="link-button" onClick={() => void openTicket(t.id)}>#{t.number} {t.title}</button>
            <span className="actions">
              <span className="muted">{t.department}</span>
              <StatusPill label={TICKET_LABELS[t.status] ?? t.status} tone={TICKET_TONES[t.status]} />
            </span>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="split">
      <div className="stack">
        {notice && <p role="status" className="notice">{notice}</p>}
        {error && <p role="alert" className="error">{error}</p>}
        {list}
        {selected && <TicketDetail projectId={projectId} ticket={selected} onChange={() => { void load(); void openTicket(selected.id); }} />}
      </div>
      <form className="stack-sm panel" onSubmit={(e) => void create(e)}>
        <h3>Raise a ticket</h3>
        <label>Title<input required minLength={3} maxLength={200} value={form.title} onChange={field("title")} /></label>
        <label>
          Type
          <select value={form.kind} onChange={field("kind")}>
            <option value="question">Question</option>
            <option value="change">Change request</option>
            <option value="defect">Something is wrong</option>
            <option value="other">Other</option>
          </select>
        </label>
        {!department && (
          <label>
            Department
            <select value={form.profile} onChange={(e) => setForm({ ...form, profile: e.target.value, assignee: "" })}>
              {targets.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
        )}
        <label>
          Notify
          <select value={form.assignee} onChange={field("assignee")}>
            <option value="">Everyone in the department</option>
            {departmentPeople.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
          </select>
        </label>
        <label>Details<textarea required rows={4} maxLength={4000} value={form.body} onChange={field("body")} /></label>
        <button type="submit" disabled={!form.title.trim() || !form.body.trim()}>Raise ticket</button>
      </form>
    </div>
  );
}

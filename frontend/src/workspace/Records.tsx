import { Suspense, lazy, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, IdentityTag, Skeleton, StatusPill } from "../components/ui";
import { PROVENANCE_LABEL, STATUS_LABEL } from "./modules";
import { SelectedRecord } from "./Assistant";
import { SectionsEditor, asSections, toMarkdown } from "./SectionsEditor";

const FlowEditor = lazy(() => import("./FlowEditor").then((m) => ({ default: m.FlowEditor })));
import { type ItemDto, type KindDto, type KindFieldDto, type Provenance, workApi } from "./workApi";

const problem = (e: unknown) =>
  e instanceof ApiError ? [e.message, ...(e.problems ?? [])].join(" ") : "That did not work. Please try again.";
const human = (s: string) => s.replace(/_/g, " ");

export function ProvenanceTag({ value }: { value: Provenance }) {
  const [label, tone] = PROVENANCE_LABEL[value] ?? [value, "neutral"];
  return value === "ai_suggestion" ? <IdentityTag kind="ai">{label}</IdentityTag> : <StatusPill label={label} tone={tone} />;
}

export function ItemStatus({ value }: { value: string }) {
  const [label, tone] = STATUS_LABEL[value] ?? [value, "neutral"];
  return <StatusPill label={label} tone={tone} />;
}

/** A filterable table of one or more record kinds, with a detail panel and package submission. */
export function Records({ projectId, department, kinds, all }: {
  projectId: string; department: string; kinds: string[]; all: KindDto[];
}) {
  const [items, setItems] = useState<ItemDto[] | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [view, setView] = useState("working");
  const [filters, setFilters] = useState({ q: "", status: "", provenance: "", sort: "key", kind: kinds[0] ?? "" });
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const kindDefs = all.filter((k) => kinds.includes(k.key));
  const shared = useContext(SelectedRecord);
  useEffect(() => {
    const open = items?.find((i) => i.id === selected);
    shared.set(open ? open.id : null, open ? open.key : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, items]);

  const load = useCallback(() => {
    workApi.items(projectId, department, { ...filters, kind: kinds.length > 1 ? filters.kind : kinds[0] })
      .then((r) => { setItems(r.items); setCanEdit(r.can_edit); setView(r.view); })
      .catch((e: unknown) => setError(problem(e)));
  }, [projectId, department, kinds, filters]);
  useEffect(load, [load]);

  async function submit() {
    setError(null);
    try {
      const p = await workApi.submit(projectId, department, "", [...checked], "");
      setNotice(`Package ${p.number} submitted with ${p.items.length} record(s), frozen at their current versions.`);
      setChecked(new Set());
      load();
    } catch (e) { setError(problem(e)); }
  }

  if (error && !items) return <p role="alert" className="error">{error}</p>;
  if (!items) return <Skeleton />;
  const toggle = (itemId: string) => setChecked((prev) => {
    const next = new Set(prev);
    if (next.has(itemId)) next.delete(itemId); else next.add(itemId);
    return next;
  });

  return (
    <div className="records">
      <div className="stack">
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status" className="notice">{notice}</p>}
        {view === "approved" && <p className="notice">You are seeing this department's approved work, at the approved
          versions. Drafts stay inside the department.</p>}
        <div className="actions" role="search" aria-label="Filter records">
          {kinds.length > 1 && (
            <label>Kind
              <select value={filters.kind} onChange={(e) => setFilters({ ...filters, kind: e.target.value })}>
                {kindDefs.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </label>
          )}
          <label>Search<input value={filters.q} placeholder="Key or title"
            onChange={(e) => setFilters({ ...filters, q: e.target.value })} /></label>
          <label>Status
            <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="">Any (not archived)</option>
              {Object.keys(STATUS_LABEL).slice(0, 5).map((s) => <option key={s} value={s}>{STATUS_LABEL[s][0]}</option>)}
            </select>
          </label>
          <label>Source
            <select value={filters.provenance} onChange={(e) => setFilters({ ...filters, provenance: e.target.value })}>
              <option value="">Any</option>
              {Object.entries(PROVENANCE_LABEL).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label>Sort
            <select value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value })}>
              <option value="key">ID</option><option value="title">Title</option>
              <option value="updated">Recently changed</option><option value="status">Status</option>
            </select>
          </label>
          {canEdit && <button type="button" onClick={() => { setCreating(true); setSelected(null); }}>New</button>}
          {canEdit && checked.size > 0 && (
            <button type="button" onClick={submit}>Submit {checked.size} for review</button>
          )}
        </div>
        {items.length === 0
          ? <EmptyState title="No records here yet.">{canEdit ? "Create one, or let the AI propose them when the department's steps run."
            : "Nothing has been approved here yet."}</EmptyState>
          : (
            <div className="table-wrap">
              <table aria-label="Records">
                <thead><tr>{canEdit && <th><span className="sr-only">Select</span></th>}<th>ID</th><th>Title</th>
                  <th>Source</th><th>Status</th><th>Version</th></tr></thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className={selected === item.id ? "selected" : undefined}>
                      {canEdit && <td><input type="checkbox" aria-label={`Select ${item.key}`} checked={checked.has(item.id)}
                        onChange={() => toggle(item.id)} /></td>}
                      <td><button type="button" className="link" onClick={() => { setSelected(item.id); setCreating(false); }}>
                        {item.key}</button></td>
                      <td>{item.title}</td><td><ProvenanceTag value={item.provenance} /></td>
                      <td><ItemStatus value={item.status} /></td><td>v{item.version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>
      {creating && (
        <aside className="panel stack" aria-label="New record">
          <h2>New record</h2>
          <RecordForm kinds={kindDefs} onCancel={() => setCreating(false)} onSave={async (kind, title, body, provenance) => {
            const made = await workApi.create(projectId, department, { kind, title, body, provenance });
            setCreating(false);
            setSelected(made.id);
            load();
          }} />
        </aside>
      )}
      {selected && !creating && (
        <RecordDetail key={selected} projectId={projectId} itemId={selected} kinds={all} onChange={load} />
      )}
    </div>
  );
}

function FieldInput({ field, value, onChange }: { field: KindFieldDto; value: unknown; onChange: (v: unknown) => void }) {
  const label = `${human(field.name)}${field.required ? " (required)" : ""}`;
  if (field.type === "enum") {
    return (
      <label>{label}
        <select value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">Not set</option>
          {field.choices.map((c) => <option key={c} value={c}>{human(c)}</option>)}
        </select>
      </label>
    );
  }
  if (field.type === "list") {
    return (
      <label>{label} <span className="muted small">(one per line)</span>
        <textarea rows={3} value={((value as string[]) ?? []).join("\n")}
          onChange={(e) => onChange(e.target.value.split("\n").filter((l) => l.trim()))} />
      </label>
    );
  }
  if (field.type === "int") {
    return <label>{label}<input type="number" min="0" value={(value as number) ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} /></label>;
  }
  if (field.type === "json" && field.name === "sections") {
    return <fieldset><legend>{label}</legend><SectionsEditor value={value} onChange={onChange} /></fieldset>;
  }
  if (field.type === "json" && field.name === "diagram") {
    return (
      <fieldset><legend>{label}</legend>
        <Suspense fallback={<p className="muted small">Loading the diagram editor…</p>}>
          <FlowEditor value={value} onChange={onChange} />
        </Suspense>
      </fieldset>
    );
  }
  if (field.type === "json") {
    return <JsonField label={label} value={value} onChange={onChange} />;
  }
  return <label>{label}<textarea rows={3} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} /></label>;
}

function JsonField({ label, value, onChange }: { label: string; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(value === undefined ? "" : JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <label>{label} <span className="muted small">(structured content; its own editor arrives with this module's step)</span>
      <textarea rows={6} className="mono" value={text} aria-invalid={bad} onChange={(e) => {
        setText(e.target.value);
        try { onChange(e.target.value.trim() ? JSON.parse(e.target.value) : undefined); setBad(false); } catch { setBad(true); }
      }} />
      {bad && <span className="error small">This is not valid JSON yet.</span>}
    </label>
  );
}

function RecordForm({ kinds, initial, onSave, onCancel }: {
  kinds: KindDto[];
  initial?: { kind: string; title: string; body: Record<string, unknown>; provenance: Provenance };
  onSave: (kind: string, title: string, body: Record<string, unknown>, provenance: Exclude<Provenance, "ai_suggestion">) => Promise<void>;
  onCancel: () => void;
}) {
  const [kind, setKind] = useState(initial?.kind ?? kinds[0]?.key ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState<Record<string, unknown>>(initial?.body ?? {});
  const [provenance, setProvenance] = useState<Exclude<Provenance, "ai_suggestion">>(
    initial?.provenance && initial.provenance !== "ai_suggestion" ? initial.provenance : "confirmed");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const def = kinds.find((k) => k.key === kind);
  return (
    <form className="stack-sm" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try { await onSave(kind, title, body, provenance); } catch (err) { setError(problem(err)); } finally { setBusy(false); }
    }}>
      {!initial && kinds.length > 1 && (
        <label>Kind<select value={kind} onChange={(e) => { setKind(e.target.value); setBody({}); }}>
          {kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}</select></label>
      )}
      <label>Title (required)<input value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} /></label>
      {def?.fields.map((f) => (
        <FieldInput key={f.name} field={f} value={body[f.name]} onChange={(v) => setBody((b) => {
          const next = { ...b };
          if (v === undefined || v === "") delete next[f.name]; else next[f.name] = v;
          return next;
        })} />
      ))}
      <label>Source
        <select value={provenance} onChange={(e) => setProvenance(e.target.value as typeof provenance)}>
          <option value="confirmed">Confirmed (stated by the owner or agreed)</option>
          <option value="assumption">Assumption (not yet confirmed)</option>
          <option value="open_question">Open question</option>
        </select>
      </label>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="actions">
        <button type="submit" disabled={busy || !title.trim()}>{initial ? "Save new version" : "Create"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Value({ value, field }: { value: unknown; field?: string }) {
  if (value === undefined || value === null || value === "") return <span className="muted">not set</span>;
  if (field === "sections") {
    return <div className="stack-sm">{asSections(value).map((sec, i) => (
      <section key={i}><h4>{sec.heading}</h4><p className="prewrap">{sec.content}</p></section>))}</div>;
  }
  if (field === "diagram") {
    return <Suspense fallback={<p className="muted small">Loading the diagram…</p>}><FlowEditor value={value} readOnly /></Suspense>;
  }
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
    return <ul>{(value as string[]).map((v, i) => <li key={i}>{v}</li>)}</ul>;
  }
  if (typeof value === "object") return <pre className="mono small">{JSON.stringify(value, null, 2)}</pre>;
  return <span>{human(String(value))}</span>;
}

export function RecordDetail({ projectId, itemId, kinds, onChange }: {
  projectId: string; itemId: string; kinds: KindDto[]; onChange: () => void;
}) {
  const [item, setItem] = useState<ItemDto | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compareWith, setCompareWith] = useState<number | null>(null);
  const [diff, setDiff] = useState<{ field: string; before: unknown; after: unknown }[] | null>(null);
  const [comment, setComment] = useState("");
  const load = useCallback(() => {
    workApi.item(projectId, itemId).then(setItem).catch((e: unknown) => setError(problem(e)));
  }, [projectId, itemId]);
  useEffect(load, [load]);
  const def = useMemo(() => kinds.find((k) => k.key === item?.kind), [kinds, item]);

  useEffect(() => {
    if (!item || compareWith === null) { setDiff(null); return; }
    workApi.compare(projectId, item.id, compareWith, item.version).then((r) => setDiff(r.changes))
      .catch((e: unknown) => setError(problem(e)));
  }, [projectId, item, compareWith]);

  if (error && !item) return <aside className="panel"><p role="alert" className="error">{error}</p></aside>;
  if (!item) return <aside className="panel"><Skeleton /></aside>;
  const act = async (work: () => Promise<unknown>) => {
    setError(null);
    try { await work(); load(); onChange(); } catch (e) { setError(problem(e)); }
  };

  return (
    <aside className="panel stack record-detail" aria-label={`Record ${item.key}`}>
      <div className="row">
        <h2>{item.key} · {item.title}</h2>
        <span className="actions"><ProvenanceTag value={item.provenance} /><ItemStatus value={item.status} /></span>
      </div>
      <p className="muted small">{def?.label ?? item.kind} · version {item.version}
        {item.view === "approved" ? " (approved version)" : ""}</p>
      {error && <p role="alert" className="error">{error}</p>}
      {editing && def ? (
        <RecordForm kinds={[def]} initial={{ kind: item.kind, title: item.title, body: item.body, provenance: item.provenance }}
          onCancel={() => setEditing(false)}
          onSave={async (_k, title, body, provenance) => {
            await workApi.edit(projectId, item.id, { expected_version: item.latest_version, title, body, provenance,
              reason: "edited in the workspace" });
            setEditing(false);
            load();
            onChange();
          }} />
      ) : (
        <dl className="fields">
          {def?.fields.map((f) => <div key={f.name}><dt>{human(f.name)}</dt><dd><Value value={item.body[f.name]} field={f.name} /></dd></div>)}
        </dl>
      )}
      {item.can_edit && !editing && (
        <div className="actions">
          <button type="button" onClick={() => setEditing(true)} disabled={item.status === "archived"}>Edit</button>
          {item.provenance === "ai_suggestion" && (
            <button type="button" onClick={() => act(() => workApi.edit(projectId, item.id, {
              expected_version: item.latest_version, provenance: "confirmed", reason: "confirmed by a professional" }))}>
              Confirm suggestion</button>
          )}
          {item.kind === "document" && (
            <button type="button" className="secondary" onClick={() => {
              const blob = new Blob([toMarkdown(`${item.key} ${item.title} (v${item.version})`, asSections(item.body.sections))],
                { type: "text/markdown" });
              const link = document.createElement("a");
              link.href = URL.createObjectURL(blob);
              link.download = `${item.key}-v${item.version}.md`;
              link.click();
              URL.revokeObjectURL(link.href);
            }}>Export as Markdown</button>
          )}
          <button type="button" className="secondary" onClick={() => act(() => workApi.archive(projectId, item.id,
            item.status !== "archived"))}>{item.status === "archived" ? "Restore" : "Archive"}</button>
        </div>
      )}

      {item.links && (
        <section className="stack-sm" aria-label="Links">
          <h3>Linked records</h3>
          {item.links.length === 0 ? <p className="muted small">No links yet.</p> : (
            <ul className="list">
              {item.links.map((l) => (
                <li key={l.id} className="row">
                  <span>{l.direction === "out" ? human(l.type) : `${human(l.type)} (from)`} <strong>{l.item.key}</strong> {l.item.title}</span>
                  {item.can_edit && l.direction === "out" && (
                    <button type="button" className="secondary" onClick={() => act(() => workApi.unlink(projectId, l.id))}>Remove</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {item.can_edit && <LinkPicker projectId={projectId} item={item} onLinked={() => { load(); onChange(); }} />}
        </section>
      )}

      {item.versions && item.versions.length > 0 && (
        <section className="stack-sm" aria-label="Version history">
          <h3>History</h3>
          <ol className="list">
            {[...item.versions].reverse().map((v) => (
              <li key={v.id} className="row">
                <span>v{v.number} · {v.author_type === "ai" ? <IdentityTag kind="ai">{v.author ?? "AI"}</IdentityTag>
                  : <IdentityTag kind="human">{v.author ?? "Someone"}</IdentityTag>} · {v.reason}
                  <span className="muted small"> · {new Date(v.created_at).toLocaleString()}</span></span>
                {v.number !== item.version && (
                  <button type="button" className="secondary" onClick={() => setCompareWith(v.number)}>Compare with v{item.version}</button>
                )}
              </li>
            ))}
          </ol>
          {diff && compareWith !== null && (
            <div className="table-wrap">
              <table aria-label={`Changes from v${compareWith} to v${item.version}`}>
                <thead><tr><th>Field</th><th>v{compareWith}</th><th>v{item.version}</th></tr></thead>
                <tbody>{diff.length === 0 ? <tr><td colSpan={3}>No differences.</td></tr> : diff.map((d) => (
                  <tr key={d.field}><td>{human(d.field)}</td><td><Value value={d.before} /></td><td><Value value={d.after} /></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {item.versions.some((v) => v.sources.length > 0) && (
            <p className="muted small">AI sources: {item.versions.flatMap((v) => v.sources).map((s) => JSON.stringify(s)).join(", ")}</p>
          )}
        </section>
      )}

      <section className="stack-sm" aria-label="Comments">
        <h3>Comments</h3>
        {(item.comments ?? []).length === 0 && <p className="muted small">No comments yet.</p>}
        <ul className="list">
          {(item.comments ?? []).map((c) => (
            <li key={c.id} className={c.resolved ? "muted" : undefined}>
              <strong>{c.author}</strong> on v{c.version}{c.anchor && "field" in c.anchor ? ` (${human(String(c.anchor.field))})` : ""}: {c.body}
              {c.resolved ? " · resolved" : item.can_edit && (
                <button type="button" className="link" onClick={() => act(() => workApi.resolve(projectId, c.id))}> Resolve</button>
              )}
            </li>
          ))}
        </ul>
        <form className="actions" onSubmit={(e) => {
          e.preventDefault();
          if (comment.trim()) void act(async () => { await workApi.comment(projectId, item.id, comment, item.version); setComment(""); });
        }}>
          <label className="grow">Add a comment on v{item.version}
            <input value={comment} maxLength={5000} onChange={(e) => setComment(e.target.value)} /></label>
          <button type="submit" disabled={!comment.trim()}>Comment</button>
        </form>
      </section>
    </aside>
  );
}

const LINK_TYPES = ["derives_from", "implements", "tests", "depends_on", "blocks", "designs", "relates_to"];

function LinkPicker({ projectId, item, onLinked }: { projectId: string; item: ItemDto; onLinked: () => void }) {
  const [options, setOptions] = useState<{ id: string; key: string; title: string }[]>([]);
  const [to, setTo] = useState("");
  const [type, setType] = useState("derives_from");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    workApi.traceability(projectId).then((t) => setOptions(t.items.filter((i) => i.id !== item.id)))
      .catch(() => setOptions([]));
  }, [projectId, item.id]);
  if (options.length === 0) return null;
  return (
    <div className="actions">
      <label>Link type<select value={type} onChange={(e) => setType(e.target.value)}>
        {LINK_TYPES.map((t) => <option key={t} value={t}>{human(t)}</option>)}</select></label>
      <label>To<select value={to} onChange={(e) => setTo(e.target.value)}>
        <option value="">Choose a record</option>
        {options.map((o) => <option key={o.id} value={o.id}>{o.key} {o.title}</option>)}</select></label>
      <button type="button" disabled={!to} onClick={async () => {
        setError(null);
        try { await workApi.link(projectId, item.id, to, type); setTo(""); onLinked(); } catch (e) { setError(problem(e)); }
      }}>Link</button>
      {error && <span role="alert" className="error">{error}</span>}
    </div>
  );
}

import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api, type StageSpec, type StudioCatalogDto, type StudioWorkflowDto, type StudioWorkflowSummaryDto, type WorkflowSpecDto } from "../api";
import { addDependency, nextStageId, removeDependency, removeStage, renameStage } from "./graph";
import { StageForm } from "./StageForm";

const WorkflowCanvas = lazy(() => import("./WorkflowCanvas").then((m) => ({ default: m.WorkflowCanvas })));

interface Feedback {
  error?: string;
  problems?: string[];
  notice?: string;
}

function failure(err: unknown): Feedback {
  return err instanceof ApiError ? { error: err.message, problems: err.problems } : { error: "That did not work. Try again." };
}

function newStage(id: string): StageSpec {
  return { id, name: "New stage", work: "intake_summary", depends_on: [] };
}

function Messages({ value }: { value: Feedback }) {
  return (
    <>
      {value.notice && <p role="status" className="notice">{value.notice}</p>}
      {value.error && <p role="alert" className="error">{value.error}</p>}
      {value.problems && value.problems.length > 0 && (
        <ul className="problems" aria-label="Problems to fix">{value.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
    </>
  );
}

function Editor({ orgId, catalog, workflowKey, initial, onClose, onChanged }: {
  orgId: string;
  catalog: StudioCatalogDto;
  workflowKey: string;
  initial: WorkflowSpecDto | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<StudioWorkflowDto | null>(null);
  const [spec, setSpec] = useState<WorkflowSpecDto | null>(initial);
  const [revision, setRevision] = useState<number | null>(null);
  const [dirty, setDirty] = useState(initial !== null);
  const [selected, setSelected] = useState<string | null>(initial?.stages[0]?.id ?? null);
  const [formKey, setFormKey] = useState(0); // new form per chosen stage; renaming must keep focus
  const [feedback, setFeedback] = useState<Feedback>({});
  const [busy, setBusy] = useState(false);
  const readOnly = detail?.scope === "platform";

  const load = useCallback(async () => {
    const data = await api.studioWorkflow(orgId, workflowKey);
    setDetail(data);
    const current = data.draft?.spec ?? data.versions[0]?.spec ?? null;
    setSpec(current);
    setRevision(data.draft?.revision ?? null);
    setDirty(false);
    setSelected((s) => s ?? current?.stages[0]?.id ?? null);
  }, [orgId, workflowKey]);

  useEffect(() => {
    if (!initial) load().catch((err: unknown) => setFeedback(failure(err)));
  }, [initial, load]);

  if (!spec) return <><Messages value={feedback} /><p className="muted">Loading…</p></>;
  const stage = spec.stages.find((s) => s.id === selected) ?? null;
  const choose = (id: string | null) => {
    setSelected(id);
    setFormKey((n) => n + 1);
  };
  const edit = (next: WorkflowSpecDto) => {
    setSpec(next);
    setDirty(true);
    setFeedback({});
  };

  async function save(): Promise<number> {
    const draft = await api.saveStudioDraft(orgId, workflowKey, spec as WorkflowSpecDto, revision);
    setRevision(draft.revision);
    setDirty(false);
    onChanged();
    return draft.revision;
  }

  async function run(work: () => Promise<Feedback>) {
    setBusy(true);
    setFeedback({});
    try {
      setFeedback(await work());
    } catch (err) {
      setFeedback(failure(err));
    } finally {
      setBusy(false);
    }
  }

  async function download(format: "json" | "yaml") {
    const file = await api.exportStudioWorkflow(orgId, workflowKey, format);
    const url = URL.createObjectURL(new Blob([file.content], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = file.filename;
    link.click();
    URL.revokeObjectURL(url);
    return {};
  }

  return (
    <div className="stack">
      <div className="row">
        <h2>{spec.name} <span className="muted">· {workflowKey}</span></h2>
        <button type="button" className="secondary" onClick={onClose}>Back to workflows</button>
      </div>
      {readOnly && <p className="notice">Platform templates are read-only. Export one and import it under a new key to change it.</p>}
      <label>
        Workflow name
        <input value={spec.name} maxLength={120} disabled={readOnly} onChange={(e) => edit({ ...spec, name: e.target.value })} />
      </label>
      <Suspense fallback={<p className="muted">Loading diagram…</p>}>
        <WorkflowCanvas stages={spec.stages} selected={selected} readOnly={readOnly} onSelect={choose}
          onConnect={(a, b) => edit(addDependency(spec, a, b))}
          onDisconnect={(a, b) => edit(removeDependency(spec, a, b))} />
      </Suspense>
      <div className="row start">
        <label className="grow">
          Selected stage
          <select value={selected ?? ""} onChange={(e) => choose(e.target.value)}>
            {spec.stages.map((s) => <option key={s.id} value={s.id}>{s.name || s.id}</option>)}
          </select>
        </label>
        {!readOnly && (
          <button type="button" className="secondary" onClick={() => {
            const id = nextStageId(spec);
            edit({ ...spec, stages: [...spec.stages, newStage(id)] });
            choose(id);
          }}>Add stage</button>
        )}
      </div>
      {stage && (
        <StageForm key={formKey} stage={stage} others={spec.stages.filter((s) => s.id !== stage.id)} catalog={catalog}
          readOnly={readOnly}
          onChange={(next) => edit({ ...spec, stages: spec.stages.map((s) => (s.id === stage.id ? next : s)) })}
          onRename={(id) => { edit(renameStage(spec, stage.id, id)); setSelected(id); }}
          onRemove={() => { edit(removeStage(spec, stage.id)); choose(spec.stages.find((s) => s.id !== stage.id)?.id ?? null); }} />
      )}
      <Messages value={feedback} />
      <div className="actions">
        {!readOnly && (
          <>
            <button type="button" className="secondary" disabled={busy} onClick={() => void run(async () => {
              const result = await api.validateStudioWorkflow(orgId, spec);
              return result.valid ? { notice: "No problems found." } : { error: "Fix these before publishing.", problems: result.problems };
            })}>Check for problems</button>
            <button type="button" className="secondary" disabled={busy || !dirty} onClick={() => void run(async () => {
              await save();
              return { notice: "Draft saved." };
            })}>Save draft</button>
            <button type="button" disabled={busy} onClick={() => void run(async () => {
              const current = dirty || revision === null ? await save() : revision;
              const version = await api.publishStudioWorkflow(orgId, workflowKey, current);
              await load();
              onChanged();
              return { notice: `Version ${version.version} published.` };
            })}>Publish</button>
          </>
        )}
        <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(() => download("json"))}>Export JSON</button>
        <button type="button" className="secondary" disabled={busy || dirty} onClick={() => void run(() => download("yaml"))}>Export YAML</button>
      </div>
      {detail && detail.versions.length > 0 && (
        <section>
          <h3>Published versions</h3>
          <ul className="list">
            {detail.versions.map((v) => (
              <li key={v.id} className="row">
                <span>Version {v.version} <span className="muted">· {new Date(v.created_at).toLocaleString()}</span></span>
                {!readOnly && (
                  <button type="button" className="secondary" onClick={() => {
                    edit(v.spec);
                    choose(v.spec.stages[0]?.id ?? null);
                  }}>Load version {v.version} into draft</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function WorkflowsPanel({ orgId, catalog }: { orgId: string; catalog: StudioCatalogDto }) {
  const [items, setItems] = useState<StudioWorkflowSummaryDto[] | null>(null);
  const [open, setOpen] = useState<{ key: string; initial: WorkflowSpecDto | null } | null>(null);
  const [feedback, setFeedback] = useState<Feedback>({});
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [format, setFormat] = useState<"json" | "yaml">("yaml");
  const [content, setContent] = useState("");

  const reload = useCallback(() => {
    api.studioWorkflows(orgId).then((r) => setItems(r.items)).catch((err: unknown) => setFeedback(failure(err)));
  }, [orgId]);
  useEffect(reload, [reload]);

  if (open) {
    return <Editor key={open.key} orgId={orgId} catalog={catalog} workflowKey={open.key} initial={open.initial}
      onChanged={reload} onClose={() => { setOpen(null); reload(); }} />;
  }

  function create(e: FormEvent) {
    e.preventDefault();
    const clean = key.trim();
    setOpen({ key: clean, initial: { key: clean, name: name.trim() || clean, execution: "sequential", stages: [newStage("stage_1")] } });
  }

  async function runImport(e: FormEvent) {
    e.preventDefault();
    setFeedback({});
    try {
      const result = await api.importStudioWorkflow(orgId, format, content);
      setContent("");
      reload();
      setFeedback({
        notice: `Imported ${result.draft.key} as a draft.`,
        problems: result.problems,
        error: result.problems.length ? "It needs these fixes before it can be published." : undefined,
      });
    } catch (err) {
      setFeedback(failure(err));
    }
  }

  return (
    <div className="stack">
      <section>
        <h2>Workflows</h2>
        {items === null && !feedback.error && <p className="muted">Loading…</p>}
        <ul className="list">
          {items?.map((w) => (
            <li key={`${w.scope}-${w.key}`} className="row">
              <span>
                {w.name} <span className="muted">· {w.key} · {w.scope === "platform" ? "Platform template" : "Your organization"}
                  {w.latest ? ` · version ${w.latest.version}` : " · not published"}</span>
              </span>
              <button type="button" className="secondary" aria-label={`Open ${w.key}`}
                onClick={() => setOpen({ key: w.key, initial: null })}>Open</button>
            </li>
          ))}
        </ul>
      </section>
      <Messages value={feedback} />
      <form onSubmit={create} className="stack-sm">
        <h3>New workflow</h3>
        <label>Workflow key<input value={key} onChange={(e) => setKey(e.target.value)} pattern="[a-z][a-z0-9_\-]{1,63}" required /></label>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></label>
        <button type="submit" disabled={!key.trim()}>Create workflow</button>
      </form>
      <form onSubmit={(e) => void runImport(e)} className="stack-sm">
        <h3>Import</h3>
        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value as "json" | "yaml")}>
            <option value="yaml">YAML</option>
            <option value="json">JSON</option>
          </select>
        </label>
        <label>
          File
          <input type="file" accept=".json,.yaml,.yml" onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setFormat(file.name.endsWith(".json") ? "json" : "yaml");
            void file.text().then(setContent);
          }} />
        </label>
        <label>Workflow content<textarea rows={6} value={content} onChange={(e) => setContent(e.target.value)} /></label>
        <button type="submit" disabled={!content.trim()}>Import as draft</button>
      </form>
    </div>
  );
}

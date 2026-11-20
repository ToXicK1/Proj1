import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { ApiError, api, type ActivityDto, type ActivityFieldDto, type ActivityItemDto } from "../api";
import { EmptyState, Skeleton, When } from "../components/ui";

const KIND_LABELS: Record<string, string> = {
  job: "Job", stage: "Step", context: "Given to the AI", model_call: "Model call", output: "AI result",
  retry: "Not usable", model_error: "Model problem", review: "Review", checks: "Build and tests", result: "Outcome",
};

const human = (key: string) => key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const live = (item: ActivityItemDto) => item.kind === "model_call" && (item.detail.state === "waiting" || item.detail.state === "streaming");

function Field({ field }: { field: ActivityFieldDto }) {
  if (field.files) {
    return (
      <div className="act-field">
        <dt>{human(field.key)} <span className="muted">({field.count ?? field.files.length})</span></dt>
        <dd>
          <ul className="act-files">
            {field.files.map((f) => <li key={f.path}><code>{f.path}</code><span className="muted">{f.lines} lines</span></li>)}
          </ul>
        </dd>
      </div>
    );
  }
  return (
    <div className="act-field">
      <dt>{human(field.key)}{field.items && <span className="muted"> ({field.count})</span>}</dt>
      <dd>{field.items ? <ul>{field.items.map((t, i) => <li key={i}>{t}</li>)}</ul> : field.text}</dd>
    </div>
  );
}

function List({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="act-field">
      <dt>{title}</dt>
      <dd><ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul></dd>
    </div>
  );
}

/** Text that keeps itself scrolled to the newest line while it grows, like a streaming chat reply. */
function Stream({ text, className, active }: { text: string; className: string; active: boolean }) {
  const box = useRef<HTMLPreElement>(null);
  useLayoutEffect(() => {
    if (active && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [text, active]);
  return <pre ref={box} className={className}>{text}{active && <span className="act-caret" aria-hidden="true" />}</pre>;
}

/** One model call, shown the way a chat app shows its thinking: live while it runs, folded away when done. */
function ModelCall({ item }: { item: ActivityItemDto }) {
  const d = item.detail;
  const running = live(item);
  const [open, setOpen] = useState(running);
  const [touched, setTouched] = useState(false);
  useEffect(() => { if (!touched) setOpen(running); }, [running, touched]);
  const thinking = d.thinking ?? "";
  const text = d.text ?? "";
  const status = d.state === "waiting" ? "Waiting for the model…"
    : d.state === "streaming" ? (text ? "Writing…" : thinking ? "Thinking…" : "Waiting for the model…")
      : d.state === "failed" ? `The model did not answer${d.error ? ` (${d.error.replace(/_/g, " ")})` : ""}`
        : thinking ? `Thought and wrote for ${d.seconds ?? d.elapsed}s` : `Wrote ${text.length.toLocaleString()} characters in ${d.seconds ?? d.elapsed}s`;
  return (
    <li className={`act-entry act-call ${running ? "running" : ""}`}>
      <details open={open} onToggle={(e) => { const next = (e.target as HTMLDetailsElement).open; if (next !== open) { setTouched(true); setOpen(next); } }}>
        <summary className="act-row">
          <span className={`act-dot act-model_call ${running ? "pulsing" : ""}`} aria-hidden="true" />
          <span className="act-main">
            <span className="act-title">{item.title}</span>
            <span className={running ? "act-meta act-thinking" : "act-meta"}>
              {status}{running && d.elapsed !== undefined && <> · {d.elapsed}s</>}
              {item.stage_name && <> · {item.stage_name}</>}{" · "}<When at={item.at} />
            </span>
          </span>
        </summary>
        <div className="act-detail act-call-body">
          {d.warning && <p className="act-warning" role="note">{d.warning}</p>}
          {d.hidden && <p className="act-hidden" role="note">{d.hidden}</p>}
          {thinking && (
            <div className="act-block">
              <span className="act-block-label">Reasoning reported by the model</span>
              <Stream text={thinking} className="act-thought" active={running && !text} />
            </div>
          )}
          <div className="act-block">
            <span className="act-block-label">{running ? "Reply, as it is written" : "Reply"}</span>
            {text || running ? <Stream text={text} className="act-reply" active={running} />
              : !d.hidden && <p className="muted small">No reply text.</p>}
            {!thinking && !running && !d.hidden && (
              <p className="muted small">This model reports no separate reasoning, so its reply is what you see being written.</p>
            )}
          </div>
          {d.prompt && (
            <details className="act-prompt">
              <summary>Exactly what the agent was given · about {d.prompt_tokens_est?.toLocaleString()} tokens of a {d.context_tokens?.toLocaleString()}-token window</summary>
              <span className="act-block-label">Instructions</span>
              <pre className="act-reply">{d.prompt.system}</pre>
              <span className="act-block-label">Input</span>
              <pre className="act-reply">{d.prompt.user}</pre>
              {d.prompt.cut && <p className="muted small">Very long prompt: only the first part is kept here.</p>}
            </details>
          )}
          {d.tokens && <p className="muted small">{d.tokens.in.toLocaleString()} tokens in, {d.tokens.out.toLocaleString()} out</p>}
        </div>
      </details>
    </li>
  );
}

/** The details behind one entry. Everything is plain text: AI output is data, never markup. */
function Detail({ item }: { item: ActivityItemDto }) {
  const d = item.detail;
  switch (item.kind) {
    case "context":
      return (
        <dl className="act-detail">
          <List title="The confirmed brief" items={d.brief} />
          <div className="act-field">
            <dt>Earlier approved work it can read</dt>
            <dd>
              {d.earlier_work?.length ? (
                <ul className="act-files">
                  {d.earlier_work.map((w) => (
                    <li key={w.stage}>
                      <span>{w.name} <span className="muted">· {w.reason}</span></span>
                      <span className={w.included && w.chars < w.full_chars ? "act-cut" : "muted"}>
                        {!w.included ? "no room left" : w.chars < w.full_chars ? `${w.chars.toLocaleString()} of ${w.full_chars.toLocaleString()} chars` : `${w.chars.toLocaleString()} chars`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : "None yet"}
            </dd>
          </div>
          <List title="Feedback it must address" items={d.feedback} />
          <List title="It must return" items={d.must_return?.map(human)} />
          {d.rules && d.rules.length > 0 && <div className="act-field"><dt>Rules applied</dt><dd>{d.rules.length}</dd></div>}
        </dl>
      );
    case "output":
      return (
        <dl className="act-detail">
          {d.fields?.map((f) => <Field key={f.key} field={f} />)}
          <p className="muted small">{d.seconds}s{d.tokens ? ` · ${d.tokens.in} tokens in, ${d.tokens.out} out` : ""}</p>
        </dl>
      );
    case "review":
      return <dl className="act-detail"><List title="Findings" items={d.findings?.length ? d.findings : ["Nothing to change"]} /></dl>;
    case "checks":
      return (
        <dl className="act-detail">
          {d.checks?.map((c) => (
            <div key={c.name} className="act-field">
              <dt>{c.name}: <span className={c.passed ? "act-pass" : "act-fail"}>{c.passed ? "passed" : "failed"}</span></dt>
              <dd>{c.summary}{c.output.length > 0 && <pre className="code">{c.output.join("\n")}</pre>}</dd>
            </div>
          ))}
          {d.files && d.files.length > 0 && <Field field={{ key: "files_tested", files: d.files, count: d.files.length }} />}
        </dl>
      );
    case "stage":
      return d.addressing?.length ? <dl className="act-detail"><List title="Addressing" items={d.addressing} /></dl> : null;
    case "result":
      return d.reason ? <p className="act-detail">{d.reason}</p> : null;
    case "model_error":
    case "retry":
      return d.seconds !== undefined ? <p className="act-detail muted">After {d.seconds}s</p> : null;
    default:
      return null;
  }
}

function Entry({ item }: { item: ActivityItemDto }) {
  if (item.kind === "model_call" && item.detail.state) return <ModelCall item={item} />;
  const detail = Detail({ item }); // plain function call: null when there is nothing more to show
  const head = (
    <>
      <span className={`act-dot act-${item.kind}`} aria-hidden="true" />
      <span className="act-main">
        <span className="act-title">{item.title}</span>
        <span className="act-meta">
          {KIND_LABELS[item.kind] ?? item.kind}
          {item.stage_name && <> · {item.stage_name}</>}
          {item.department && <> · {item.department}</>}
          {" · "}<When at={item.at} />
        </span>
      </span>
    </>
  );
  if (!detail) return <li className="act-entry"><div className="act-row">{head}</div></li>;
  return (
    <li className="act-entry">
      <details>
        <summary className="act-row">{head}</summary>
        {detail}
      </details>
    </li>
  );
}

/** Top-right menu in the workspace: what the AI is doing right now, step by step. Not shown to owners. */
export function ActivityMenu({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ActivityDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const panelId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const load = useCallback(() => {
    api.projectActivity(projectId).then((d) => { setData(d); setError(null); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the AI activity."));
  }, [projectId]);

  const working = (data?.jobs.length ?? 0) > 0 || Boolean(data?.items.some(live));
  useEffect(() => {
    load();
    const every = open ? (working ? 1000 : 3000) : 10000; // near real time while you watch the AI work
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, every);
    return () => window.clearInterval(timer);
  }, [load, open, working]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onClick = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onClick); };
  }, [open]);

  return (
    <div className="act-menu" ref={wrap}>
      <button type="button" className={working ? "act-button working" : "act-button"} aria-expanded={open}
        aria-controls={panelId} onClick={() => setOpen(!open)}>
        <span className="act-pulse" aria-hidden="true" />
        AI activity
        <span className="sr-only">{working ? " (working now)" : " (idle)"}</span>
      </button>
      {open && (
        <div className="act-panel" id={panelId} role="region" aria-label="AI activity">
          <div className="act-head">
            <strong>What the AI is doing</strong>
            {data && (working
              ? <span className="act-status working">Working now{data.jobs.length > 0 && <>: {data.jobs.map((j) => j.kind).join(", ")} · since <When at={data.jobs[0].since} /></>}</span>
              : <span className="act-status">Idle: nothing is running</span>)}
          </div>
          <p className="hint">Every step appears as it happens, including each model call streaming live, the exact prompt
            it was given, and any reasoning the model reports.</p>
          {error && <p role="alert" className="error">{error}</p>}
          {!data && !error && <Skeleton title={false} />}
          {data && data.items.length === 0 && <EmptyState title="No AI activity yet.">Steps appear here once delivery starts.</EmptyState>}
          {data && data.items.length > 0 && (
            <ol className="act-list" aria-label="AI steps, newest first">
              {data.items.map((item) => <Entry key={item.id} item={item} />)}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

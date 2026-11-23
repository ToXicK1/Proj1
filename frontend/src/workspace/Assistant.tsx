import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiError } from "../api";
import { IdentityTag } from "../components/ui";
import { workApi, type AssistantExchangeDto } from "./workApi";

/** The record open in the work area, so the assistant can be asked about it. */
export const SelectedRecord = createContext<{ id: string | null; key: string | null; set: (id: string | null, key: string | null) => void }>(
  { id: null, key: null, set: () => undefined });

const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work. Please try again.");

/** The department's AI assistant. It answers and proposes; a person decides whether to add a proposal, and an added
 * proposal is still an AI suggestion to confirm. It never changes, submits or approves anything. */
export function Assistant({ projectId, department, canEdit }: { projectId: string; department: string; canEdit: boolean }) {
  const selected = useContext(SelectedRecord);
  const [items, setItems] = useState<AssistantExchangeDto[]>([]);
  const [question, setQuestion] = useState("");
  const [about, setAbout] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    workApi.assistantHistory(projectId, department).then((r) => setItems(r.items)).catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  useEffect(load, [load]);
  const pending = items.some((i) => i.status === "pending");
  useEffect(() => {
    if (!pending) return undefined;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  return (
    <section className="panel stack-sm assistant" aria-label="AI assistant">
      <h3><IdentityTag kind="ai">AI assistant</IdentityTag></h3>
      <form className="stack-sm" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await workApi.ask(projectId, department, question, about && selected.id ? selected.id : null);
          setQuestion("");
          load();
        } catch (err) { setError(problem(err)); } finally { setBusy(false); }
      }}>
        <label>Ask the assistant
          <textarea rows={3} value={question} maxLength={4000} onChange={(e) => setQuestion(e.target.value)}
            placeholder="For example: which acceptance criteria are missing?" />
        </label>
        {selected.key && (
          <label className="check"><input type="checkbox" checked={about} onChange={(e) => setAbout(e.target.checked)} />
            About {selected.key}</label>
        )}
        <button type="submit" disabled={busy || !question.trim()}>Ask</button>
      </form>
      {error && <p role="alert" className="error small">{error}</p>}
      <ol className="list" aria-label="Assistant answers">
        {items.map((x) => (
          <li key={x.id} className="stack-sm">
            <p className="small"><strong>{x.asked_by}</strong>{x.item ? ` about ${x.item.key}` : ""}: {x.question}</p>
            {x.status === "pending" && <p className="muted small">The assistant is working on this…</p>}
            {x.status === "failed" && <p className="error small">The assistant could not answer: {x.failure}</p>}
            {x.status === "answered" && <p className="small assistant-answer">{x.answer}</p>}
            {x.proposals.length > 0 && (
              <ul className="list small" aria-label="Proposals">
                {x.proposals.map((p, i) => (
                  <li key={i} className="row">
                    <span>{p.kind.replace(/_/g, " ")}: <strong>{p.title}</strong></span>
                    {p.added ? <span className="muted">added as {p.added}</span> : canEdit && (
                      <button type="button" className="secondary" onClick={async () => {
                        setError(null);
                        try { await workApi.addProposal(projectId, x.id, i); load(); } catch (e) { setError(problem(e)); }
                      }}>Add as suggestion</button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
      <p className="muted small">Added proposals are AI suggestions: confirm or edit them before they can be submitted.</p>
    </section>
  );
}

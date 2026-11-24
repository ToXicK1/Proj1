import { useEffect, useState } from "react";
import { EmptyState } from "../components/ui";
import { Records } from "./Records";
import { type KindDto, workApi } from "./workApi";

/** The PM's Project Intake (RD-21): the client's optional pre-meeting answers as unconfirmed input, then the one
 * intake record the PM fills in from the meetings and validates. */
export function Intake({ projectId, all }: { projectId: string; all: KindDto[] }) {
  const [form, setForm] = useState<Awaited<ReturnType<typeof workApi.clientForm>> | null>(null);
  useEffect(() => { workApi.clientForm(projectId).then(setForm).catch(() => setForm(null)); }, [projectId]);
  return (
    <div className="stack">
      <section className="panel stack-sm" aria-label="Client's pre-meeting answers">
        <h3>Client's pre-meeting answers <span className="muted small">(unconfirmed input)</span></h3>
        {!form || form.answers.length === 0
          ? <EmptyState title="The client has not filled in the optional pre-meeting form." />
          : <dl className="fields">{form.answers.map((a) => (
            <div key={a.field}><dt>{a.label}</dt><dd className="prewrap">{a.value}</dd></div>
          ))}</dl>}
        <p className="muted small">Use these as a starting point for your meetings. Only what you confirm in the intake
          below counts.</p>
      </section>
      <p className="muted">One intake per project. Create it as a draft from your meetings; when it is confirmed and
        complete, set its validation to "validated". The Project Brief is built from the validated intake (P4).</p>
      <Records projectId={projectId} department="project_manager" kinds={["project_intake"]} all={all} />
    </div>
  );
}

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api, type StudioAgentDto, type StudioCatalogDto, type StudioHookDto, type StudioProposalDto, type StudioRuleDto } from "../api";

interface PanelProps {
  orgId: string;
  catalog: StudioCatalogDto;
  onCatalogChange: () => void;
}

function useAction(after: () => void | Promise<void>) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const run = async (work: () => Promise<unknown>, done: string): Promise<boolean> => {
    setError(null);
    setNotice(null);
    try {
      await work();
      await after();
      setNotice(done);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.");
      return false;
    }
  };
  const messages: ReactNode = (
    <>
      {notice && <p role="status" className="notice">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </>
  );
  return { run, messages, setError };
}

function keys(text: string): string[] {
  return text.split(",").map((k) => k.trim()).filter(Boolean);
}

const BLANK_AGENT = { profile: "", key: "", kind: "lead" as "lead" | "reviewer", instructions: "", outputs: "", route: "" };

export function ProfilesPanel({ orgId, catalog, onCatalogChange }: PanelProps) {
  const { run, messages } = useAction(onCatalogChange);
  const [profileKey, setProfileKey] = useState("");
  const [profileName, setProfileName] = useState("");
  const [form, setForm] = useState(BLANK_AGENT);
  const [editing, setEditing] = useState<StudioAgentDto | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [tools, setTools] = useState<string[]>([]);
  const kind = editing?.kind ?? form.kind;
  const toggle = (list: string[], value: string, on: boolean) => (on ? [...list, value] : list.filter((v) => v !== value));

  function reset() {
    setForm(BLANK_AGENT);
    setEditing(null);
    setSources([]);
    setTools([]);
  }

  function startEdit(agent: StudioAgentDto) {
    setEditing(agent);
    setForm({ profile: agent.profile, key: agent.key, kind: agent.kind, instructions: agent.instructions,
      outputs: agent.required_keys.join(", "), route: agent.model_route ?? "" });
    setSources(agent.context_sources);
    setTools(agent.tools);
  }

  async function saveAgent(e: FormEvent) {
    e.preventDefault();
    const body = { instructions: form.instructions, required_keys: keys(form.outputs), model_route: form.route,
      context_sources: sources, tools };
    const ok = await run(() => (editing
      ? api.addAgentVersion(orgId, editing.key, body)
      : api.createAgent(orgId, { ...body, profile: form.profile, key: form.key, kind: form.kind })),
    editing ? `Saved a new version of ${editing.key}.` : `Agent ${form.key} created.`);
    if (ok) reset();
  }

  return (
    <div className="stack">
      {messages}
      <section className="stack-sm">
        <h2>Profiles</h2>
        <ul className="list">{catalog.profiles.map((p) => <li key={p.key}>{p.name} <span className="muted">· {p.key}</span></li>)}</ul>
        {catalog.profiles.length === 0 && <p className="muted">No profiles yet.</p>}
        <form className="stack-sm" onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.createProfile(orgId, profileKey.trim(), profileName.trim()), `Profile ${profileName.trim()} created.`)
            .then((ok) => { if (ok) { setProfileKey(""); setProfileName(""); } });
        }}>
          <label>Profile key<input required value={profileKey} onChange={(e) => setProfileKey(e.target.value)} /></label>
          <label>Profile name<input required maxLength={120} value={profileName} onChange={(e) => setProfileName(e.target.value)} /></label>
          <button type="submit">Create profile</button>
        </form>
      </section>
      <section className="stack-sm">
        <h2>Agents</h2>
        <ul className="list">
          {catalog.agents.map((a) => (
            <li key={a.key} className="row">
              <span>{a.key} <span className="muted">· {a.kind} · {a.profile} · version {a.version}</span></span>
              <button type="button" className="secondary" aria-label={`Edit ${a.key}`} onClick={() => startEdit(a)}>Edit</button>
            </li>
          ))}
        </ul>
        {catalog.model_routes.length === 0 && <p className="notice">An agent needs a model route. No route is set up yet.</p>}
        <form className="stack-sm" onSubmit={(e) => void saveAgent(e)}>
          <h3>{editing ? `New version of ${editing.key}` : "New agent"}</h3>
          {!editing && (
            <>
              <label>
                Agent profile
                <select required value={form.profile} onChange={(e) => setForm({ ...form, profile: e.target.value })}>
                  <option value="">Choose…</option>
                  {catalog.profiles.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
                </select>
              </label>
              <label>Agent key<input required value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
              <label>
                Agent type
                <select value={form.kind} onChange={(e) => { setForm({ ...form, kind: e.target.value as "lead" | "reviewer" }); setSources([]); }}>
                  <option value="lead">Lead</option>
                  <option value="reviewer">Reviewer</option>
                </select>
              </label>
            </>
          )}
          <label>Instructions<textarea required rows={4} maxLength={4000} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} /></label>
          <label>Output keys (comma separated)<input required value={form.outputs} onChange={(e) => setForm({ ...form, outputs: e.target.value })} /></label>
          <label>
            Agent model route
            <select required value={form.route} onChange={(e) => setForm({ ...form, route: e.target.value })}>
              <option value="">Choose…</option>
              {catalog.model_routes.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <fieldset className="stack-sm">
            <legend>May read</legend>
            {catalog.context_sources[kind].map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={sources.includes(s)} onChange={(e) => setSources(toggle(sources, s, e.target.checked))} />{s}
              </label>
            ))}
          </fieldset>
          <fieldset className="stack-sm">
            <legend>Tool permissions</legend>
            {catalog.tools.map((t) => (
              <label key={t.key} className="check">
                <input type="checkbox" disabled={!t.grantable} checked={tools.includes(t.key)}
                  onChange={(e) => setTools(toggle(tools, t.key, e.target.checked))} />
                {t.key} <span className="muted">· {t.permission_class}{t.grantable ? "" : " · cannot be granted yet"}</span>
              </label>
            ))}
          </fieldset>
          <div className="actions">
            <button type="submit">{editing ? "Save new version" : "Create agent"}</button>
            {editing && <button type="button" className="secondary" onClick={reset}>Cancel</button>}
          </div>
        </form>
      </section>
    </div>
  );
}

const BLANK_RULE = { key: "", scope_type: "organization", scope_key: "", kind: "convention", name: "", description: "", content: "", change_note: "" };

export function RulesPanel({ orgId, catalog }: PanelProps) {
  const [rules, setRules] = useState<StudioRuleDto[]>([]);
  const [proposals, setProposals] = useState<StudioProposalDto[]>([]);
  const [form, setForm] = useState(BLANK_RULE);
  const reload = useCallback(async () => {
    const [r, p] = await Promise.all([api.studioRules(orgId), api.studioProposals(orgId)]);
    setRules(r.items);
    setProposals(p.items.filter((item) => item.status === "pending"));
  }, [orgId]);
  const { run, messages, setError } = useAction(reload);
  useEffect(() => { reload().catch(() => setError("Could not load rules.")); }, [reload, setError]);
  const field = (name: keyof typeof BLANK_RULE, value: string) => setForm({ ...form, [name]: value });

  return (
    <div className="stack">
      {messages}
      <section>
        <h2>Rules</h2>
        {rules.length === 0 && <p className="muted">No rules yet.</p>}
        <ul className="list">
          {rules.map((r) => (
            <li key={r.id} className="row">
              <span>{r.name} <span className="muted">· {r.kind} · {r.scope_type}{r.scope_key ? `:${r.scope_key}` : ""} · version {r.version} · {r.status}</span></span>
              {r.status !== "retired" && (
                <button type="button" className="secondary" aria-label={`Retire ${r.key}`}
                  onClick={() => void run(() => api.retireRule(orgId, r.id), `${r.name} retired.`)}>Retire</button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <form className="stack-sm" onSubmit={(e) => {
        e.preventDefault();
        void run(() => api.saveRule(orgId, form), `Rule ${form.name} saved.`).then((ok) => { if (ok) setForm(BLANK_RULE); });
      }}>
        <h3>Add or update a rule</h3>
        <label>Rule key<input required value={form.key} onChange={(e) => field("key", e.target.value)} /></label>
        <label>Rule name<input required maxLength={120} value={form.name} onChange={(e) => field("name", e.target.value)} /></label>
        <label>
          Applies at
          <select value={form.scope_type} onChange={(e) => field("scope_type", e.target.value)}>
            {catalog.rule_scopes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {form.scope_type !== "organization" && <label>Scope key<input required value={form.scope_key} onChange={(e) => field("scope_key", e.target.value)} /></label>}
        <label>
          Rule type
          <select value={form.kind} onChange={(e) => field("kind", e.target.value)}>
            {catalog.rule_kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}
          </select>
        </label>
        <label>Rule text<textarea required rows={3} maxLength={2000} value={form.content} onChange={(e) => field("content", e.target.value)} /></label>
        <label>Change note<input maxLength={300} value={form.change_note} onChange={(e) => field("change_note", e.target.value)} /></label>
        <p className="muted">Rules guide agents. To enforce something, add a sensor or a hook.</p>
        <button type="submit">Save rule</button>
      </form>
      <section>
        <h2>Proposed changes</h2>
        {proposals.length === 0 && <p className="muted">Nothing is waiting for a decision.</p>}
        <ul className="list">
          {proposals.map((p) => (
            <li key={p.id} className="stack-sm">
              <strong>{p.target}: {p.key}</strong> <span className="muted">· from {p.proposer_type}</span>
              <pre className="code">{JSON.stringify(p.payload, null, 2)}</pre>
              {p.conflicts.length > 0 && <p className="error">Conflicts: {p.conflicts.join("; ")}</p>}
              <div className="actions">
                <button type="button" aria-label={`Approve proposal ${p.key}`} onClick={() => void run(() => api.decideProposal(orgId, p.id, true), "Proposal approved.")}>Approve</button>
                <button type="button" className="secondary" aria-label={`Reject proposal ${p.key}`} onClick={() => void run(() => api.decideProposal(orgId, p.id, false), "Proposal rejected.")}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const ACTION_EXAMPLES: Record<string, string> = {
  require_approval: '{\n  "stages": ["stage_1"]\n}',
  run_sensor: '{\n  "sensor": "secret_detection",\n  "config": {}\n}',
  notify: '{\n  "role": "project_owner",\n  "message": "A stage is ready for review"\n}',
};

export function HooksPanel({ orgId, catalog }: PanelProps) {
  const [hooks, setHooks] = useState<StudioHookDto[]>([]);
  const reload = useCallback(async () => setHooks((await api.studioHooks(orgId)).items), [orgId]);
  const { run, messages, setError } = useAction(reload);
  const [key, setKey] = useState("");
  const [event, setEvent] = useState("stage.approval_requested");
  const [phase, setPhase] = useState<"pre" | "post">("post");
  const [action, setAction] = useState("notify");
  const [config, setConfig] = useState(ACTION_EXAMPLES.notify);
  const [policy, setPolicy] = useState<"advisory" | "fail_closed">("advisory");
  useEffect(() => { reload().catch(() => setError("Could not load hooks.")); }, [reload, setError]);
  const canPre = catalog.hook_pre_events.includes(event);
  const canBlock = catalog.hook_blockable.some(([e, p]) => e === event && p === phase);

  function save(e: FormEvent) {
    e.preventDefault();
    let actionConfig: Record<string, unknown>;
    try {
      actionConfig = JSON.parse(config) as Record<string, unknown>;
    } catch {
      setError("The action settings are not valid JSON.");
      return;
    }
    void run(() => api.saveHook(orgId, key.trim(), {
      event, phase, action, action_config: actionConfig, permissions: [catalog.hook_actions[action]],
      failure_policy: canBlock ? policy : "advisory",
    }), `Hook ${key.trim()} saved.`).then((ok) => { if (ok) setKey(""); });
  }

  return (
    <div className="stack">
      {messages}
      <section>
        <h2>Hooks</h2>
        {hooks.length === 0 && <p className="muted">No hooks yet.</p>}
        <ul className="list">
          {hooks.map((h) => (
            <li key={h.key} className="row">
              <span>{h.key} <span className="muted">· {h.event} ({h.phase}) · {h.action} · {h.failure_policy} · version {h.version}</span></span>
              <button type="button" className="secondary" aria-label={`${h.enabled ? "Disable" : "Enable"} ${h.key}`}
                onClick={() => void run(() => api.setHookEnabled(orgId, h.key, !h.enabled), `${h.key} ${h.enabled ? "disabled" : "enabled"}.`)}>
                {h.enabled ? "Disable" : "Enable"}
              </button>
            </li>
          ))}
        </ul>
      </section>
      <form className="stack-sm" onSubmit={save}>
        <h3>Add or update a hook</h3>
        <p className="muted">Hooks choose from built-in actions. They cannot run code.</p>
        <label>Hook key<input required value={key} onChange={(e) => setKey(e.target.value)} /></label>
        <label>
          Event
          <select value={event} onChange={(e) => {
            setEvent(e.target.value);
            if (!catalog.hook_pre_events.includes(e.target.value)) setPhase("post");
          }}>
            {catalog.hook_events.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label>
          Timing
          <select value={phase} onChange={(e) => setPhase(e.target.value as "pre" | "post")}>
            <option value="post">After the event</option>
            {canPre && <option value="pre">Before the event</option>}
          </select>
        </label>
        <label>
          Action
          <select value={action} onChange={(e) => { setAction(e.target.value); setConfig(ACTION_EXAMPLES[e.target.value] ?? "{}"); }}>
            {Object.keys(catalog.hook_actions).map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label>Action settings (JSON)<textarea rows={4} value={config} onChange={(e) => setConfig(e.target.value)} /></label>
        <label>
          If the hook fails
          <select value={canBlock ? policy : "advisory"} disabled={!canBlock} onChange={(e) => setPolicy(e.target.value as "advisory" | "fail_closed")}>
            <option value="advisory">Record it and continue</option>
            <option value="fail_closed">Stop the workflow</option>
          </select>
        </label>
        <button type="submit">Save hook</button>
      </form>
    </div>
  );
}

export function SensorsPanel({ catalog }: { catalog: StudioCatalogDto }) {
  return (
    <section>
      <h2>Sensors</h2>
      <p className="muted">Sensors are built into the platform. Add them to a stage in the workflow editor.</p>
      <ul className="list">
        {catalog.sensors.map((s) => (
          <li key={s.key}>
            <strong>{s.key}</strong> <span className="muted">· {s.category}{s.evidence_kind ? ` · needs ${s.evidence_kind} evidence` : ""}</span>
            <div>{s.description}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

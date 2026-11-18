import { useState } from "react";
import type { SensorSpec, StageSpec, StudioCatalogDto } from "../api";
import { readPolicy, writePolicy, type PolicyDraft } from "./graph";

interface Props {
  stage: StageSpec;
  others: StageSpec[];
  catalog: StudioCatalogDto;
  readOnly: boolean;
  onChange: (next: StageSpec) => void;
  onRename: (id: string) => void;
  onRemove: () => void;
}

function optional<T extends object>(stage: T, key: keyof T, value: string): T {
  const next = { ...stage };
  if (value) (next as Record<string, unknown>)[key as string] = value;
  else delete next[key];
  return next;
}

function SensorRow({ sensor, readOnly, onChange, onRemove }: {
  sensor: SensorSpec;
  readOnly: boolean;
  onChange: (s: SensorSpec) => void;
  onRemove: () => void;
}) {
  const [text, setText] = useState(JSON.stringify(sensor.config ?? {}, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <fieldset disabled={readOnly} className="stack-sm">
      <legend>{sensor.key}</legend>
      <label className="check">
        <input type="checkbox" checked={sensor.mandatory !== false}
          onChange={(e) => onChange({ ...sensor, mandatory: e.target.checked })} />
        Must pass before approval
      </label>
      <label className="check">
        <input type="checkbox" checked={Boolean(sensor.allow_risk_acceptance)}
          onChange={(e) => onChange({ ...sensor, allow_risk_acceptance: e.target.checked })} />
        An administrator may accept the risk
      </label>
      <label>
        Settings for {sensor.key} (JSON)
        <textarea rows={3} value={text} onChange={(e) => {
          setText(e.target.value);
          try {
            onChange({ ...sensor, config: JSON.parse(e.target.value || "{}") as Record<string, unknown> });
            setBad(false);
          } catch {
            setBad(true);
          }
        }} />
      </label>
      {bad && <p role="alert" className="error">These settings are not valid JSON yet.</p>}
      <button type="button" className="secondary" onClick={onRemove}>Remove {sensor.key}</button>
    </fieldset>
  );
}

export function StageForm({ stage, others, catalog, readOnly, onChange, onRename, onRemove }: Props) {
  const policy = readPolicy(stage.approval_policy);
  const isAi = catalog.work.find((w) => w.key === stage.work)?.ai ?? false;
  const sensors = stage.sensors ?? [];
  const used = new Set(sensors.map((s) => s.key));
  const setPolicy = (p: PolicyDraft) => onChange({ ...stage, approval_policy: writePolicy(p) });

  return (
    <fieldset disabled={readOnly} className="stack-sm plain">
      <h3>Stage settings</h3>
      <label>
        Stage ID
        <input value={stage.id} onChange={(e) => onRename(e.target.value)} />
      </label>
      <label>
        Stage name
        <input value={stage.name} maxLength={120} onChange={(e) => onChange({ ...stage, name: e.target.value })} />
      </label>
      <label>
        Work
        <select value={stage.work} onChange={(e) => {
          const { agent: _a, reviewer: _r, model_route: _m, ...rest } = stage;
          onChange({ ...rest, work: e.target.value });
        }}>
          {catalog.work.map((w) => <option key={w.key} value={w.key}>{w.key}</option>)}
        </select>
      </label>
      <label>
        Profile
        <select value={stage.profile ?? ""} onChange={(e) => onChange(optional(stage, "profile", e.target.value))}>
          <option value="">None</option>
          {catalog.profiles.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
        </select>
      </label>
      {isAi && (
        <>
          <label>
            Lead agent
            <select value={stage.agent ?? ""} onChange={(e) => onChange(optional(stage, "agent", e.target.value))}>
              <option value="">None</option>
              {catalog.agents.filter((a) => a.kind === "lead").map((a) => <option key={a.key} value={a.key}>{a.key}</option>)}
            </select>
          </label>
          <label>
            Independent reviewer
            <select value={stage.reviewer ?? ""} onChange={(e) => onChange(optional(stage, "reviewer", e.target.value))}>
              <option value="">None</option>
              {catalog.agents.filter((a) => a.kind === "reviewer").map((a) => <option key={a.key} value={a.key}>{a.key}</option>)}
            </select>
          </label>
          {!stage.agent && (
            <label>
              Model route
              <select value={stage.model_route ?? ""} onChange={(e) => onChange(optional(stage, "model_route", e.target.value))}>
                <option value="">Choose…</option>
                {catalog.model_routes.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
          )}
        </>
      )}
      <label>
        Required output keys (comma separated)
        <input value={(stage.output_required_keys ?? []).join(", ")} onChange={(e) => onChange({
          ...stage,
          output_required_keys: e.target.value.split(",").map((k) => k.trim()).filter(Boolean),
        })} />
      </label>
      <fieldset className="stack-sm">
        <legend>Runs after</legend>
        {others.length === 0 && <p className="muted">No other stages yet.</p>}
        {others.map((o) => (
          <label key={o.id} className="check">
            <input type="checkbox" checked={(stage.depends_on ?? []).includes(o.id)} onChange={(e) => onChange({
              ...stage,
              depends_on: e.target.checked
                ? [...(stage.depends_on ?? []), o.id]
                : (stage.depends_on ?? []).filter((d) => d !== o.id),
            })} />
            {o.name || o.id}
          </label>
        ))}
      </fieldset>
      <fieldset className="stack-sm">
        <legend>Human approval gate</legend>
        <p className="muted">Every stage stops here until the required people approve it.</p>
        <label>
          Approval rule
          <select value={policy.type} onChange={(e) => setPolicy({
            ...policy,
            type: e.target.value,
            roles: e.target.value === "single" ? policy.roles.slice(0, 1) : policy.roles,
          })}>
            <option value="single">One role approves</option>
            <option value="any_of">Any listed role approves</option>
            <option value="all_of">Every listed role approves</option>
            <option value="role_based">A number of people approve</option>
            <option value="sequential">Roles approve in order</option>
          </select>
        </label>
        {catalog.roles.map((role) => (
          <label key={role} className="check">
            <input type={policy.type === "single" ? "radio" : "checkbox"} name={`approver-${stage.id}`}
              checked={policy.roles.includes(role)} onChange={(e) => setPolicy({
                ...policy,
                roles: policy.type === "single" ? [role]
                  : e.target.checked ? [...policy.roles, role] : policy.roles.filter((r) => r !== role),
              })} />
            Approver: {role.replace(/_/g, " ")}
          </label>
        ))}
        {policy.type === "role_based" && (
          <label>
            People required
            <input type="number" min={1} max={10} value={policy.minApprovers}
              onChange={(e) => setPolicy({ ...policy, minApprovers: Number(e.target.value) })} />
          </label>
        )}
      </fieldset>
      <fieldset className="stack-sm">
        <legend>Sensors</legend>
        {sensors.map((s, i) => (
          <SensorRow key={s.key} sensor={s} readOnly={readOnly}
            onChange={(next) => onChange({ ...stage, sensors: sensors.map((x, j) => (j === i ? next : x)) })}
            onRemove={() => onChange({ ...stage, sensors: sensors.filter((_, j) => j !== i) })} />
        ))}
        <label>
          Add a sensor
          <select value="" onChange={(e) => e.target.value && onChange({
            ...stage,
            sensors: [...sensors, { key: e.target.value, mandatory: true, config: {} }],
          })}>
            <option value="">Choose…</option>
            {catalog.sensors.filter((s) => !used.has(s.key)).map((s) => <option key={s.key} value={s.key}>{s.key}</option>)}
          </select>
        </label>
      </fieldset>
      <button type="button" className="secondary" onClick={onRemove}>Remove stage</button>
    </fieldset>
  );
}

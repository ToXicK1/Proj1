import { useEffect, useState } from "react";
import { ApiError, api, type RegistryDepartmentDto, type RoutingRuleDto, type StudioCatalogDto } from "../api";
import { Skeleton } from "../components/ui";

const TASKS: [RoutingRuleDto["task"], string][] = [
  ["lead", "Doing the work (lead)"], ["reviewer", "Independent review"], ["specialist", "Support specialists"],
  ["answer", "Answering the owner"], ["triage", "Checking tickets"],
];

/** Who the AI agents are in each department, and which model route each kind of task uses. */
export function RoutingPanel({ orgId, catalog }: { orgId: string; catalog: StudioCatalogDto }) {
  const [registry, setRegistry] = useState<RegistryDepartmentDto[] | null>(null);
  const [rules, setRules] = useState<RoutingRuleDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.agentRegistry(orgId), api.routingPolicies(orgId)])
      .then(([r, p]) => { setRegistry(r.departments); setRules(p.rules); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the agents."));
  }, [orgId]);

  if (error && !rules) return <p role="alert" className="error">{error}</p>;
  if (!registry || !rules) return <Skeleton />;
  const routes = catalog.model_routes;
  const update = (i: number, change: Partial<RoutingRuleDto>) =>
    setRules(rules.map((r, n) => (n === i ? { ...r, ...change } : r)));

  async function save() {
    setError(null);
    setNotice(null);
    try {
      setRules((await api.saveRoutingPolicies(orgId, rules ?? [])).rules);
      setNotice("Routing saved. It applies to the next AI calls, including on running projects.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the routing.");
    }
  }

  return (
    <div className="stack">
      <section className="stack-sm">
        <h2>Routing policies</h2>
        <p className="muted">Without a rule, each agent uses its own model route. A rule for one department wins over a
          rule for every department. An independent review can be required to come from a different provider than the
          work it reviews; if none is available the review stops with a clear reason.</p>
        {rules.length === 0 && <p className="muted">No rules: every agent uses its own route.</p>}
        <ul className="list" aria-label="Routing rules">
          {rules.map((rule, i) => (
            <li key={i} className="actions">
              <label>Task
                <select value={rule.task} onChange={(e) => update(i, {
                  task: e.target.value as RoutingRuleDto["task"],
                  require_different_provider: e.target.value === "reviewer" && rule.require_different_provider })}>
                  {TASKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label>Department
                <select value={rule.profile ?? ""} onChange={(e) => update(i, { profile: e.target.value || null })}>
                  <option value="">Every department</option>
                  {registry.map((d) => <option key={d.profile} value={d.profile}>{d.name}</option>)}
                </select>
              </label>
              <label>Model route
                <select value={rule.route} onChange={(e) => update(i, { route: e.target.value })}>
                  {routes.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              {rule.task === "reviewer" && (
                <label className="check">
                  <input type="checkbox" checked={rule.require_different_provider}
                    onChange={(e) => update(i, { require_different_provider: e.target.checked })} />
                  Must use a different provider
                </label>
              )}
              <button type="button" className="secondary" onClick={() => setRules(rules.filter((_, n) => n !== i))}>
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="actions">
          <button type="button" className="secondary" disabled={routes.length === 0}
            onClick={() => setRules([...rules, { task: "lead", profile: null, route: routes[0], require_different_provider: false }])}>
            Add rule
          </button>
          <button type="button" onClick={() => void save()}>Save routing</button>
        </div>
        {notice && <p role="status" className="notice">{notice}</p>}
        {error && <p role="alert" className="error">{error}</p>}
      </section>

      <section className="stack-sm">
        <h2>Agent registry</h2>
        <p className="muted">Every agent by department. Leads do a step's work and may use read-only tools; reviewers
          check it independently; specialists advise a lead. None of them can approve anything.</p>
        {registry.map((d) => (
          <details key={d.profile}>
            <summary>
              {d.name} · {d.leads.length} leads, {d.reviewers.length} reviewer{d.reviewers.length === 1 ? "" : "s"},{" "}
              {d.specialists.length} specialist{d.specialists.length === 1 ? "" : "s"}
            </summary>
            <div className="table-wrap">
              <table>
                <caption className="sr-only">{d.name} agents</caption>
                <thead>
                  <tr><th scope="col">Agent</th><th scope="col">Kind</th><th scope="col">Version</th>
                    <th scope="col">Route</th><th scope="col">Tools</th></tr>
                </thead>
                <tbody>
                  {[...d.leads, ...d.reviewers, ...d.specialists].map((a) => (
                    <tr key={a.key}>
                      <th scope="row">{a.key}</th><td>{a.kind}</td><td>v{a.version}</td><td>{a.route}</td>
                      <td>{a.tools.length ? a.tools.join(", ") : <span className="muted">none</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))}
      </section>
    </div>
  );
}

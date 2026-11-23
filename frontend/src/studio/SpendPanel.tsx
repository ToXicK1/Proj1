import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type BudgetDto, type ModelRouteDto, type ProjectDto, type SpendDto } from "../api";
import { Skeleton } from "../components/ui";

const money = (usd: number) => `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
const ON_LIMIT: [BudgetDto["on_limit"], string][] = [
  ["pause", "Pause AI work until the limit is raised or the month ends"],
  ["free_only", "Keep going on free providers only (for example a local model)"],
];

/** Monthly budgets, paused providers, prices and what has been spent. Administrators only; enforced on the server. */
export function SpendPanel({ orgId }: { orgId: string }) {
  const [spend, setSpend] = useState<SpendDto | null>(null);
  const [routes, setRoutes] = useState<ModelRouteDto[]>([]);
  const [projects, setProjects] = useState<ProjectDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.spend(orgId), api.modelRoutes(orgId), api.listProjects()])
      .then(([s, r, p]) => { setSpend(s); setRoutes(r.items); setProjects(p.items); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load spending."));
  }, [orgId]);
  useEffect(load, [load]);

  async function act(work: () => Promise<unknown>, done: string) {
    setError(null);
    setNotice(null);
    try {
      await work();
      setNotice(done);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? [e.message, ...(e.problems ?? [])].join(" ") : "That did not work.");
    }
  }

  if (error && !spend) return <p role="alert" className="error">{error}</p>;
  if (!spend) return <Skeleton />;
  const orgBudget = spend.budgets.find((b) => b.project_id === null) ?? null;
  const projectName = (id: string | null) => projects.find((p) => p.id === id)?.name ?? "A project";

  return (
    <div className="stack">
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="notice">{notice}</p>}

      <section className="stack-sm" aria-label="This month">
        <h2>This month</h2>
        <ul className="stats">
          <li><strong>{money(spend.spent_usd)}</strong> spent since {new Date(spend.month_start).toLocaleDateString()}</li>
          {orgBudget && <li className={orgBudget.over ? "stat-blocked" : orgBudget.warned ? "stat-pending" : ""}>
            <strong>{money(orgBudget.limit_usd)}</strong> monthly budget</li>}
          {spend.unpriced_runs > 0 && <li className="stat-pending"><strong>{spend.unpriced_runs}</strong> runs with no
            price entered (not counted)</li>}
        </ul>
        {spend.by_model.length > 0 && (
          <div className="table-wrap">
            <table aria-label="Spend by model">
              <thead><tr><th>Provider</th><th>Model</th><th>Runs</th><th>Input tokens</th><th>From cache</th>
                <th>Output tokens</th><th>Spent</th></tr></thead>
              <tbody>
                {spend.by_model.map((m) => (
                  <tr key={`${m.provider}/${m.model}`}>
                    <td>{m.provider}</td><td>{m.model}</td><td>{m.runs}</td>
                    <td>{m.input_tokens.toLocaleString()}</td><td>{m.cache_read_tokens.toLocaleString()}</td>
                    <td>{m.output_tokens.toLocaleString()}</td><td>{money(m.spent_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="stack-sm" aria-label="Budgets">
        <h2>Budgets</h2>
        <p className="muted">A budget is checked on the server before every AI call. Administrators get a notification
          when spending passes the warning level and again when it reaches the limit. Runs on models with no price
          do not count, so enter a price for every paid model.</p>
        <BudgetForm key={orgBudget?.id ?? "new-org"} title="Whole organization" budget={orgBudget}
          onSave={(b) => act(() => api.saveBudget(orgId, { ...b, project_id: null }), "Organization budget saved.")}
          onRemove={orgBudget ? () => act(() => api.removeBudget(orgId, orgBudget.id), "Budget removed.") : undefined} />
        {spend.budgets.filter((b) => b.project_id !== null).map((b) => (
          <BudgetForm key={b.id} title={projectName(b.project_id)} budget={b}
            onSave={(v) => act(() => api.saveBudget(orgId, { ...v, project_id: b.project_id }), "Project budget saved.")}
            onRemove={() => act(() => api.removeBudget(orgId, b.id), "Budget removed.")} />
        ))}
        <ProjectBudgetAdder projects={projects.filter((p) => !spend.budgets.some((b) => b.project_id === p.id))}
          onAdd={(projectId, v) => act(() => api.saveBudget(orgId, { ...v, project_id: projectId }),
            "Project budget saved.")} />
      </section>

      <section className="stack-sm" aria-label="Provider health">
        <h2>Providers</h2>
        <p className="muted">A provider that runs out of credit is skipped until next month. One whose key is refused
          is skipped until the key is replaced. One that is rate limited or down is skipped for a minute or so. Routes
          then use their next provider. Resume a provider once you have fixed the cause.</p>
        <ul className="list" aria-label="Providers">
          {spend.providers.map((p) => (
            <li key={p.id} className="actions">
              <span><strong>{p.name}</strong> <span className="muted">· {p.adapter_type}</span></span>
              {p.paused
                ? <>
                  <span className="error">Paused: {p.paused_reason}{p.paused_until
                    ? ` (until ${new Date(p.paused_until).toLocaleString()})` : ""}</span>
                  <button type="button" onClick={() => act(() => api.resumeProvider(orgId, p.id),
                    `${p.name} resumed.`)}>Resume</button>
                </>
                : <span className="muted">Available</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="stack-sm" aria-label="Route strategy">
        <h2>Which provider goes first</h2>
        <p className="muted">In order: the route's primary, then its fallbacks. Cheapest first: the cheapest priced
          provider on the route, so expensive models only run when the cheaper ones cannot.</p>
        <ul className="list" aria-label="Routes">
          {routes.map((r) => (
            <li key={r.id} className="actions">
              <label>{r.key} <span className="muted">({1 + r.fallbacks.length} provider{r.fallbacks.length ? "s" : ""})</span>
                <select value={r.strategy} onChange={(e) => act(
                  () => api.setRouteStrategy(orgId, r.id, e.target.value as ModelRouteDto["strategy"]),
                  `Route ${r.key} updated.`)}>
                  <option value="ordered">In order</option>
                  <option value="cheapest">Cheapest first</option>
                </select>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <PriceList spend={spend} onSave={(p) => act(() => api.savePrice(orgId, p), "Price saved.")}
        onRemove={(id) => act(() => api.removePrice(orgId, id), "Price removed; the default applies again.")} />
    </div>
  );
}

type BudgetValues = { limit_usd: number; warn_percent: number; on_limit: BudgetDto["on_limit"] };

function BudgetFields({ value, onChange }: { value: BudgetValues; onChange: (v: BudgetValues) => void }) {
  return (
    <>
      <label>Monthly limit (US dollars)
        <input type="number" min="0.01" step="0.01" value={value.limit_usd || ""}
          onChange={(e) => onChange({ ...value, limit_usd: Number(e.target.value) })} />
      </label>
      <label>Warn at (%)
        <input type="number" min="1" max="100" value={value.warn_percent}
          onChange={(e) => onChange({ ...value, warn_percent: Number(e.target.value) })} />
      </label>
      <label>At the limit
        <select value={value.on_limit} onChange={(e) => onChange({ ...value, on_limit: e.target.value as BudgetDto["on_limit"] })}>
          {ON_LIMIT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
    </>
  );
}

function BudgetForm({ title, budget, onSave, onRemove }: {
  title: string; budget: BudgetDto | null; onSave: (v: BudgetValues) => void; onRemove?: () => void;
}) {
  const [value, setValue] = useState<BudgetValues>({
    limit_usd: budget?.limit_usd ?? 0, warn_percent: budget?.warn_percent ?? 80, on_limit: budget?.on_limit ?? "pause",
  });
  return (
    <fieldset className="stack-sm">
      <legend>{title}{budget && <span className="muted"> · {money(budget.spent_usd)} spent{budget.over
        ? ", limit reached" : budget.warned ? ", past the warning level" : ""}</span>}</legend>
      <div className="actions">
        <BudgetFields value={value} onChange={setValue} />
        <button type="button" disabled={!(value.limit_usd > 0)} onClick={() => onSave(value)}>
          {budget ? "Save" : "Set budget"}</button>
        {onRemove && <button type="button" className="secondary" onClick={onRemove}>Remove</button>}
      </div>
    </fieldset>
  );
}

function ProjectBudgetAdder({ projects, onAdd }: {
  projects: ProjectDto[]; onAdd: (projectId: string, v: BudgetValues) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [value, setValue] = useState<BudgetValues>({ limit_usd: 0, warn_percent: 80, on_limit: "pause" });
  if (projects.length === 0) return null;
  return (
    <fieldset className="stack-sm">
      <legend>Add a project budget</legend>
      <div className="actions">
        <label>Project
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Choose a project</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <BudgetFields value={value} onChange={setValue} />
        <button type="button" disabled={!projectId || !(value.limit_usd > 0)}
          onClick={() => onAdd(projectId, value)}>Add budget</button>
      </div>
    </fieldset>
  );
}

function PriceList({ spend, onSave, onRemove }: {
  spend: SpendDto;
  onSave: (p: { adapter_type: string; model: string; input_usd_per_mtok: number; output_usd_per_mtok: number }) => void;
  onRemove: (id: string) => void;
}) {
  const [draft, setDraft] = useState({ adapter_type: "openai", model: "", input: "", output: "" });
  return (
    <section className="stack-sm" aria-label="Prices">
      <h2>Prices</h2>
      <p className="muted">US dollars per million tokens. Claude prices come from Anthropic's published list; check
        them against your own contract. Enter a price for every other paid model, or its runs are not counted.
        Cache reads are charged at a tenth of the input price and cache writes at 1.25 times, unless you enter
        otherwise.</p>
      <div className="table-wrap">
        <table aria-label="Model prices">
          <thead><tr><th>Provider type</th><th>Model</th><th>Input</th><th>Output</th><th>Cache read</th>
            <th>Source</th><th /></tr></thead>
          <tbody>
            {spend.prices.map((p) => (
              <tr key={`${p.adapter_type}/${p.model}`}>
                <td>{p.adapter_type}</td><td>{p.model}</td><td>{money(p.input_usd_per_mtok)}</td>
                <td>{money(p.output_usd_per_mtok)}</td><td>{money(p.cache_read_usd_per_mtok)}</td>
                <td>{p.source === "organization" ? "Yours" : "Published default"}</td>
                <td>{p.id && <button type="button" className="secondary" onClick={() => onRemove(p.id as string)}>
                  Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions" aria-label="Add or change a price">
        <label>Provider type
          <select value={draft.adapter_type} onChange={(e) => setDraft({ ...draft, adapter_type: e.target.value })}>
            {["anthropic", "openai", "gemini", "openai_compatible"].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label>Model<input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label>
        <label>Input<input type="number" min="0" step="0.01" value={draft.input}
          onChange={(e) => setDraft({ ...draft, input: e.target.value })} /></label>
        <label>Output<input type="number" min="0" step="0.01" value={draft.output}
          onChange={(e) => setDraft({ ...draft, output: e.target.value })} /></label>
        <button type="button" disabled={!draft.model.trim() || draft.input === "" || draft.output === ""}
          onClick={() => onSave({ adapter_type: draft.adapter_type, model: draft.model.trim(),
            input_usd_per_mtok: Number(draft.input), output_usd_per_mtok: Number(draft.output) })}>Save price</button>
      </div>
    </section>
  );
}

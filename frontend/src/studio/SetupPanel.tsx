import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api, type ProviderDto, type StudioCatalogDto } from "../api";

export function SetupPanel({ orgId, catalog, onCatalogChange }: {
  orgId: string; catalog: StudioCatalogDto; onCatalogChange: () => void;
}) {
  const [providers, setProviders] = useState<ProviderDto[]>([]);
  const [name, setName] = useState("");
  const [adapter, setAdapter] = useState("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [providerId, setProviderId] = useState("");
  const [routeKey, setRouteKey] = useState("");
  const [model, setModel] = useState("");
  const [route, setRoute] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => api.studioProviders(orgId).then((r) => {
    setProviders(r.items);
    setProviderId((p) => p || r.items[0]?.id || "");
  }), [orgId]);
  useEffect(() => { load().catch(() => setError("Could not load AI connections.")); }, [load]);
  const chosenRoute = route || catalog.model_routes[0] || "";

  async function run(work: () => Promise<unknown>, done: string): Promise<boolean> {
    setError(null);
    setNotice(null);
    try {
      await work();
      await load();
      onCatalogChange();
      setNotice(done);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.");
      return false;
    }
  }

  function addProvider(e: FormEvent) {
    e.preventDefault();
    void run(() => api.createProvider(orgId, { name: name.trim(), adapter_type: adapter, base_url: baseUrl.trim() || null,
      api_key: apiKey || null }), `Connection ${name.trim()} added.`).then((ok) => {
      setApiKey("");
      if (ok) { setName(""); setBaseUrl(""); }
    });
  }

  return (
    <div className="stack">
      {notice && <p role="status" className="notice">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      <section className="stack-sm">
        <h2>AI connections</h2>
        <ul className="list">{providers.map((p) => <li key={p.id}>{p.name} <span className="muted">· {p.adapter_type}</span></li>)}</ul>
        {providers.length === 0 && <p className="muted">None yet.</p>}
        <form className="stack-sm" onSubmit={addProvider} autoComplete="off">
          <label>Connection name<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>
            Connection type
            <select value={adapter} onChange={(e) => setAdapter(e.target.value)}>
              <option value="openai_compatible">OpenAI-compatible server (for example Ollama)</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Google Gemini</option>
              <option value="mock">Offline test connection</option>
            </select>
          </label>
          <label>Server address<input value={baseUrl} placeholder="http://host.docker.internal:11434/v1" onChange={(e) => setBaseUrl(e.target.value)} /></label>
          <label>API key (stored encrypted, never shown again)<input type="password" value={apiKey} autoComplete="new-password" onChange={(e) => setApiKey(e.target.value)} /></label>
          <button type="submit">Add connection</button>
        </form>
      </section>
      <form className="stack-sm" onSubmit={(e) => {
        e.preventDefault();
        void run(() => api.createRoute(orgId, routeKey.trim(), providerId, model.trim()), `Model route ${routeKey.trim()} added.`)
          .then((ok) => { if (ok) { setRoute(routeKey.trim()); setRouteKey(""); setModel(""); } });
      }}>
        <h2>Model routes</h2>
        <ul className="list">{catalog.model_routes.map((r) => <li key={r}>{r}</li>)}</ul>
        <label>Route key<input required value={routeKey} onChange={(e) => setRouteKey(e.target.value)} /></label>
        <label>
          Connection
          <select required value={providerId} onChange={(e) => setProviderId(e.target.value)}>
            {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label>Model name<input required value={model} onChange={(e) => setModel(e.target.value)} /></label>
        <div className="actions">
          <button type="submit" disabled={!providerId}>Add route</button>
          <button type="button" className="secondary" disabled={!providerId || !model.trim()}
            onClick={() => void run(async () => {
              const result = await api.testProvider(orgId, providerId, model.trim());
              if (!result.ok) throw new ApiError(502, "connection_failed", "The connection did not answer.");
            }, "The connection answered.")}>Test connection</button>
        </div>
      </form>
      <section className="stack-sm">
        <h2>Delivery team</h2>
        <p className="muted">The six professional profiles and the ready-made lifecycle are already set up. Use this only to add anything missing on a chosen route.</p>
        <label>
          Team model route
          <select value={chosenRoute} onChange={(e) => setRoute(e.target.value)}>
            {catalog.model_routes.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button type="button" disabled={!chosenRoute}
          onClick={() => void run(() => api.setupDeliveryTeam(orgId, chosenRoute), "Your delivery team is ready.")}>Check delivery team</button>
      </section>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { api, type OrgDto, type StudioCatalogDto } from "../api";
import { HooksPanel, ProfilesPanel, RulesPanel, SensorsPanel } from "../studio/ConfigPanels";
import { WorkflowsPanel } from "../studio/WorkflowsPanel";

const TABS = ["Workflows", "Profiles and agents", "Rules", "Hooks", "Sensors"] as const;
type Tab = (typeof TABS)[number];

export function StudioPage() {
  const [orgs, setOrgs] = useState<OrgDto[] | null>(null);
  const [orgId, setOrgId] = useState("");
  const [catalog, setCatalog] = useState<StudioCatalogDto | null>(null);
  const [tab, setTab] = useState<Tab>("Workflows");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listOrgs().then((r) => {
      const admin = r.items.filter((o) => o.role === "org_admin");
      setOrgs(admin);
      setOrgId(admin[0]?.id ?? "");
    }).catch(() => setError("Could not load your organizations."));
  }, []);

  const loadCatalog = useCallback(async () => {
    if (orgId) setCatalog(await api.studioCatalog(orgId));
  }, [orgId]);

  useEffect(() => {
    setCatalog(null);
    loadCatalog().catch(() => setError("Could not load the studio."));
  }, [loadCatalog]);

  if (error) return <p role="alert" className="error">{error}</p>;
  if (orgs === null) return <p className="muted">Loading…</p>;
  if (orgs.length === 0) return <p className="muted">Only organization administrators can use the studio.</p>;
  const props = catalog ? { orgId, catalog, onCatalogChange: () => void loadCatalog() } : null;

  return (
    <section className="card stack">
      <h1>Workflow Studio</h1>
      {orgs.length > 1 && (
        <label>
          Organization
          <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>
      )}
      <div className="tabs" role="tablist" aria-label="Studio sections">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t}
            className={tab === t ? "tab selected" : "tab"} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {!props && <p className="muted">Loading…</p>}
      {props && (
        <div role="tabpanel" aria-label={tab} key={orgId}>
          {tab === "Workflows" && <WorkflowsPanel orgId={orgId} catalog={props.catalog} />}
          {tab === "Profiles and agents" && <ProfilesPanel {...props} />}
          {tab === "Rules" && <RulesPanel {...props} />}
          {tab === "Hooks" && <HooksPanel {...props} />}
          {tab === "Sensors" && <SensorsPanel catalog={props.catalog} />}
        </div>
      )}
    </section>
  );
}

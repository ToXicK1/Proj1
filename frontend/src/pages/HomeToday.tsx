import { Link } from "react-router-dom";
import { Panel, StatusPill } from "../components/ui";
import type { MyDayDto } from "../api";
import { PROFILES } from "../portal/roles";
import { DEPARTMENT_PATH } from "../workspace/modules";

// Home's "today" panels: what waits on this person across their projects. Each item links to where it is handled:
// change sets to the IDE's review, packages to the department, tickets and conversations to the project.

const dept = (key: string) => PROFILES.find(([k]) => k === key)?.[1] ?? key;
const project = (id: string) => `/projects/${encodeURIComponent(id)}`;
const when = (iso: string) => new Date(iso).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });

export function todayCount(day: MyDayDto | null): number {
  if (!day) return 0;
  return day.change_sets.length + day.packages.length + day.tickets.length + day.messages.length;
}

export function HomeToday({ day }: { day: MyDayDto }) {
  return (
    <>
      {day.change_sets.length > 0 && (
        <Panel title="Change sets to review" aside={<StatusPill label={`${day.change_sets.length} open`} tone="pending" />}>
          <ul className="rows">
            {day.change_sets.map((c) => (
              <li key={c.id} className="row-item">
                <span className="row-main">
                  <Link to={`${project(c.project_id)}/ide?change_set=${encodeURIComponent(c.id)}`}>#{c.number} {c.title}</Link>
                  <span className="muted">{c.project} · {c.branch}{c.by_ai ? " · written by the Developer AI" : ""}</span>
                </span>
                <StatusPill label="In review" />
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {day.packages.length > 0 && (
        <Panel title="Packages waiting for a decision" aside={<StatusPill label={`${day.packages.length}`} tone="pending" />}>
          <ul className="rows">
            {day.packages.map((p) => (
              <li key={p.id} className="row-item">
                <span className="row-main">
                  <Link to={`${project(p.project_id)}/work/${DEPARTMENT_PATH[p.department] ?? ""}`}>{p.title}</Link>
                  <span className="muted">{p.project} · {dept(p.department)} · package {p.number}</span>
                </span>
                <StatusPill label="Submitted" />
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {day.tickets.length > 0 && (
        <Panel title="Tickets" aside={<span className="muted">{day.tickets.length}</span>}>
          <ul className="rows">
            {day.tickets.map((t) => (
              <li key={t.id} className="row-item">
                <span className="row-main">
                  <Link to={`${project(t.project_id)}?tab=Tickets`}>#{t.number} {t.title}</Link>
                  <span className="muted">{t.project} · {dept(t.department)} · {t.assigned_to_me ? "assigned to you" : "unassigned in your department"}</span>
                </span>
                <StatusPill label={t.status === "open" ? "Open" : "Needs a professional"} tone="pending" />
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {day.messages.length > 0 && (
        <Panel title="Messages for you" aside={<span className="muted">last 7 days</span>}>
          <ul className="rows">
            {day.messages.map((m) => (
              <li key={m.id} className="row-item">
                <span className="row-main">
                  {m.project_id
                    ? <Link to={`${project(m.project_id)}?tab=Conversations`}>{m.author}{m.direct ? " (to you)" : ` in ${dept(m.channel)}`}</Link>
                    : <Link to="/team-chat">{m.author}{m.direct ? " (to you)" : ""}</Link>}
                  <span className="muted clamp">{m.project ? `${m.project} · ` : ""}{m.body}</span>
                </span>
                <span className="muted">{when(m.created_at)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {day.ai_updates.length > 0 && (
        <Panel title="What the AI finished" aside={<span className="muted">last 3 days</span>}>
          <ul className="rows">
            {day.ai_updates.map((u, i) => (
              <li key={`${u.subject}-${i}`} className="row-item">
                <span className="row-main">
                  <Link to={`${project(u.project_id)}/ide`}>Developer AI on {String(u.data.branch ?? "its branch")}</Link>
                  <span className="muted">{u.project} · {String(u.data.status ?? "").replace("_", " ")}</span>
                </span>
                <span className="muted">{when(u.created_at)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {day.notifications.unread > 0 && (
        <Panel title="Notifications" aside={<Link to="/notifications">{day.notifications.unread} unread</Link>}>
          <ul className="rows">
            {day.notifications.latest.map((n) => (
              <li key={n.id} className="row-item"><span className="row-main"><span>{n.message}</span></span>
                <span className="muted">{when(n.created_at)}</span></li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}

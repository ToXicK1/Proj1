import { useEffect, useRef, useState } from "react";
import { request } from "../api";

/** One workspace event (Phase 1d): identifiers and a short summary; the owning screens load the details. */
export interface WorkspaceEventDto {
  id: number; kind: string; subject: string; actor: string; data: Record<string, unknown>; at: string | null;
}

export type Connection = "connecting" | "live" | "reconnecting" | "offline";

const MAX_KEPT = 100;

function socketUrl(projectId: string, after: number): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/v1/projects/${encodeURIComponent(projectId)}/events/ws?after=${after}`;
}

/** Follows a project's live workspace events over a WebSocket. It catches up from the last event it saw after every
 * reconnect (REST first, then the socket resumes from there), backs off on failure, and stops when the server closes
 * the socket for policy reasons (signed out, or not on the project's team). */
export function useWorkspaceEvents(projectId: string, enabled = true): { events: WorkspaceEventDto[]; connection: Connection } {
  const [events, setEvents] = useState<WorkspaceEventDto[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const last = useRef(0);

  useEffect(() => {
    if (!enabled || !projectId || typeof WebSocket === "undefined") { setConnection("offline"); return undefined; }
    let socket: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let timer: number | undefined;
    const keep = (items: WorkspaceEventDto[]) => {
      if (!items.length) return;
      last.current = Math.max(last.current, items[items.length - 1].id);
      setEvents((old) => [...old, ...items.filter((e) => !old.some((o) => o.id === e.id))].slice(-MAX_KEPT));
    };
    const open = async () => {
      if (stopped) return;
      try {  // catch up over REST, so nothing is missed while the socket was down
        const page = await request<{ items: WorkspaceEventDto[]; last: number }>(
          "GET", `/api/v1/projects/${encodeURIComponent(projectId)}/events?after=${last.current}`);
        keep(page.items);
      } catch { /* the socket will say whether we may follow */ }
      if (stopped) return;
      socket = new WebSocket(socketUrl(projectId, last.current));
      socket.onopen = () => { attempt = 0; setConnection("live"); };
      socket.onmessage = (message) => {
        try {
          const body = JSON.parse(String(message.data)) as { type: string; items: WorkspaceEventDto[] };
          if (body.type === "events") keep(body.items);
        } catch { /* ignore anything that is not an event batch */ }
      };
      socket.onclose = (closed) => {
        if (stopped) return;
        if (closed.code === 1008) { setConnection("offline"); return; }  // not allowed: do not keep retrying
        setConnection("reconnecting");
        attempt += 1;
        timer = window.setTimeout(() => void open(), Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5)));
      };
    };
    void open();
    return () => { stopped = true; window.clearTimeout(timer); socket?.close(); };
  }, [projectId, enabled]);

  return { events, connection };
}

const LABELS: Record<string, string> = {
  "execution.queued": "Execution queued", "execution.started": "Execution started",
  "execution.finished": "Execution finished", "repository.created": "Repository created",
  "repository.committed": "Commit", "change_set.opened": "Change set opened",
  "change_set.approved": "Change set approved", "change_set.changes_requested": "Changes requested on a change set",
  "change_set.merged": "Change set merged", "terminal.opened": "Terminal opened", "terminal.closed": "Terminal closed",
  "developer_ai.requested": "Developer AI asked", "developer_ai.step": "Developer AI",
  "developer_ai.committed": "Developer AI committed", "developer_ai.checked": "Developer AI built and tested",
  "developer_ai.finished": "Developer AI finished", "developer_ai.cancelled": "Developer AI cancelled",
};

export function ConnectionStatus({ connection }: { connection: Connection }) {
  const text = { connecting: "Connecting…", live: "Live", reconnecting: "Reconnecting…", offline: "Not live" }[connection];
  // A note, not a status region: the page's own status messages stay the only "status" (screen readers and tests).
  return <span className={`connection connection-${connection}`} role="note" aria-label={`Live updates: ${text}`}>{text}</span>;
}

/** The workspace's live activity: what is happening in this project's workspaces right now. */
export function LiveActivity({ events }: { events: WorkspaceEventDto[] }) {
  return (
    <section className="stack-sm" aria-label="Live activity">
      <h3>Live activity</h3>
      {events.length === 0 ? <p className="muted small">Nothing yet. New activity appears here as it happens.</p> : (
        <ul className="list small">
          {[...events].reverse().slice(0, 15).map((e) => (
            <li key={e.id}>
              <strong>{LABELS[e.kind] ?? e.kind}</strong>
              {typeof e.data.status === "string" && <> · {e.data.status.replace(/_/g, " ")}</>}
              {typeof e.data.text === "string" && e.data.text && <> · {e.data.text}</>}
              {typeof e.data.summary === "string" && e.data.summary && <> · {e.data.summary}</>}
              {typeof e.data.branch === "string" && <> · {e.data.branch}</>}
              {typeof e.data.commit === "string" && <> · <code>{e.data.commit.slice(0, 7)}</code></>}
              {e.at && <span className="muted"> · {new Date(e.at).toLocaleTimeString()}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

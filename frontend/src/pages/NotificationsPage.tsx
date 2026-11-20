import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type NotificationDto } from "../api";
import { EmptyState, Icon, PageHeader, Skeleton } from "../components/ui";

export function NotificationsPage() {
  const [items, setItems] = useState<NotificationDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.notifications().then((r) => setItems(r.items)), []);
  useEffect(() => { load().catch(() => setError("Could not load your notifications.")); }, [load]);
  const unread = items?.filter((n) => !n.read).length ?? 0;

  return (
    <section className="page narrow-column">
      <PageHeader title="Notifications" meta={items ? (unread ? `${unread} unread` : "You are all caught up.") : undefined} />
      {error && <p role="alert" className="error">{error}</p>}
      {!items && !error && <Skeleton title={false} />}
      {items?.length === 0 && <EmptyState title="Nothing here yet.">Approvals, mentions and direct messages show up here.</EmptyState>}
      {items && items.length > 0 && (
        <ul className="rows panel">
          {items.map((n) => (
            <li key={n.id} className={n.read ? "row-item notification" : "row-item notification unread"}>
              <span className="notification-icon" aria-hidden="true"><Icon name={n.project_id ? "folder" : "chat"} /></span>
              <Link className="row-main" to={n.project_id ? `/projects/${n.project_id}` : "/team-chat"}
                onClick={() => { if (!n.read) void api.readNotification(n.id); }}>
                {n.read ? n.message : <strong>{n.message}</strong>}
              </Link>
              {!n.read && (
                <button type="button" className="secondary small" aria-label={`Mark as read: ${n.message}`}
                  onClick={() => void api.readNotification(n.id).then(load)}>Mark as read</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type NotificationDto } from "../api";

export function NotificationsPage() {
  const [items, setItems] = useState<NotificationDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.notifications().then((r) => setItems(r.items)), []);
  useEffect(() => { load().catch(() => setError("Could not load your notifications.")); }, [load]);

  return (
    <section className="card">
      <h1>Notifications</h1>
      {error && <p role="alert" className="error">{error}</p>}
      {items?.length === 0 && <p className="muted">You are all caught up.</p>}
      <ul className="list">
        {items?.map((n) => (
          <li key={n.id} className="row">
            <Link to={`/projects/${n.project_id}`} onClick={() => { if (!n.read) void api.readNotification(n.id); }}>
              {n.read ? n.message : <strong>{n.message}</strong>}
            </Link>
            {!n.read && (
              <button type="button" className="secondary" aria-label={`Mark as read: ${n.message}`}
                onClick={() => void api.readNotification(n.id).then(load)}>Mark as read</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

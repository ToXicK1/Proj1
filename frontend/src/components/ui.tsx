import type { ReactNode } from "react";

export type Tone = "success" | "warning" | "error" | "info" | "blocked" | "pending" | "progress" | "neutral";

const TONES: Record<string, Tone> = {
  approved: "success",
  completed: "success",
  passed: "success",
  "you told us": "success",
  "in progress": "progress",
  "awaiting review": "pending",
  "waiting for owner": "pending",
  "awaiting user input": "pending",
  "needs your answer": "pending",
  "changes requested": "warning",
  assumption: "warning",
  unclear: "warning",
  open: "warning",
  triaged: "info",
  in_progress: "progress",
  resolved: "success",
  blocked: "blocked",
  rejected: "error",
  failed: "error",
  "not started": "neutral",
};

/** One status label with a conventional, accessible colour. Brand colours are never used for status. */
export function StatusPill({ label, tone }: { label: string; tone?: Tone }) {
  const resolved = tone ?? TONES[label.toLowerCase()] ?? "neutral";
  return <span className={`pill pill-${resolved}`}>{label}</span>;
}

export type Identity = "ai" | "human" | "system";

const IDENTITY_NAMES: Record<Identity, string> = { ai: "AI", human: "Person", system: "System" };

/** Marks who did something: purple for AI, forest green for people, neutral for automated events. */
export function IdentityTag({ kind, children }: { kind: Identity; children?: ReactNode }) {
  return (
    <span className={`identity identity-${kind}`}>
      <span className="identity-dot" aria-hidden="true" />
      <span className="identity-kind">{IDENTITY_NAMES[kind]}</span>
      {children && <span className="identity-name">{children}</span>}
    </span>
  );
}


/** A loading placeholder shaped like the content it stands in for. Marked busy for screen readers. */
export function Skeleton({ lines = 3, title = true }: { lines?: number; title?: boolean }) {
  return (
    <div className="stack-sm" aria-busy="true" aria-label="Loading">
      {title && <span className="skeleton skeleton-title" />}
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton skeleton-line" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

/** Shows that a page refreshes itself, and when it last did. */
export function LiveIndicator({ updated }: { updated: Date | null }) {
  return (
    <span className="live">
      <span className="live-dot" aria-hidden="true" />
      {updated ? `Live · updated ${updated.toLocaleTimeString()}` : "Live"}
    </span>
  );
}

/* Layout building blocks ------------------------------------------------------------------------------------------ */

const ICONS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  folder: "M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  chat: "M4 5h16v11H8l-4 4z",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.5a4 4 0 0 1 0 7.5M22 21v-1a6 6 0 0 0-4-5.6",
  flow: "M5 3h4v4H5zM15 17h4v4h-4zM7 7v5a2 2 0 0 0 2 2h6a2 2 0 0 1 2 2v1",
  logout: "M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 8l-4 4 4 4M6 12h11",
  plus: "M12 5v14M5 12h14",
  menu: "M4 6h16M4 12h16M4 18h16",
  sidebar: "M4 4h16v16H4zM9 4v16",
  arrow: "M15 18l-6-6 6-6",
  workspace: "M3 4h18v12H3zM8 20h8M12 16v4M7 8l3 2-3 2M12 12h4",
};

/** A small line icon. Decorative: the text next to it carries the meaning. */
export function Icon({ name }: { name: keyof typeof ICONS | string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={ICONS[name] ?? ""} />
    </svg>
  );
}

export function initials(name: string): string {
  const words = name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

/** A person's initials in a circle; purple for AI, green for people. The name is said in text elsewhere. */
export function Avatar({ name, kind = "human", size = "md" }: { name: string; kind?: Identity; size?: "sm" | "md" }) {
  return <span className={`avatar avatar-${kind} avatar-${size}`} aria-hidden="true">{kind === "ai" ? "AI" : initials(name)}</span>;
}

/** The top of every page: where you are, what it is, and the main actions. */
export function PageHeader({ eyebrow, title, meta, actions, children }: {
  eyebrow?: ReactNode; title: ReactNode; meta?: ReactNode; actions?: ReactNode; children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-main">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {meta && <p className="page-meta">{meta}</p>}
        {children}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </header>
  );
}

/** A titled block of a page. Panels are quiet surfaces; plain sections have no box at all. */
export function Panel({ title, aside, children, label, plain = false }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; label?: string; plain?: boolean;
}) {
  return (
    <section className={plain ? "panel plain" : "panel"} aria-label={label}>
      {(title || aside) && <div className="panel-head">{title && <h2>{title}</h2>}{aside}</div>}
      {children}
    </section>
  );
}

/** What to show when there is nothing yet, and what to do about it. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

/** "5 min ago", "yesterday", or a date. The exact time is in the title for anyone who needs it. */
export function When({ at }: { at: string }) {
  const date = new Date(at);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  let text: string;
  if (Number.isNaN(seconds)) return null;
  if (seconds < 60) text = "just now";
  else if (seconds < 3600) text = `${Math.floor(seconds / 60)} min ago`;
  else if (seconds < 86400) text = `${Math.floor(seconds / 3600)} h ago`;
  else if (seconds < 172800) text = "yesterday";
  else text = date.toLocaleDateString();
  return <time className="when" dateTime={date.toISOString()} title={date.toLocaleString()}>{text}</time>;
}

import type { ReactNode } from "react";

export type Tone = "success" | "warning" | "error" | "info" | "blocked" | "pending" | "progress" | "neutral";

const TONES: Record<string, Tone> = {
  approved: "success",
  completed: "success",
  passed: "success",
  "you told us": "success",
  "in progress": "progress",
  "awaiting review": "pending",
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

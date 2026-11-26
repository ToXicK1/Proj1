// The IDE's open tabs, unsaved edits included, kept in this browser tab's session storage (never sent anywhere), so
// that leaving the IDE for a platform page such as the Codebase Explorer and coming back keeps them.

export interface Tab { path: string; ref: string; original: string; value: string }

const SAFE_BRANCH = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$/;

export interface Saved { branch: string; tabs: Tab[]; active: string | null }
export const savedKey = (projectId: string) => `aidlc.ide.${projectId}`;

/** The IDE's open tabs, unsaved edits included, kept in this browser tab's session so that leaving the IDE (for the
 * Codebase Explorer, say) and coming back keeps them. Never sent anywhere. */
export function readSaved(projectId: string): Saved | null {
  try {
    const raw = window.sessionStorage.getItem(savedKey(projectId));
    const data = raw ? JSON.parse(raw) as Saved : null;
    return data && typeof data.branch === "string" && Array.isArray(data.tabs) ? data : null;
  } catch { return null; }
}

/** Where the IDE starts: the branch asked for in the link, unless that would hide unsaved edits on another branch. */
export function startingPoint(saved: Saved | null, askedBranch: string | null): { branch: string; tabs: Tab[]; active: string | null; blocked: boolean } {
  const asked = askedBranch && SAFE_BRANCH.test(askedBranch) && !askedBranch.includes("..") ? askedBranch : null;
  const dirty = saved?.tabs.some((t) => t.value !== t.original) ?? false;
  if (saved && (!asked || asked === saved.branch || dirty)) {
    return { branch: saved.branch, tabs: saved.tabs, active: saved.active, blocked: Boolean(asked && asked !== saved.branch) };
  }
  return { branch: asked ?? "main", tabs: [], active: null, blocked: false };
}


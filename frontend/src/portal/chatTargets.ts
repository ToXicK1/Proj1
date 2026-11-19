/** Reading "@name" and "@everyone" out of what someone types, the way an in-game chat does. */
export interface Who {
  user_id: string;
  name: string;
}

export type Target = Who | "everyone";

const boundary = (ch: string | undefined) => ch === undefined || /[\s,.:;!?]/.test(ch);

/** The person named right after "@" at `at`, preferring the longest full name, then a unique first name. */
function nameAt(text: string, at: number, people: Who[]): { who: Target; length: number } | null {
  const after = text.slice(at + 1);
  const lower = after.toLowerCase();
  if (lower.startsWith("everyone") && boundary(after[8])) return { who: "everyone", length: 9 };
  const full = [...people].sort((a, b) => b.name.length - a.name.length)
    .find((p) => lower.startsWith(p.name.toLowerCase()) && boundary(after[p.name.length]));
  if (full) return { who: full, length: full.name.length + 1 };
  const word = /^[^\s,.:;!?@]+/.exec(after)?.[0]?.toLowerCase();
  if (!word) return null;
  const byFirst = people.filter((p) => p.name.toLowerCase().split(/\s+/)[0] === word);
  return byFirst.length === 1 ? { who: byFirst[0], length: word.length + 1 } : null;
}

/** A message that starts with @name or @everyone switches who the chat goes to; the rest is the message. */
export function leadingTarget(text: string, people: Who[]): { target: Target | null; rest: string } {
  const trimmed = text.trimStart();
  if (!trimmed.startsWith("@")) return { target: null, rest: text.trim() };
  const found = nameAt(trimmed, 0, people);
  if (!found) return { target: null, rest: text.trim() };
  return { target: found.who, rest: trimmed.slice(found.length).trim() };
}

/** Everyone named with @ anywhere in a message, for department discussions where @name notifies. */
export function mentionsIn(text: string, people: Who[]): Who[] {
  const out = new Map<string, Who>();
  for (let i = text.indexOf("@"); i !== -1; i = text.indexOf("@", i + 1)) {
    if (i > 0 && !boundary(text[i - 1])) continue; // an email address, not a mention
    const found = nameAt(text, i, people);
    if (found && found.who !== "everyone") out.set(found.who.user_id, found.who);
  }
  return [...out.values()];
}

/** Suggestions while someone is typing a name after "@" at the end of the text. */
export function suggestions(text: string, people: Who[], everyone: boolean): { label: string; insert: string }[] {
  const match = /(^|\s)@([^@]{0,40})$/.exec(text);
  if (!match) return [];
  const query = match[2].toLowerCase();
  if (people.some((p) => p.name.toLowerCase() === query.trimEnd())) return [];
  const start = text.length - match[2].length - 1;
  const list = [
    ...(everyone ? [{ label: "@everyone", name: "everyone" }] : []),
    ...people.map((p) => ({ label: `@${p.name}`, name: p.name })),
  ].filter((o) => o.name.toLowerCase().startsWith(query) || o.name.toLowerCase().split(/\s+/).some((w) => w.startsWith(query)));
  return list.slice(0, 6).map((o) => ({ label: o.label, insert: `${text.slice(0, start)}@${o.name} ` }));
}

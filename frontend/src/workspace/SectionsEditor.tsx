import { useState } from "react";

/** A BRD, SRS or other document: an outline of sections, each with a heading and text. Requirement keys such as
 * REQ-004 in the text are shown as links to those records. */
export interface Section { heading: string; content: string }

export function asSections(value: unknown): Section[] {
  return Array.isArray(value)
    ? value.filter((s) => s && typeof s === "object").map((s) => ({
      heading: String((s as Section).heading ?? ""), content: String((s as Section).content ?? "") }))
    : [];
}

export function SectionsEditor({ value, onChange }: { value: unknown; onChange: (sections: Section[]) => void }) {
  const [sections, setSections] = useState<Section[]>(asSections(value).length ? asSections(value) : [{ heading: "", content: "" }]);
  const [open, setOpen] = useState(0);
  const update = (next: Section[]) => { setSections(next); onChange(next.filter((s) => s.heading.trim() || s.content.trim())); };
  const move = (i: number, by: number) => {
    const next = [...sections];
    const [item] = next.splice(i, 1);
    next.splice(i + by, 0, item);
    update(next);
    setOpen(i + by);
  };
  return (
    <div className="sections-editor">
      <nav aria-label="Document outline" className="stack-sm">
        {sections.map((s, i) => (
          <button key={i} type="button" className={i === open ? "nav-link active" : "nav-link"} onClick={() => setOpen(i)}>
            {i + 1}. {s.heading || "Untitled section"}</button>
        ))}
        <button type="button" className="secondary" onClick={() => { update([...sections, { heading: "", content: "" }]); setOpen(sections.length); }}>
          Add section</button>
      </nav>
      {sections[open] && (
        <div className="stack-sm">
          <label>Section heading<input value={sections[open].heading}
            onChange={(e) => update(sections.map((s, i) => (i === open ? { ...s, heading: e.target.value } : s)))} /></label>
          <label>Text <span className="muted small">(refer to records by key, for example REQ-004)</span>
            <textarea rows={10} value={sections[open].content}
              onChange={(e) => update(sections.map((s, i) => (i === open ? { ...s, content: e.target.value } : s)))} /></label>
          <div className="actions">
            <button type="button" className="secondary" disabled={open === 0} onClick={() => move(open, -1)}>Move up</button>
            <button type="button" className="secondary" disabled={open === sections.length - 1} onClick={() => move(open, 1)}>Move down</button>
            <button type="button" className="secondary" disabled={sections.length === 1} onClick={() => {
              update(sections.filter((_, i) => i !== open)); setOpen(Math.max(0, open - 1));
            }}>Remove section</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The document as Markdown, for export. */
export function toMarkdown(title: string, sections: Section[]): string {
  return [`# ${title}`, "", ...sections.flatMap((s) => [`## ${s.heading}`, "", s.content, ""])].join("\n");
}

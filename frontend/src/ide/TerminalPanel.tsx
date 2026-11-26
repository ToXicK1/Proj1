import "@xterm/xterm/css/xterm.css";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, request } from "../api";

// The IDE terminal (Phase 2d). The shell runs in its own locked-down container in the executor (no network, the
// branch checked out as a throwaway working copy), never on the API server. The browser only relays keystrokes and
// output through the API, which checks the person and the session. Every submitted line is recorded.

interface SessionDto { id: string; branch: string; status: string; end_reason: string | null }
type State = "idle" | "opening" | "preparing" | "ready" | "closed";

const base = (p: string) => `/api/v1/projects/${encodeURIComponent(p)}/terminal`;
const socketUrl = (p: string, id: string) =>
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${base(p)}/${encodeURIComponent(id)}/ws`;

export function TerminalPanel({ projectId, branch, visible }: { projectId: string; branch: string; visible: boolean }) {
  const host = useRef<HTMLDivElement | null>(null);
  const term = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const [state, setState] = useState<State>("idle");
  const [note, setNote] = useState("");
  const [session, setSession] = useState<SessionDto | null>(null);

  const resize = useCallback(() => {
    if (!fit.current || !term.current || !host.current?.offsetParent) return;
    try { fit.current.fit(); } catch { return; }
    const s = socket.current;
    if (s?.readyState === WebSocket.OPEN) s.send(JSON.stringify({ type: "resize", cols: term.current.cols, rows: term.current.rows }));
  }, []);

  useEffect(() => () => { socket.current?.close(); term.current?.dispose(); }, []);
  useEffect(() => {
    if (!visible) return undefined;
    const t = window.setTimeout(resize, 30);
    window.addEventListener("resize", resize);
    return () => { window.clearTimeout(t); window.removeEventListener("resize", resize); };
  }, [visible, resize, state]);

  const open = async () => {
    setState("opening"); setNote("");
    let made: SessionDto;
    try {
      made = await request<SessionDto>("POST", base(projectId), { branch });
    } catch (e) {
      setState("idle"); setNote(e instanceof ApiError ? e.message : "Could not open a terminal"); return;
    }
    setSession(made);
    if (!term.current && host.current) {
      const t = new Terminal({ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 13, cursorBlink: true,
        theme: { background: "#1e1e1e", foreground: "#d4d4d4" }, scrollback: 5000 });
      const f = new FitAddon();
      t.loadAddon(f);
      t.open(host.current);
      t.onData((data) => {
        const s = socket.current;
        if (s?.readyState === WebSocket.OPEN) s.send(JSON.stringify({ type: "input", data }));
      });
      term.current = t; fit.current = f;
    }
    term.current?.reset();
    setState("preparing");
    const s = new WebSocket(socketUrl(projectId, made.id));
    socket.current = s;
    s.onmessage = (event) => {
      let body: { type?: string; data?: string; text?: string };
      try { body = JSON.parse(String(event.data)); } catch { return; }
      if (body.type === "output" && body.data) term.current?.write(body.data);
      else if (body.type === "status" && body.text === "ready") { setState("ready"); resize(); term.current?.focus(); }
      else if (body.type === "status" && body.text) term.current?.writeln(`\x1b[90m${body.text}\x1b[0m`);
    };
    s.onclose = (event) => {
      if (socket.current !== s) return;
      setState("closed");
      setNote(event.code === 1008 ? "The terminal was refused (sign in again, or open a new one)." : event.reason || "The terminal session ended.");
      term.current?.writeln("\r\n\x1b[90m[session ended — the container and its working copy were removed]\x1b[0m");
    };
  };

  const close = () => { socket.current?.close(); };
  const running = state === "preparing" || state === "ready";

  return (
    <div className="ide-terminal" hidden={!visible}>
      <div className="ide-terminal-bar">
        {running ? (
          <>
            <span className="ide-hint">{state === "ready" ? `bash on ${session?.branch} · isolated container, no network · input recorded` : "Preparing…"}</span>
            <button type="button" onClick={close}>End session</button>
          </>
        ) : (
          <>
            <span className="ide-hint">{note || `A shell on a throwaway checkout of ${branch}, in its own container with no network. Commit from the editor.`}</span>
            <button type="button" onClick={() => void open()} disabled={state === "opening"}>
              {state === "opening" ? "Opening…" : state === "closed" ? "New terminal" : "Open terminal"}</button>
          </>
        )}
      </div>
      <div ref={host} className="ide-terminal-screen" aria-label="Terminal" />
    </div>
  );
}

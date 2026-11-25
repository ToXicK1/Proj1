import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWorkspaceEvents } from "./liveEvents";

class FakeSocket {
  static made: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((c: { code: number }) => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeSocket.made.push(this); }
  close() { this.closed = true; }
}

const event = (id: number, kind: string) => ({ id, kind, subject: "s", actor: "executor", data: {}, at: null });

describe("useWorkspaceEvents", () => {
  beforeEach(() => {
    FakeSocket.made = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [event(1, "execution.queued")], last: 1 }),
      { status: 200, headers: { "Content-Type": "application/json" } })));
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("catches up over REST, then follows the socket from the last event it saw", async () => {
    const { result } = renderHook(() => useWorkspaceEvents("p1"));
    await waitFor(() => expect(FakeSocket.made).toHaveLength(1));
    expect(result.current.events.map((e) => e.id)).toEqual([1]);
    expect(FakeSocket.made[0].url).toContain("/api/v1/projects/p1/events/ws?after=1");
    act(() => { FakeSocket.made[0].onopen?.(); });
    expect(result.current.connection).toBe("live");
    act(() => { FakeSocket.made[0].onmessage?.({ data: JSON.stringify({ type: "events", items: [event(2, "execution.finished")] }) }); });
    expect(result.current.events.map((e) => e.kind)).toEqual(["execution.queued", "execution.finished"]);
  });

  it("stops when the server refuses (policy close) instead of retrying", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useWorkspaceEvents("p1"));
    await waitFor(() => expect(FakeSocket.made).toHaveLength(1));
    act(() => { FakeSocket.made[0].onclose?.({ code: 1008 }); });
    expect(result.current.connection).toBe("offline");
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(FakeSocket.made).toHaveLength(1);  // no reconnect storm against a refusal
    vi.useRealTimers();
  });
});

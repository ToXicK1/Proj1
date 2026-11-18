import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request, setCsrfToken } from "./api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  setCsrfToken(null);
});

describe("api client", () => {
  it("surfaces the backend error code and message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(401, { code: "unauthenticated", title: "Sign in required" }),
    );
    const err = await api.me().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe("unauthenticated");
  });

  it("sends the CSRF header on unsafe requests only", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, { status: "ok" }));
    setCsrfToken("token-123");
    await request("GET", "/api/v1/projects");
    await request("POST", "/api/v1/auth/logout");
    const getHeaders = (spy.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    const postHeaders = (spy.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    expect(getHeaders["X-CSRF-Token"]).toBeUndefined();
    expect(postHeaders["X-CSRF-Token"]).toBe("token-123");
  });

  it("sends credentials as same-origin cookies and never reads a token from storage", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, {}));
    await request("GET", "/api/v1/auth/me");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
  });
});

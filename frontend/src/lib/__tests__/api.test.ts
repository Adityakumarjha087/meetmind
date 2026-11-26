import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, getAccessToken, refreshSession, setAccessToken } from "@/lib/api";
import { formatDuration, formatTimestamp, formatUsd, initials } from "@/lib/utils";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => setAccessToken(null));

describe("api client", () => {
  it("sends bearer tokens and refreshes once on 401", async () => {
    setAccessToken("old");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "Token expired" } }))
      .mockResolvedValueOnce(json(200, { access_token: "new", refresh_token: "r", expires_in: 900, user: {} }))
      .mockResolvedValueOnce(json(200, { id: "u1", email: "a@x.com" }));
    const me = await api.me();
    expect(me.id).toBe("u1");
    expect(getAccessToken()).toBe("new");
    const calls = fetchMock.mock.calls;
    expect(new Headers(calls[0][1]!.headers).get("Authorization")).toBe("Bearer old");
    expect(String(calls[1][0])).toContain("/auth/refresh");
    expect(new Headers(calls[2][1]!.headers).get("Authorization")).toBe("Bearer new");
  });

  it("surfaces structured API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(422, { error: { code: "validation_error", message: "Bad input", details: [1] } }));
    await expect(api.workspaces()).rejects.toMatchObject({ status: 422, code: "validation_error", message: "Bad input" });
    await expect(api.workspaces()).rejects.toBeInstanceOf(ApiError);
  });

  it("clears the session when refresh fails", async () => {
    setAccessToken("x");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(401, {}));
    expect(await refreshSession()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("builds query strings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { items: [], total: 0, limit: 50, offset: 0 }));
    await api.meetings("w1", { q: "launch", status: "completed" });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/workspaces\/w1\/meetings\?q=launch&status=completed$/);
  });
});

describe("formatters", () => {
  it("formats timestamps, durations, money and initials", () => {
    expect(formatTimestamp(65)).toBe("01:05");
    expect(formatTimestamp(3725)).toBe("1:02:05");
    expect(formatDuration(74)).toBe("1 min");
    expect(formatDuration(5400)).toBe("1h 30m");
    expect(formatDuration(null)).toBe("—");
    expect(formatUsd(0.0123)).toContain("0.0123");
    expect(initials("Ada Lovelace King")).toBe("AL");
  });
});

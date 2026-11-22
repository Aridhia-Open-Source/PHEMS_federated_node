import { expiresSoon, getRefreshToken, getToken, setToken } from "./auth";
import { api, refreshSession } from "./client";

// An unsigned JWT with the given exp (seconds); the UI only reads claims.
function jwt(exp: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
  return `${b64({ alg: "none" })}.${b64({ exp })}.sig`;
}
const inSeconds = (s: number) => Math.floor(Date.now() / 1000) + s;

afterEach(() => {
  setToken(null);
  vi.unstubAllGlobals();
});

test("expiresSoon is true near exp and for unreadable tokens", () => {
  expect(expiresSoon(jwt(inSeconds(300)))).toBe(false);
  expect(expiresSoon(jwt(inSeconds(10)))).toBe(true);
  expect(expiresSoon("garbage")).toBe(true);
});

test("refreshSession swaps the refresh token for a new pair", async () => {
  const fresh = jwt(inSeconds(300));
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ token: fresh, refresh_token: "r2" })));
  vi.stubGlobal("fetch", fetchMock);
  setToken(jwt(inSeconds(5)), "r1");

  await refreshSession();

  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer r1");
  expect([getToken(), getRefreshToken()]).toEqual([fresh, "r2"]);
});

test("a refused refresh ends the session", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
  setToken(jwt(inSeconds(5)), "r1");

  await refreshSession();

  expect([getToken(), getRefreshToken()]).toEqual([null, null]);
});

test("a request with an expiring token refreshes first and sends the new access token", async () => {
  const fresh = jwt(inSeconds(300));
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.endsWith("/refresh_token")) {
      return new Response(JSON.stringify({ token: fresh, refresh_token: "r2" }));
    }
    return new Response("[]", { headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  setToken(jwt(inSeconds(5)), "r1");

  // openapi-fetch keeps the fetch it was created with, so the request takes the mock per call
  await api.GET("/projects", { fetch: fetchMock });

  const sent = fetchMock.mock.calls.map(([input]) => input).find((i): i is Request => i instanceof Request);
  expect(sent?.headers.get("Authorization")).toBe(`Bearer ${fresh}`);
});

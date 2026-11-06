/**
 * Low-level HTTP helpers shared by RTK Query and the WebSocket client: the API base path and the
 * single-flight token refresh (concurrent 401s trigger one /auth/refresh).
 */
import { tokens } from "./tokens";
import type { TokenPair } from "./types";

export const API_BASE = "/api";

let refreshing: Promise<boolean> | null = null;

/** Exchange the stored refresh token for a new pair. Concurrent callers share one request. */
export function refreshTokens(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const refresh = tokens.refresh;
      if (!refresh) return false;
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) {
          tokens.clear();
          return false;
        }
        const pair = (await res.json()) as TokenPair;
        tokens.set(pair.access_token, pair.refresh_token);
        return true;
      } catch {
        return false; // network error: keep the refresh token, try again later
      }
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

/** Human-readable message from an RTK Query / fetch error. */
export function errorMessage(error: unknown): string {
  if (!error) return "";
  const e = error as { status?: number | string; originalStatus?: number; data?: { detail?: unknown } | string;
    error?: string; message?: string };
  const detail = typeof e.data === "object" ? e.data?.detail : undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("; ");
  const status = e.originalStatus ?? (typeof e.status === "number" ? e.status : undefined);
  if (status && status >= 500) return `The server had a problem (${status}). Please try again in a moment.`;
  if (e.status === "FETCH_ERROR") return "Can't reach the server. Check your connection and try again.";
  if (e.status === "PARSING_ERROR") return "The server sent an unexpected response. Please try again.";
  return e.message ?? (status ? `Request failed (${status})` : "Something went wrong");
}

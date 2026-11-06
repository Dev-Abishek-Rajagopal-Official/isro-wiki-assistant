/**
 * Token storage. The access token lives only in memory; the refresh token is kept in localStorage so a
 * reload can restore the session. (An httpOnly cookie would be safer against XSS - see README.)
 */

const REFRESH_KEY = "isro.refresh_token";

let accessToken: string | null = null;
const listeners = new Set<() => void>();

export const tokens = {
  get access(): string | null {
    return accessToken;
  },
  get refresh(): string | null {
    try {
      return localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  set(access: string, refresh: string) {
    accessToken = access;
    try {
      localStorage.setItem(REFRESH_KEY, refresh);
    } catch {
      /* storage unavailable (private mode): session lasts until reload */
    }
    listeners.forEach((l) => l());
  },
  clear() {
    accessToken = null;
    try {
      localStorage.removeItem(REFRESH_KEY);
    } catch {
      /* ignore */
    }
    listeners.forEach((l) => l());
  },
  /** Notified whenever tokens change (e.g. the WebSocket re-authenticates). */
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

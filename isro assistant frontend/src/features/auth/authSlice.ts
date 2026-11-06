/**
 * Session: restore on load (refresh token -> new access token -> /auth/me), login, register, logout.
 * The access token stays in memory (lib/tokens); `user.is_admin` drives the admin navigation.
 */
import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { refreshTokens } from "../../lib/api";
import { tokens } from "../../lib/tokens";
import type { User } from "../../lib/types";
import { api } from "../../services/api";
import { runsActions } from "../runs/runsSlice";

type Status = "checking" | "authenticated" | "anonymous";

interface AuthState {
  user: User | null;
  status: Status;
}

const initialState: AuthState = { user: null, status: "checking" };

async function loadMe(dispatch: (a: unknown) => unknown): Promise<User> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (dispatch(api.endpoints.me.initiate(undefined, { forceRefetch: true })) as any).unwrap();
}

export const restoreSession = createAsyncThunk("auth/restore", async (_, { dispatch }) => {
  if (!tokens.refresh || !(await refreshTokens())) return null;
  try {
    return await loadMe(dispatch);
  } catch {
    tokens.clear();
    return null;
  }
});

export const login = createAsyncThunk(
  "auth/login",
  async (body: { email: string; password: string }, { dispatch, rejectWithValue }) => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const pair = await (dispatch(api.endpoints.login.initiate(body)) as any).unwrap();
      tokens.set(pair.access_token, pair.refresh_token);
      return await loadMe(dispatch);
    } catch (e) {
      return rejectWithValue(e);
    }
  },
);

export const logout = createAsyncThunk("auth/logout", async (everywhere: boolean | undefined, { dispatch }) => {
  try {
    if (everywhere) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (dispatch(api.endpoints.logoutAll.initiate()) as any).unwrap();
    } else if (tokens.refresh) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (dispatch(api.endpoints.logout.initiate({ refresh_token: tokens.refresh })) as any).unwrap();
    }
  } catch {
    /* the session ends locally either way */
  }
  tokens.clear();
  dispatch(api.util.resetApiState());
  dispatch(runsActions.reset());
});

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(restoreSession.fulfilled, (s, a) => {
      s.user = a.payload;
      s.status = a.payload ? "authenticated" : "anonymous";
    });
    b.addCase(restoreSession.rejected, (s) => {
      s.user = null;
      s.status = "anonymous";
    });
    b.addCase(login.fulfilled, (s, a) => {
      s.user = a.payload;
      s.status = "authenticated";
    });
    b.addCase(logout.fulfilled, (s) => {
      s.user = null;
      s.status = "anonymous";
    });
  },
});

export default authSlice.reducer;

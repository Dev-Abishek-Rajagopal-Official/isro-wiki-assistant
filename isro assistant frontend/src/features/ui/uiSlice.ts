/** UI state: details drawer (which step is open), mobile sidebar, toasts, socket connection status. */
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { ConnectionStatus } from "../../lib/ws";

export interface DrawerTarget {
  /** "live" = runs slice for a thread, "history" = a run rebuilt from stored events */
  source: "live" | "history";
  threadId: string;
  runId?: string | null;
  stepId: string;
}

export interface Toast {
  id: number;
  kind: "info" | "error" | "success";
  text: string;
}

interface UiState {
  drawer: DrawerTarget | null;
  sidebarOpen: boolean;
  connection: ConnectionStatus;
  toasts: Toast[];
}

const initialState: UiState = { drawer: null, sidebarOpen: false, connection: "idle", toasts: [] };
let toastId = 0;

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    openDrawer(state, action: PayloadAction<DrawerTarget>) {
      state.drawer = action.payload;
    },
    closeDrawer(state) {
      state.drawer = null;
    },
    toggleSidebar(state, action: PayloadAction<boolean | undefined>) {
      state.sidebarOpen = action.payload ?? !state.sidebarOpen;
    },
    connectionChanged(state, action: PayloadAction<ConnectionStatus>) {
      state.connection = action.payload;
    },
    toastAdded: {
      reducer(state, action: PayloadAction<Toast>) {
        state.toasts.push(action.payload);
      },
      prepare(kind: Toast["kind"], text: string) {
        return { payload: { id: ++toastId, kind, text } };
      },
    },
    toastDismissed(state, action: PayloadAction<number>) {
      state.toasts = state.toasts.filter((t) => t.id !== action.payload);
    },
  },
});

export const uiActions = uiSlice.actions;
export default uiSlice.reducer;

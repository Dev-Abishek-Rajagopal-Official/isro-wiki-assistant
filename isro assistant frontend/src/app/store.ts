/** Redux store: RTK Query cache + auth, live runs, UI; the socket middleware feeds WebSocket messages in. */
import { configureStore } from "@reduxjs/toolkit";
import { setupListeners } from "@reduxjs/toolkit/query";
import authReducer from "../features/auth/authSlice";
import runsReducer from "../features/runs/runsSlice";
import { socketMiddleware } from "../features/socket/socketMiddleware";
import uiReducer from "../features/ui/uiSlice";
import { api } from "../services/api";

export function makeStore() {
  const store = configureStore({
    reducer: {
      [api.reducerPath]: api.reducer,
      auth: authReducer,
      runs: runsReducer,
      ui: uiReducer,
    },
    middleware: (getDefault) =>
      getDefault({ serializableCheck: { ignoredActions: ["api/executeQuery/fulfilled"] } })
        .concat(api.middleware, socketMiddleware),
  });
  setupListeners(store.dispatch); // refetch on focus / reconnect where enabled
  return store;
}

export const store = makeStore();
export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];

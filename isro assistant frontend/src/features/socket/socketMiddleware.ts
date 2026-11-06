/**
 * Connects the WebSocket to Redux.
 *
 * - starts the socket when a session begins, stops it on logout
 * - every server message goes to the runs slice (live steps, tokens, AgentState)
 * - keeps the RTK Query cache fresh: run_started / conversation_titled -> conversation list,
 *   run_finished -> that thread, its runs and usage
 */
import type { Middleware } from "@reduxjs/toolkit";
import { agentSocket } from "../../lib/ws";
import type { WsMessage } from "../../lib/types";
import { api } from "../../services/api";
import { login, logout, restoreSession } from "../auth/authSlice";
import { runsActions } from "../runs/runsSlice";
import { uiActions } from "../ui/uiSlice";

export const socketMiddleware: Middleware = (store) => {
  let detach: (() => void)[] = [];

  const onMessage = (msg: WsMessage) => {
    store.dispatch(runsActions.messageReceived(msg));
    switch (msg.type) {
      case "conversation_titled":
        store.dispatch(api.util.invalidateTags(["ConversationList", { type: "Conversation", id: msg.conversation_id }]));
        break;
      case "run_started":
        if (!msg.replay) store.dispatch(api.util.invalidateTags(["ConversationList"]));
        break;
      case "run_finished":
      case "run_cancelled":
      case "error":
        if (msg.thread_id && !msg.replay) {
          store.dispatch(api.util.invalidateTags([{ type: "Thread", id: msg.thread_id }, { type: "Runs", id: msg.thread_id }, "Usage"]));
        }
        break;
      case "busy":
        store.dispatch(uiActions.toastAdded("info", "This thread is still answering - wait for it to finish."));
        break;
    }
  };

  const start = () => {
    if (detach.length) return;
    detach = [agentSocket.onMessage(onMessage), agentSocket.onStatus((s) => store.dispatch(uiActions.connectionChanged(s)))];
    agentSocket.start();
  };

  const stop = () => {
    detach.forEach((d) => d());
    detach = [];
    agentSocket.stop();
  };

  return (next) => (action) => {
    const result = next(action);
    if ((restoreSession.fulfilled.match(action) && action.payload) || login.fulfilled.match(action)) start();
    if (logout.fulfilled.match(action)) stop();
    return result;
  };
};

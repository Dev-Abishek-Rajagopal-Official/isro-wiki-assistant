/**
 * WebSocket client for /api/ws.
 *
 * - authenticates with the first message, re-authenticates on `auth_expired` (after refreshing tokens)
 * - reconnects with exponential backoff and re-subscribes to every thread it was following, asking only
 *   for events after the last `event_id` it has seen (nothing is lost, nothing repeated)
 * - de-duplicates run messages by `event_id`
 */
import { refreshTokens } from "./api";
import { tokens } from "./tokens";
import type { WsMessage } from "./types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed";
type Handler = (msg: WsMessage) => void;

export class AgentSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private statusHandlers = new Set<(s: ConnectionStatus) => void>();
  private threads = new Map<string, number>(); // thread_id -> last event_id seen
  private seen = new Set<number>();
  private queue: object[] = [];
  private retry = 0;
  private stopped = true;
  private authed = false;
  status: ConnectionStatus = "idle";

  constructor(private url: string = AgentSocket.defaultUrl()) {}

  static defaultUrl(): string {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/api/ws`;
  }

  onMessage(h: Handler): () => void {
    this.handlers.add(h);
    return () => this.handlers.delete(h);
  }

  onStatus(h: (s: ConnectionStatus) => void): () => void {
    this.statusHandlers.add(h);
    return () => this.statusHandlers.delete(h);
  }

  start(): void {
    this.stopped = false;
    if (!this.ws) this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close(1000, "logout");
    this.ws = null;
    this.threads.clear();
    this.seen.clear();
    this.setStatus("closed");
  }

  /** Send now if authenticated, otherwise queue until the socket is ready. */
  send(message: object): void {
    if (this.ws && this.authed && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      this.queue.push(message);
    }
  }

  ask(threadId: string, question: string, clientMsgId: string): void {
    this.follow(threadId, false);
    this.send({ type: "ask", thread_id: threadId, question, client_msg_id: clientMsgId });
  }

  askAudio(threadId: string, audioB64: string, clientMsgId: string): void {
    this.follow(threadId, false);
    this.send({ type: "ask_audio", thread_id: threadId, audio_b64: audioB64, filename: "question.wav",
      content_type: "audio/wav", client_msg_id: clientMsgId });
  }

  cancel(runId: string): void {
    this.send({ type: "cancel", run_id: runId });
  }

  /** Follow a thread live. With replay, stored events after the last seen id are sent first. */
  follow(threadId: string, replay = true): void {
    const known = this.threads.has(threadId);
    if (!known) this.threads.set(threadId, 0);
    if (!known || replay) {
      this.send({ type: "subscribe", thread_id: threadId, after_id: this.threads.get(threadId) ?? 0 });
    }
  }

  // ------------------------------------------------------------------ internals
  private setStatus(s: ConnectionStatus) {
    this.status = s;
    this.statusHandlers.forEach((h) => h(s));
  }

  private connect(): void {
    this.setStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    this.authed = false;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: tokens.access }));
    ws.onmessage = (ev) => this.handle(JSON.parse(ev.data) as WsMessage);
    ws.onclose = (ev) => {
      this.ws = null;
      this.authed = false;
      this.setStatus("closed");
      if (this.stopped) return;
      if (ev.code === 4401) {
        // token rejected: refresh and try again (gives up if the session is gone)
        void refreshTokens().then((ok) => (ok ? this.scheduleReconnect() : this.stop()));
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = Math.min(15000, 500 * 2 ** this.retry++);
    setTimeout(() => !this.stopped && this.connect(), delay);
  }

  private handle(msg: WsMessage): void {
    if (msg.type === "auth_ok") {
      this.authed = true;
      this.retry = 0;
      this.setStatus("open");
      // resume every followed thread from the last event seen, then flush queued messages
      for (const [threadId, lastId] of this.threads) {
        this.ws?.send(JSON.stringify({ type: "subscribe", thread_id: threadId, after_id: lastId }));
      }
      const pending = this.queue.splice(0);
      pending.forEach((m) => this.ws?.send(JSON.stringify(m)));
      return;
    }
    if (msg.type === "auth_expired") {
      void refreshTokens().then((ok) => ok && this.ws?.send(JSON.stringify({ type: "auth", token: tokens.access })));
      return;
    }
    if (msg.event_id != null) {
      if (this.seen.has(msg.event_id)) return; // replayed + live overlap
      this.seen.add(msg.event_id);
      if (msg.thread_id && msg.event_id > (this.threads.get(msg.thread_id) ?? 0)) {
        this.threads.set(msg.thread_id, msg.event_id);
      }
    }
    this.handlers.forEach((h) => h(msg));
  }
}

export const agentSocket = new AgentSocket();

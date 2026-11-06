/**
 * Chat page.
 *  /                       welcome + composer; the first question creates a conversation and a thread
 *  /c/:conversationId      opens the conversation's first thread
 *  /c/:cid/t/:threadId     the thread: past turns (REST) + the live run (WebSocket), composer
 * Opening a thread follows it on the socket (replays stored events after the last one seen), so the
 * latest run's steps are visible again after a reload.
 */
import { History, Mic, MessagesSquare, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { EmptyState, fmt, Skeleton, Spinner } from "../../components/ui";
import { errorMessage } from "../../lib/api";
import { agentSocket } from "../../lib/ws";
import {
  useConversationQuery,
  useCreateConversationMutation,
  useCreateThreadMutation,
  useThreadQuery,
} from "../../services/api";
import { runsActions } from "../runs/runsSlice";
import { uiActions } from "../ui/uiSlice";
import { Composer } from "./Composer";
import { Turn } from "./Turn";

const EXAMPLES = [
  "When is the next ISRO launch, and what is it carrying?",
  "Is Cartosat-3 still in orbit?",
  "Why did the atomic clocks on the IRNSS satellites fail?",
  "List the Chandrayaan missions with their launch dates.",
];

const newId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()));

/** Send a text or voice question on a thread (optimistic live run + WebSocket message). */
function useAsk() {
  const dispatch = useAppDispatch();
  return {
    text(threadId: string, question: string) {
      const id = newId();
      dispatch(runsActions.started({ threadId, question, inputType: "text", clientMsgId: id }));
      agentSocket.ask(threadId, question, id);
    },
    voice(threadId: string, wavB64: string) {
      const id = newId();
      dispatch(runsActions.started({ threadId, question: "", inputType: "voice", clientMsgId: id }));
      agentSocket.askAudio(threadId, wavB64, id);
    },
  };
}

function Welcome() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const ask = useAsk();
  const user = useAppSelector((s) => s.auth.user);
  const [createConversation, c1] = useCreateConversationMutation();
  const [createThread, c2] = useCreateThreadMutation();
  const starting = c1.isLoading || c2.isLoading;

  const start = async (send: (threadId: string) => void) => {
    try {
      const conv = await createConversation().unwrap();
      const thread = await createThread({ conversationId: conv.id }).unwrap();
      navigate(`/c/${conv.id}/t/${thread.id}`);
      send(thread.id);
    } catch (e) {
      dispatch(uiActions.toastAdded("error", errorMessage(e)));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-10">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600"><Sparkles className="h-7 w-7" /></div>
        <h1 className="text-center text-2xl font-semibold text-slate-900">Hi {user?.full_name.split(" ")[0]}, what would you like to know?</h1>
        <p className="mt-2 max-w-lg text-center text-sm text-slate-500">
          Ask about ISRO missions, satellites, rockets and launches - type or tap <Mic className="inline h-3.5 w-3.5" /> to speak.
          You can watch each agent work and open any step to see what it found.
        </p>
        <div className="mt-6 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
          {EXAMPLES.map((q) => (
            <button key={q} disabled={starting} onClick={() => start((tid) => ask.text(tid, q))}
              className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 shadow-sm transition hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-50">
              {q}
            </button>
          ))}
        </div>
        {starting && <Spinner className="mt-4" />}
      </div>
      <Composer busy={false} disabled={starting} onSend={(q) => start((tid) => ask.text(tid, q))}
        onVoice={(b64) => start((tid) => ask.voice(tid, b64))} onStop={() => undefined} />
    </div>
  );
}

function OpenFirstThread({ conversationId }: { conversationId: string }) {
  const navigate = useNavigate();
  const { data, isError } = useConversationQuery(conversationId);
  const [createThread] = useCreateThreadMutation();
  useEffect(() => {
    if (!data) return;
    if (data.threads[0]) navigate(`/c/${conversationId}/t/${data.threads[0].id}`, { replace: true });
    else void createThread({ conversationId }).unwrap().then((t) => navigate(`/c/${conversationId}/t/${t.id}`, { replace: true }));
  }, [data, conversationId, navigate, createThread]);
  if (isError) return <EmptyState title="Conversation not found" />;
  return <div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6" /></div>;
}

function ThreadView({ conversationId, threadId }: { conversationId: string; threadId: string }) {
  const { data: thread, isLoading, isError } = useThreadQuery(threadId);
  const { data: conversation } = useConversationQuery(conversationId);
  const live = useAppSelector((s) => s.runs.byThread[threadId]);
  const ask = useAsk();
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { agentSocket.follow(threadId); }, [threadId]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); },
    [live?.answer, live?.timeline.length, thread?.runs.length]);

  const busy = !!live && ["pending", "transcribing", "running"].includes(live.status);
  const runs = thread?.runs ?? [];
  const liveInRest = live?.runId ? runs.some((r) => r.id === live.runId) : false;
  const usage = live?.threadUsage ?? thread?.thread_usage;
  const threadIndex = (conversation?.threads.findIndex((t) => t.id === threadId) ?? -1) + 1;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-slate-200 bg-white/80 px-4 py-2.5 backdrop-blur sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-slate-800">{conversation?.title ?? "New conversation"}</div>
          <div className="truncate text-xs text-slate-500">{thread?.title ?? (threadIndex ? `Thread ${threadIndex}` : "")}</div>
        </div>
        {usage && usage.llm_calls > 0 && (
          <div className="hidden text-right text-xs text-slate-500 sm:block" title="Tokens used in this thread">
            <div className="font-medium text-slate-700">{fmt.compact(usage.input_tokens + usage.output_tokens)} tokens</div>
            <div>{usage.llm_calls} LLM calls</div>
          </div>
        )}
        <Link to={`/c/${conversationId}/t/${threadId}/history`} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100">
          <History className="h-4 w-4" /> History
        </Link>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6 sm:px-6">
          {isLoading && <div className="space-y-4"><Skeleton className="ml-auto h-10 w-2/3" /><Skeleton className="h-24" /></div>}
          {isError && <EmptyState title="Thread not found" />}
          {!isLoading && !runs.length && !live && (
            <EmptyState icon={<MessagesSquare className="h-8 w-8" />} title="Ask your first question in this thread">
              Each thread keeps its own memory, so follow-up questions understand what came before.
            </EmptyState>
          )}
          {runs.map((r) => <Turn key={r.id} run={r} live={live?.runId === r.id ? live : undefined} threadId={threadId} />)}
          {live && !liveInRest && <Turn live={live} threadId={threadId} />}
          <div ref={bottom} />
        </div>
      </div>

      <Composer busy={busy} disabled={!!isError} onSend={(q) => ask.text(threadId, q)}
        onVoice={(b64) => ask.voice(threadId, b64)} onStop={() => live?.runId && agentSocket.cancel(live.runId)}
        placeholder="Ask a follow-up…" />
    </div>
  );
}

export function ChatPage() {
  const { conversationId, threadId } = useParams();
  if (!conversationId) return <Welcome />;
  if (!threadId) return <OpenFirstThread conversationId={conversationId} />;
  return <ThreadView key={threadId} conversationId={conversationId} threadId={threadId} />;
}

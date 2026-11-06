/**
 * Conversations sidebar: 10 most recent conversations + "Load more" (cursor pages of 10), the open
 * conversation's threads, new conversation / new thread, rename and archive. Titles update live
 * (conversation_titled invalidates the cached list).
 */
import { Archive, GitBranch, Loader2, MessageSquarePlus, MoreHorizontal, Pencil, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { Button, cx, fmt, Skeleton } from "../../components/ui";
import type { Conversation } from "../../lib/types";
import {
  useArchiveConversationMutation,
  useArchiveThreadMutation,
  useConversationQuery,
  useConversationsInfiniteQuery,
  useCreateThreadMutation,
  useUpdateConversationMutation,
} from "../../services/api";
import { uiActions } from "../ui/uiSlice";

function RowMenu({ onRename, onArchive }: { onRename: () => void; onArchive: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button onClick={(e) => { e.preventDefault(); setOpen(!open); }} aria-label="Conversation options"
        className="rounded p-1 text-slate-400 opacity-0 transition hover:bg-slate-200 hover:text-slate-700 group-hover:opacity-100 focus:opacity-100">
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-slate-200 bg-white p-1 text-sm shadow-lg">
          <button className="flex w-full items-center gap-2 rounded px-2 py-1.5 hover:bg-slate-50" onClick={(e) => { e.preventDefault(); setOpen(false); onRename(); }}>
            <Pencil className="h-3.5 w-3.5" /> Rename
          </button>
          <button className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-red-600 hover:bg-red-50" onClick={(e) => { e.preventDefault(); setOpen(false); onArchive(); }}>
            <Archive className="h-3.5 w-3.5" /> Archive
          </button>
        </div>
      )}
    </div>
  );
}

function Threads({ conversationId, activeThreadId }: { conversationId: string; activeThreadId?: string }) {
  const { data, isLoading } = useConversationQuery(conversationId);
  const [createThread, { isLoading: creating }] = useCreateThreadMutation();
  const [archiveThread] = useArchiveThreadMutation();
  const navigate = useNavigate();
  const running = useAppSelector((s) => s.runs.byThread);

  const newThread = async () => {
    const t = await createThread({ conversationId }).unwrap();
    navigate(`/c/${conversationId}/t/${t.id}`);
  };

  if (isLoading) return <div className="space-y-1 py-1 pl-6"><Skeleton className="h-6 w-32" /></div>;
  return (
    <div className="ml-4 border-l border-slate-200 py-1 pl-2">
      {data?.threads.map((t, i) => {
        const live = running[t.id];
        const busy = live && ["pending", "transcribing", "running"].includes(live.status);
        return (
          <div key={t.id} className="group flex items-center">
            <Link to={`/c/${conversationId}/t/${t.id}`}
              className={cx("flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1 text-xs",
                t.id === activeThreadId ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
              {busy ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-brand-600" /> : <GitBranch className="h-3 w-3 shrink-0 opacity-60" />}
              <span className="truncate">{t.title || `Thread ${i + 1}`}</span>
            </Link>
            {data.threads.length > 1 && (
              <button onClick={() => archiveThread({ id: t.id, conversationId })} aria-label="Archive thread"
                className="rounded p-1 text-slate-300 opacity-0 hover:text-red-500 group-hover:opacity-100"><Archive className="h-3 w-3" /></button>
            )}
          </div>
        );
      })}
      <button onClick={newThread} disabled={creating}
        className="mt-0.5 flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-brand-700">
        {creating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />} New thread
      </button>
    </div>
  );
}

function ConversationRow({ conv, active, activeThreadId }: { conv: Conversation; active: boolean; activeThreadId?: string }) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(conv.title ?? "");
  const [update] = useUpdateConversationMutation();
  const [archive] = useArchiveConversationMutation();
  const navigate = useNavigate();
  const { data } = useConversationQuery(conv.id, { skip: !active });

  const save = async () => {
    setRenaming(false);
    if (title.trim() && title.trim() !== conv.title) await update({ id: conv.id, title: title.trim() });
  };
  const firstThread = data?.threads[0]?.id;

  return (
    <div>
      <div className={cx("group flex items-center gap-1 rounded-lg pr-1", active ? "bg-slate-100" : "hover:bg-slate-50")}>
        {renaming ? (
          <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onBlur={save}
            onKeyDown={(e) => { if (e.key === "Enter") void save(); if (e.key === "Escape") setRenaming(false); }}
            className="m-1 flex-1 rounded border border-brand-300 px-2 py-1 text-sm outline-none" aria-label="Conversation name" />
        ) : (
          <Link to={active && firstThread ? `/c/${conv.id}/t/${activeThreadId ?? firstThread}` : `/c/${conv.id}`}
            className="min-w-0 flex-1 px-2.5 py-2">
            <div className={cx("truncate text-sm", conv.title ? "text-slate-800" : "italic text-slate-400")}>
              {conv.title ?? "Naming…"}
            </div>
            <div className="text-[11px] text-slate-400">
              {fmt.ago(conv.last_activity_at ?? conv.created_at)}{conv.thread_count > 1 && ` · ${conv.thread_count} threads`}
            </div>
          </Link>
        )}
        {!renaming && <RowMenu onRename={() => { setTitle(conv.title ?? ""); setRenaming(true); }}
          onArchive={async () => { await archive(conv.id); if (active) navigate("/"); }} />}
      </div>
      {active && <Threads conversationId={conv.id} activeThreadId={activeThreadId} />}
    </div>
  );
}

export function Sidebar() {
  const { conversationId, threadId } = useParams();
  const open = useAppSelector((s) => s.ui.sidebarOpen);
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage, refetch } = useConversationsInfiniteQuery();
  const conversations = data?.pages.flatMap((p) => p.items) ?? [];

  useEffect(() => { dispatch(uiActions.toggleSidebar(false)); }, [conversationId, threadId, dispatch]);

  return (
    <>
      {open && <div className="fixed inset-0 z-20 bg-slate-900/20 lg:hidden" onClick={() => dispatch(uiActions.toggleSidebar(false))} />}
      <aside className={cx("z-30 flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white",
        "fixed inset-y-0 left-0 top-14 transition-transform lg:static lg:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="p-3">
          <Button className="w-full" onClick={() => navigate("/")}><MessageSquarePlus className="h-4 w-4" /> New conversation</Button>
        </div>
        <div className="px-4 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Recent</div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Conversations">
          {isLoading && <div className="space-y-2 p-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>}
          {isError && <button onClick={() => refetch()} className="w-full p-3 text-sm text-red-600">Couldn't load conversations - retry</button>}
          {!isLoading && conversations.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-slate-400">No conversations yet. Ask your first question!</p>
          )}
          {conversations.map((c) => (
            <ConversationRow key={c.id} conv={c} active={c.id === conversationId} activeThreadId={threadId} />
          ))}
          {hasNextPage && (
            <Button variant="ghost" className="mt-1 w-full text-xs" loading={isFetchingNextPage} onClick={() => fetchNextPage()}>
              Load more
            </Button>
          )}
        </nav>
      </aside>
    </>
  );
}

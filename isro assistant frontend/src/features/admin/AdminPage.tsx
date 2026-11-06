/**
 * Admin panel (only for ADMIN_EMAILS; the server answers 404 to everyone else). System-wide analytics:
 * overview + trends, agents & routes, MCP tools, models & roles, users, errors (with full run timelines),
 * system health. Data is cached 60 s on the server (Redis) and in RTK Query.
 */
import { CheckCircle2, RefreshCw, Search, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { Drawer } from "../../components/Drawer";
import { Tabs } from "../../components/Tabs";
import { Badge, Button, Card, EmptyState, ErrorNote, fmt, Skeleton, Stat } from "../../components/ui";
import { errorMessage } from "../../lib/api";
import { storedToMessage } from "../../lib/events";
import {
  api,
  useAdminAgentsQuery,
  useAdminModelsQuery,
  useAdminOverviewQuery,
  useAdminRunQuery,
  useAdminRunsQuery,
  useAdminTimeseriesQuery,
  useAdminToolsQuery,
  useAdminUserQuery,
  useAdminUsersQuery,
  useHealthQuery,
} from "../../services/api";
import { runsActions } from "../runs/runsSlice";
import { label } from "../steps/buildSteps";
import { StepList } from "../steps/StepList";
import { TokenChart } from "../usage/UsagePage";

type TabId = "overview" | "agents" | "tools" | "models" | "users" | "errors" | "system";
const RANGES = [["24h", 1], ["7 days", 7], ["30 days", 30], ["All time", 0]] as const;

function usePeriod(days: number) {
  return useMemo(() => (days ? { from: new Date(Date.now() - days * 86400_000).toISOString() } : {}), [days]);
}

function Overview({ period, bucket }: { period: { from?: string }; bucket: "hour" | "day" }) {
  const { data, isLoading, error } = useAdminOverviewQuery(period);
  const { data: ts } = useAdminTimeseriesQuery({ ...period, bucket });
  if (error) return <ErrorNote>{errorMessage(error)}</ErrorNote>;
  if (isLoading || !data) return <Skeleton className="h-64" />;
  const series = (ts ?? []).map((p) => ({ ...p, label: new Date(p.bucket).toLocaleString(undefined, bucket === "hour" ? { hour: "2-digit", day: "numeric" } : { month: "short", day: "numeric" }) }));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Users" value={fmt.int(data.users.total)} hint={`${data.users.active_today} active today · ${data.users.active_7d} this week`} />
        <Stat label="Questions" value={fmt.int(data.runs.requests)} hint={`${data.conversations} conversations · ${data.threads} threads`} />
        <Stat label="Error rate" value={fmt.pct(data.runs.error_rate)} hint={`${data.runs.failed} failed · ${data.runs.cancelled} stopped`} />
        <Stat label="Answer time" value={fmt.secs(data.runs.p50_seconds)} hint={`p95 ${fmt.secs(data.runs.p95_seconds)}`} />
        <Stat label="Input tokens" value={fmt.compact(data.tokens.input_tokens)} hint={`${fmt.int(data.tokens.llm_calls)} LLM calls`} />
        <Stat label="Output tokens" value={fmt.compact(data.tokens.output_tokens)} hint={`${fmt.compact(data.tokens.reasoning_tokens)} reasoning`} />
        <Stat label="Voice questions" value={fmt.int(data.runs.voice_requests)} hint={fmt.pct(data.runs.requests ? data.runs.voice_requests / data.runs.requests : null)} />
        <Stat label="Rate-limit headroom" value={fmt.compact(data.latest_rate_limit?.remaining_tokens)} hint="tokens left (latest Azure response)" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-700">Questions & errors</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={series}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} allowDecimals={false} /><Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="requests" name="Questions" stroke="#3b6ef5" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="failed" name="Failed" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-700">Tokens</h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={series}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.compact(v)} /><Tooltip formatter={(v) => fmt.int(Number(v))} /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="input_tokens" name="Input" stackId="1" stroke="#3b6ef5" fill="#3b6ef5" fillOpacity={0.25} />
              <Area type="monotone" dataKey="output_tokens" name="Output" stackId="1" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.25} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card className="p-4 lg:col-span-2">
          <h3 className="mb-2 text-sm font-medium text-slate-700">Answer time (seconds)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="avg_seconds" name="Average" stroke="#10b981" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="p95_seconds" name="p95" stroke="#ef4444" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr>{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

function Agents({ period }: { period: { from?: string } }) {
  const { data, isLoading } = useAdminAgentsQuery(period);
  if (isLoading || !data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-700">How often each agent is used</h3>
          {data.agent_usage.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.agent_usage.map((a) => ({ name: label(a.agent), runs: a.runs }))} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} /><YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={110} /><Tooltip />
                <Bar dataKey="runs" name="Questions" fill="#3b6ef5" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState title="No agent runs yet" />}
          <p className="mt-2 text-xs text-slate-500">Average agents per question: {data.avg_agents_per_run ?? "–"}</p>
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-700">Most common routes</h3>
          <ul className="space-y-2">
            {data.routes.map((r, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className="flex flex-1 flex-wrap items-center gap-1">{r.route.map((n, j) => <span key={j} className="contents">{j > 0 && <span className="text-slate-300">→</span>}<Badge tone={n === "router" || n === "final_agent" ? "slate" : "blue"}>{label(n)}</Badge></span>)}</span>
                <span className="text-xs text-slate-500">{r.runs}× · {fmt.secs(r.avg_seconds)}</span>
              </li>
            ))}
            {!data.routes.length && <EmptyState title="No completed questions yet" />}
          </ul>
        </Card>
      </div>
      <Table head={["Agent node", "LLM calls", "Tokens", "Avg latency"]}>
        {data.llm_by_node.map((n) => (
          <tr key={n.node ?? "none"}><td className="px-3 py-2">{label(n.node) || "–"}</td><td className="px-3 py-2">{fmt.int(n.calls)}</td><td className="px-3 py-2">{fmt.int(n.tokens)}</td><td className="px-3 py-2">{fmt.secs(n.avg_seconds)}</td></tr>
        ))}
      </Table>
    </div>
  );
}

function Tools({ period }: { period: { from?: string } }) {
  const { data, isLoading } = useAdminToolsQuery(period);
  if (isLoading || !data) return <Skeleton className="h-64" />;
  if (!data.length) return <EmptyState title="No tool calls recorded yet" />;
  return (
    <Table head={["Agent", "MCP tool", "Calls", "Failed", "Empty", "Failure rate", "Avg duration"]}>
      {data.map((t) => (
        <tr key={`${t.agent}-${t.tool}`}>
          <td className="px-3 py-2">{label(t.agent)}</td><td className="px-3 py-2 font-mono text-xs">{t.tool}</td>
          <td className="px-3 py-2">{fmt.int(t.calls)}</td><td className="px-3 py-2">{t.failed}</td><td className="px-3 py-2">{t.empty}</td>
          <td className="px-3 py-2"><Badge tone={t.failure_rate > 0.1 ? "amber" : "green"}>{fmt.pct(t.failure_rate)}</Badge></td>
          <td className="px-3 py-2">{t.avg_ms != null ? fmt.secs(t.avg_ms / 1000) : "–"}</td>
        </tr>
      ))}
    </Table>
  );
}

function Models({ period }: { period: { from?: string } }) {
  const { data, isLoading } = useAdminModelsQuery(period);
  if (isLoading || !data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-5">
      <Card className="p-4"><h3 className="mb-2 text-sm font-medium text-slate-700">Tokens by LLM role</h3>
        <TokenChart rows={data.by_role.map((g) => ({ name: g.key ?? "–", input: g.input_tokens, output: g.output_tokens }))} />
      </Card>
      <Table head={["Model", "LLM calls", "Input", "Output", "Reasoning", "Cached", "Avg latency"]}>
        {data.by_model.map((g) => (
          <tr key={g.key}><td className="px-3 py-2 font-medium">{g.key}</td><td className="px-3 py-2">{fmt.int(g.llm_calls)}</td><td className="px-3 py-2">{fmt.int(g.input_tokens)}</td><td className="px-3 py-2">{fmt.int(g.output_tokens)}</td><td className="px-3 py-2">{fmt.int(g.reasoning_tokens)}</td><td className="px-3 py-2">{fmt.int(g.cached_tokens)}</td><td className="px-3 py-2">{fmt.secs(g.avg_llm_call_seconds)}</td></tr>
        ))}
      </Table>
    </div>
  );
}

function UserDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, isLoading } = useAdminUserQuery(id);
  return (
    <Drawer open wide title={data?.user.full_name ?? "User"} subtitle={data?.user.email} onClose={onClose}>
      <div className="space-y-5 p-5">
        {isLoading || !data ? <Skeleton className="h-40" /> : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Questions" value={fmt.int(data.usage.runs.requests)} />
              <Stat label="Failed" value={fmt.int(data.usage.runs.failed)} />
              <Stat label="Tokens" value={fmt.compact(data.usage.tokens.total_tokens)} />
              <Stat label="p50 time" value={fmt.secs(data.usage.runs.p50_seconds)} />
            </div>
            <Card className="p-4"><h3 className="mb-2 text-sm font-medium text-slate-700">Tokens per day</h3>
              <TokenChart rows={data.usage.groups.map((g) => ({ name: g.key ?? "–", input: g.input_tokens, output: g.output_tokens }))} />
            </Card>
            <Card className="p-4"><h3 className="mb-2 text-sm font-medium text-slate-700">Tokens by LLM role</h3>
              <TokenChart rows={data.by_role.map((g) => ({ name: g.key ?? "–", input: g.input_tokens, output: g.output_tokens }))} />
            </Card>
          </>
        )}
      </div>
    </Drawer>
  );
}

function Users() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const limit = 20;
  const { data, isLoading, isFetching } = useAdminUsersQuery({ limit, offset: page * limit, ...(query ? { search: query } : {}) });
  useEffect(() => { const t = setTimeout(() => { setQuery(search); setPage(0); }, 300); return () => clearTimeout(t); }, [search]);
  return (
    <div className="space-y-3">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name or email" aria-label="Search users"
          className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
      </div>
      {isLoading ? <Skeleton className="h-64" /> : (
        <>
          <Table head={["User", "Conversations", "Questions", "Failed", "Tokens", "Last active"]}>
            {data?.items.map((u) => (
              <tr key={u.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(u.id)}>
                <td className="px-3 py-2"><div className="font-medium text-slate-800">{u.full_name}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                <td className="px-3 py-2">{u.conversations}</td><td className="px-3 py-2">{u.requests}</td>
                <td className="px-3 py-2">{u.failed ? <Badge tone="amber">{u.failed}</Badge> : 0}</td>
                <td className="px-3 py-2">{fmt.compact(u.tokens)}</td><td className="px-3 py-2 text-slate-500">{fmt.ago(u.last_active) || "never"}</td>
              </tr>
            ))}
          </Table>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span>{data?.total ?? 0} users</span>
            <Button variant="secondary" className="ml-auto" disabled={page === 0 || isFetching} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={(page + 1) * limit >= (data?.total ?? 0) || isFetching} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </>
      )}
      {open && <UserDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function RunDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const dispatch = useAppDispatch();
  const { data } = useAdminRunQuery(id);
  const key = `history:${id}`;
  const run = useAppSelector((s) => s.runs.byThread[key]);
  useEffect(() => {
    if (!data) return;
    dispatch(runsActions.cleared(key));
    data.events.forEach((e) => dispatch(runsActions.messageReceived(storedToMessage({ ...e, run_id: id }, key))));
  }, [data, id, key, dispatch]);
  return (
    <Drawer open wide title="Run timeline" subtitle={data ? `${data.user_email} · ${data.run.question}` : "…"} onClose={onClose}>
      <div className="space-y-4 p-5">
        {data?.run.error && <ErrorNote>{data.run.error}</ErrorNote>}
        {run ? <StepList run={run} threadKey={key} defaultOpen /> : <Skeleton className="h-40" />}
      </div>
    </Drawer>
  );
}

function Errors() {
  const [status, setStatus] = useState<"failed" | "cancelled">("failed");
  const [open, setOpen] = useState<string | null>(null);
  const { data, isLoading } = useAdminRunsQuery({ status, limit: 50, offset: 0 });
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        {(["failed", "cancelled"] as const).map((s) => (
          <button key={s} onClick={() => setStatus(s)} className={`rounded-full px-3 py-1 text-xs font-medium ${status === s ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"}`}>{s}</button>
        ))}
      </div>
      {isLoading ? <Skeleton className="h-64" /> : !data?.items.length ? <EmptyState title={`No ${status} questions`}>Everything ran fine in this period.</EmptyState> : (
        <Table head={["When", "User", "Question", "Error"]}>
          {data.items.map((r) => (
            <tr key={r.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(r.id)}>
              <td className="whitespace-nowrap px-3 py-2 text-slate-500">{fmt.ago(r.started_at)}</td>
              <td className="px-3 py-2">{r.user_email}</td>
              <td className="max-w-xs truncate px-3 py-2">{r.question}</td>
              <td className="max-w-xs truncate px-3 py-2 text-amber-700">{r.error ?? "–"}</td>
            </tr>
          ))}
        </Table>
      )}
      {open && <RunDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function SystemHealth() {
  const { data, isLoading, refetch, isFetching } = useHealthQuery(undefined, { pollingInterval: 30000 });
  if (isLoading || !data) return <Skeleton className="h-40" />;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge tone={data.status === "ok" ? "green" : "amber"}>{data.status === "ok" ? "All systems operational" : "Degraded"}</Badge>
        <Button variant="ghost" className="ml-auto" loading={isFetching} onClick={() => refetch()}><RefreshCw className="h-4 w-4" /> Refresh</Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(data.checks).map(([name, c]) => (
          <Card key={name} className="flex items-start gap-3 p-4">
            {c.ok ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <XCircle className="h-5 w-5 text-red-500" />}
            <div className="min-w-0">
              <div className="font-medium capitalize text-slate-800">{name.replace(/_/g, " ")}</div>
              <div className="text-xs text-slate-500">
                {Object.entries(c).filter(([k]) => k !== "ok").map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || (c.ok ? "reachable" : "unreachable")}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function AdminPage() {
  const dispatch = useAppDispatch();
  const [tab, setTab] = useState<TabId>("overview");
  const [days, setDays] = useState<number>(7);
  const period = usePeriod(days);
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">Admin</h1>
            <p className="text-sm text-slate-500">System-wide analytics across all users.</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex rounded-lg border border-slate-200 bg-white p-0.5 text-sm">
              {RANGES.map(([l, d]) => (
                <button key={l} onClick={() => setDays(d)} className={`rounded-md px-3 py-1 ${days === d ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600"}`}>{l}</button>
              ))}
            </div>
            <Button variant="secondary" onClick={() => dispatch(api.util.invalidateTags(["Admin"]))}><RefreshCw className="h-4 w-4" /></Button>
          </div>
        </div>
        <Tabs value={tab} onChange={setTab} tabs={[
          { id: "overview", label: "Overview" }, { id: "agents", label: "Agents & routes" }, { id: "tools", label: "Tools (MCP)" },
          { id: "models", label: "Models & roles" }, { id: "users", label: "Users" }, { id: "errors", label: "Errors" }, { id: "system", label: "System" }]} />
        {tab === "overview" && <Overview period={period} bucket={days === 1 ? "hour" : "day"} />}
        {tab === "agents" && <Agents period={period} />}
        {tab === "tools" && <Tools period={period} />}
        {tab === "models" && <Models period={period} />}
        {tab === "users" && <Users />}
        {tab === "errors" && <Errors />}
        {tab === "system" && <SystemHealth />}
      </div>
    </div>
  );
}

/** The signed-in user's usage: requests, latency, tokens, grouped by day / model / role / agent / conversation. */
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, EmptyState, ErrorNote, fmt, Skeleton, Stat } from "../../components/ui";
import { errorMessage } from "../../lib/api";
import { useUsageQuery } from "../../services/api";
import { label } from "../steps/buildSteps";

const GROUPS = [
  ["day", "Day"], ["role", "LLM role"], ["node", "Agent"], ["model", "Model"], ["conversation", "Conversation"],
] as const;

export function TokenChart({ rows }: { rows: { name: string; input: number; output: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={rows.length > 6 ? -25 : 0} textAnchor={rows.length > 6 ? "end" : "middle"} height={rows.length > 6 ? 60 : 30} />
        <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.compact(v)} />
        <Tooltip formatter={(v) => fmt.int(Number(v))} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="input" name="Input tokens" stackId="t" fill="#3b6ef5" radius={[0, 0, 0, 0]} />
        <Bar dataKey="output" name="Output tokens" stackId="t" fill="#a5b4fc" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function UsagePage() {
  const [groupBy, setGroupBy] = useState<(typeof GROUPS)[number][0]>("day");
  const { data, isLoading, error } = useUsageQuery({ groupBy });

  const rows = (data?.groups ?? []).map((g) => ({
    name: groupBy === "node" ? label(g.key) || "–" : g.label ?? g.key ?? "–",
    input: g.input_tokens, output: g.output_tokens, calls: g.llm_calls,
  }));

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">My usage</h1>
          <p className="text-sm text-slate-500">Questions asked and AI tokens used (as reported by Azure AI Foundry).</p>
        </div>
        {error && <ErrorNote>{errorMessage(error)}</ErrorNote>}
        {isLoading || !data ? <Skeleton className="h-28" /> : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Questions" value={fmt.int(data.runs.requests)} hint={`${data.runs.voice_requests} by voice`} />
            <Stat label="Success rate" value={fmt.pct(data.runs.requests ? data.runs.succeeded / data.runs.requests : null)} hint={`${data.runs.failed} failed`} />
            <Stat label="Typical answer time" value={fmt.secs(data.runs.p50_seconds)} hint={`p95 ${fmt.secs(data.runs.p95_seconds)}`} />
            <Stat label="Tokens" value={fmt.compact(data.tokens.total_tokens)} hint={`${fmt.int(data.tokens.llm_calls)} LLM calls`} />
          </div>
        )}
        <Card className="p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-700">Tokens by</span>
            {GROUPS.map(([k, l]) => (
              <button key={k} onClick={() => setGroupBy(k)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${groupBy === k ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{l}</button>
            ))}
          </div>
          {rows.length ? <TokenChart rows={rows} /> : <EmptyState title="No usage yet">Ask a question to see your usage here.</EmptyState>}
        </Card>
      </div>
    </div>
  );
}

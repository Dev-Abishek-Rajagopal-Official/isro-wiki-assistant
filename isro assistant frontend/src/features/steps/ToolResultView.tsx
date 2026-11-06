/**
 * Readable rendering of what each MCP tool returned: RAG chunks as cards, launches as a table, Wikidata facts,
 * CelesTrak records / orbits; anything else (and "Raw JSON") falls back to the JSON tree.
 */
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { JsonView } from "../../components/JsonView";
import { Badge, cx } from "../../components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
function KeyValues({ rows }: { rows: [string, any][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
          <dd className="break-words text-slate-800">{Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RagResults({ data }: { data: any }) {
  return (
    <div className="space-y-2">
      {data.relevance && (
        <div className="text-xs text-slate-500">
          Best semantic match {data.relevance.best_dense_score} ·{" "}
          {data.relevance.likely_in_corpus ? <Badge tone="green">in the documents</Badge> : <Badge tone="amber">probably not covered</Badge>}
        </div>
      )}
      {(data.results ?? []).map((r: any, i: number) => (
        <div key={r.chunk_id ?? i} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-800">{r.title}</span>
            <span className="text-xs text-slate-500">› {r.section}</span>
            <Badge tone={r.chunk_type === "facts" ? "violet" : r.chunk_type === "table" ? "amber" : "slate"}>{r.chunk_type}</Badge>
            <span className="ml-auto text-xs text-slate-400">score {r.score}</span>
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-600">{r.content}</p>
          {r.url && (
            <a href={r.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">
              Wikipedia <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      ))}
      {data.content && !data.results && <p className="whitespace-pre-wrap text-xs text-slate-600">{data.content}</p>}
    </div>
  );
}

function Table({ cols, rows }: { cols: [string, string][]; rows: any[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr>{cols.map(([, h]) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((r, i) => (
            <tr key={i}>{cols.map(([k]) => <td key={k} className="px-2 py-1.5 align-top text-slate-700">{String(r[k] ?? "–")}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pretty({ data }: { data: any }) {
  if (data.results || (data.content && data.title)) return <RagResults data={data} />;
  if (data.launches) return <Table rows={data.launches} cols={[["name", "Launch"], ["net_utc", "Date (UTC)"], ["status", "Status"], ["rocket", "Rocket"], ["pad", "Pad"]]} />;
  if (data.launch) return <KeyValues rows={Object.entries(data.launch)} />;
  if (data.satellites) return <Table rows={data.satellites} cols={[["name", "Satellite"], ["norad_id", "NORAD"], ["launch_date", "Launched"], ["in_orbit", "In orbit"], ["operational_status", "Status"], ["perigee_km", "Perigee km"], ["apogee_km", "Apogee km"]]} />;
  if (data.satellite) return <KeyValues rows={Object.entries(data.satellite)} />;
  if (data.perigee_altitude_km != null) return <KeyValues rows={Object.entries(data).filter(([k]) => !["source", "source_url", "fetched_at", "from_cache"].includes(k))} />;
  if (data.missions) return <Table rows={data.missions} cols={[["name", "Mission"], ["launch_date", "Launch date"], ["types", "Type"], ["qid", "Wikidata"]]} />;
  if (data.matches) return <Table rows={data.matches} cols={[["label", "Name"], ["description", "Description"], ["qid", "Wikidata"]]} />;
  if (data.facts) {
    return (
      <div className="space-y-2">
        <div className="text-sm font-medium text-slate-800">{data.label} <span className="font-normal text-slate-500">{data.description}</span></div>
        <KeyValues rows={Object.entries(data.facts)} />
      </div>
    );
  }
  return <JsonView value={data} />;
}

export function ToolResultView({ result }: { result: any }) {
  const [raw, setRaw] = useState(false);
  if (result == null) return <p className="text-sm text-slate-500">No data returned.</p>;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        {result.source && <span className="text-slate-500">Source: {result.source}</span>}
        {result.from_cache && <Badge tone="slate">cached</Badge>}
        {result._truncated && <Badge tone="amber">shortened for display</Badge>}
        <button className={cx("ml-auto rounded px-2 py-0.5", raw ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-100")} onClick={() => setRaw(!raw)}>
          {raw ? "Readable view" : "Raw JSON"}
        </button>
      </div>
      {raw ? <JsonView value={result} /> : <Pretty data={result} />}
    </div>
  );
}

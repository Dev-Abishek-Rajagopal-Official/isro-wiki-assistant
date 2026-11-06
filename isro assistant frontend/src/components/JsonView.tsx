/** Collapsible JSON tree with copy button; keys listed in `highlight` are marked (e.g. just-changed state). */
import { Check, ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useState } from "react";
import { cx } from "./ui";

function Node({ name, value, depth, highlight }: { name?: string; value: unknown; depth: number; highlight?: Set<string> }) {
  const [open, setOpen] = useState(depth < 1);
  const isObj = value !== null && typeof value === "object";
  const marked = name != null && depth === 1 && highlight?.has(name);
  const label = name != null && <span className={cx("text-violet-700", marked && "rounded bg-amber-100 px-1")}>{name}: </span>;

  if (!isObj) {
    const text = typeof value === "string" ? `"${value}"` : String(value);
    return (
      <div className="whitespace-pre-wrap break-words pl-4">
        {label}
        <span className={typeof value === "string" ? "text-emerald-700" : "text-sky-700"}>{text}</span>
      </div>
    );
  }
  const entries = Array.isArray(value) ? value.map((v, i) => [String(i), v] as const) : Object.entries(value as object);
  return (
    <div className="pl-2">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex items-center text-left hover:text-brand-700">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {label}
        <span className="text-slate-400">{Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`}</span>
      </button>
      {open && entries.map(([k, v]) => <Node key={k} name={k} value={v} depth={depth + 1} highlight={highlight} />)}
    </div>
  );
}

export function JsonView({ value, highlight, className }: { value: unknown; highlight?: Set<string>; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard?.writeText(JSON.stringify(value, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className={cx("relative rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-relaxed", className)}>
      <button type="button" onClick={copy} className="absolute right-2 top-2 rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700" aria-label="Copy JSON">
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <Node value={value} depth={0} highlight={highlight} />
    </div>
  );
}

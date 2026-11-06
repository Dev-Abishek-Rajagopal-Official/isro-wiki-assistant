/** Accessible tab bar (controlled). */
import { cx } from "./ui";

export function Tabs<T extends string>({ tabs, value, onChange, className }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (id: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cx("flex gap-1 overflow-x-auto border-b border-slate-200", className)}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition",
            value === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700")}>
          {t.label}
          {t.count != null && <span className="ml-1.5 rounded bg-slate-100 px-1.5 text-xs text-slate-600">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

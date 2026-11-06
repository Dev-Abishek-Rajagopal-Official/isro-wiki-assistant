/** Small design-system primitives (Tailwind). */
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 disabled:opacity-50",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:opacity-50",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:opacity-50",
};

export function Button({ variant = "primary", loading, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium",
        "transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed", variants[variant], className)}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function IconButton({ label, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button {...rest} aria-label={label} title={label}
      className={cx("inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition",
        "hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
        "disabled:cursor-not-allowed disabled:opacity-40", className)}>
      {children}
    </button>
  );
}

export function Input({ label, error, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      <input {...rest} aria-invalid={!!error}
        className={cx("block w-full rounded-lg border bg-white px-3 py-2 text-sm shadow-sm outline-none transition",
          "focus:border-brand-500 focus:ring-2 focus:ring-brand-100",
          error ? "border-red-400" : "border-slate-300", className)} />
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>;
}

const badgeTones = {
  slate: "bg-slate-100 text-slate-700",
  blue: "bg-brand-50 text-brand-700",
  green: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  red: "bg-red-50 text-red-700",
  violet: "bg-violet-50 text-violet-700",
};

export function Badge({ tone = "slate", className, children }: { tone?: keyof typeof badgeTones; className?: string; children: ReactNode }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium", badgeTones[tone], className)}>{children}</span>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin text-brand-600", className)} aria-label="loading" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-slate-200/70", className)} />;
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 text-slate-400">{icon}</div>}
      <p className="font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{children}</div>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}

export const fmt = {
  int: (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString()),
  compact: (n: number | null | undefined) =>
    n == null ? "–" : Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n),
  secs: (s: number | null | undefined) => (s == null ? "–" : s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`),
  pct: (r: number | null | undefined) => (r == null ? "–" : `${(r * 100).toFixed(1)}%`),
  ago: (iso: string | null | undefined) => {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 604800) return `${Math.floor(s / 86400)} d ago`;
    return new Date(iso).toLocaleDateString();
  },
};

/** Transient notifications (auto-dismiss after 5 s). */
import { X } from "lucide-react";
import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { cx } from "../../components/ui";
import { uiActions } from "../ui/uiSlice";

export function Toasts() {
  const toasts = useAppSelector((s) => s.ui.toasts);
  const dispatch = useAppDispatch();
  useEffect(() => {
    const timers = toasts.map((t) => setTimeout(() => dispatch(uiActions.toastDismissed(t.id)), 5000));
    return () => timers.forEach(clearTimeout);
  }, [toasts, dispatch]);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={cx("pointer-events-auto flex max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg",
          t.kind === "error" ? "border-red-200 bg-red-50 text-red-800" : t.kind === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-700")}>
          <span className="flex-1">{t.text}</span>
          <button onClick={() => dispatch(uiActions.toastDismissed(t.id))} aria-label="Dismiss"><X className="h-4 w-4 opacity-60" /></button>
        </div>
      ))}
    </div>
  );
}

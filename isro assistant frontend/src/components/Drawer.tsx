/** Right-side off-canvas panel (full screen on mobile). Esc closes; focus moves into the panel. */
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { IconButton } from "./ui";

export function Drawer({ open, title, subtitle, onClose, children, wide }: {
  open: boolean; title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-[1px]" onClick={onClose} />
      <div ref={panel} tabIndex={-1}
        className={`relative flex h-full w-full flex-col bg-white shadow-2xl outline-none ${wide ? "sm:max-w-3xl" : "sm:max-w-xl"}`}>
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-900">{title}</h2>
            {subtitle && <div className="mt-0.5 text-sm text-slate-500">{subtitle}</div>}
          </div>
          <IconButton label="Close" onClick={onClose}><X className="h-5 w-5" /></IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

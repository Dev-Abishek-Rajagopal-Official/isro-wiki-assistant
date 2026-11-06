/** App shell: top bar (navigation, connection status, user menu) + sidebar + page + drawer + toasts. */
import { BarChart3, ChevronDown, LogOut, Menu, MessagesSquare, Rocket, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { cx, IconButton } from "../../components/ui";
import { logout } from "../auth/authSlice";
import { Sidebar } from "../conversations/Sidebar";
import { StepDrawerHost } from "../steps/StepDrawer";
import { uiActions } from "../ui/uiSlice";
import { Toasts } from "./Toasts";

function ConnectionDot() {
  const status = useAppSelector((s) => s.ui.connection);
  const tone = status === "open" ? "bg-emerald-500" : status === "connecting" ? "bg-amber-400 animate-pulse" : "bg-slate-300";
  const label = status === "open" ? "Live" : status === "connecting" ? "Connecting…" : "Offline";
  return (
    <span className="hidden items-center gap-1.5 text-xs text-slate-500 sm:inline-flex" title={`Real-time connection: ${label}`}>
      <span className={cx("h-2 w-2 rounded-full", tone)} />{label}
    </span>
  );
}

function UserMenu() {
  const dispatch = useAppDispatch();
  const user = useAppSelector((s) => s.auth.user);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  if (!user) return null;
  const initials = user.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-100" aria-haspopup="menu">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">{initials}</span>
        <ChevronDown className="h-4 w-4 text-slate-400" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1 w-60 rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
          <div className="border-b border-slate-100 px-3 py-2">
            <div className="truncate text-sm font-medium text-slate-800">{user.full_name}</div>
            <div className="truncate text-xs text-slate-500">{user.email}</div>
          </div>
          <button role="menuitem" onClick={() => dispatch(logout(false))} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
          <button role="menuitem" onClick={() => dispatch(logout(true))} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
            <LogOut className="h-4 w-4" /> Sign out on all devices
          </button>
        </div>
      )}
    </div>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <NavLink to={to} end={to === "/"}
      className={({ isActive }) => cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition",
        isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
      {icon}<span className="hidden sm:inline">{label}</span>
    </NavLink>
  );
}

export function AppLayout() {
  const dispatch = useAppDispatch();
  const isAdmin = useAppSelector((s) => s.auth.user?.is_admin);
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 sm:px-4">
        <IconButton label="Open conversations" className="lg:hidden" onClick={() => dispatch(uiActions.toggleSidebar())}>
          <Menu className="h-5 w-5" />
        </IconButton>
        <div className="flex items-center gap-2 font-semibold text-slate-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Rocket className="h-4 w-4" /></span>
          <span className="hidden sm:inline">ISRO Assistant</span>
        </div>
        <nav className="ml-2 flex items-center gap-1 sm:ml-6">
          <NavItem to="/" icon={<MessagesSquare className="h-4 w-4" />} label="Chat" />
          <NavItem to="/usage" icon={<BarChart3 className="h-4 w-4" />} label="My usage" />
          {isAdmin && <NavItem to="/admin" icon={<ShieldCheck className="h-4 w-4" />} label="Admin" />}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <ConnectionDot />
          <UserMenu />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-hidden"><Outlet /></main>
      </div>
      <StepDrawerHost />
      <Toasts />
    </div>
  );
}

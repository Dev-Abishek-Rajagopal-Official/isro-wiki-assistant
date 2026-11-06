/** Sign in / sign up screens and the route guards (RequireAuth, RequireAdmin, GuestOnly). */
import { Eye, EyeOff, Rocket } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { Button, ErrorNote, Input, Spinner } from "../../components/ui";
import { errorMessage } from "../../lib/api";
import { useRegisterMutation } from "../../services/api";
import { login } from "./authSlice";

function AuthCard({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-brand-50 via-slate-50 to-white px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-white shadow-lg shadow-brand-600/30">
            <Rocket className="h-6 w-6" />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}

function PasswordInput({ value, onChange, label = "Password", hint, autoComplete }: {
  value: string; onChange: (v: string) => void; label?: string; hint?: string; autoComplete: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input label={label} type={show ? "text" : "password"} value={value} required autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)} className="pr-10" />
      <button type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"}
        className="absolute right-2 top-[30px] rounded p-1 text-slate-400 hover:text-slate-600">
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function LoginPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await dispatch(login({ email, password }));
    setBusy(false);
    if (login.fulfilled.match(res)) navigate(from, { replace: true });
    else setError(errorMessage(res.payload) || "Could not sign in");
  };

  return (
    <AuthCard title="Welcome back" subtitle="Sign in to ask about ISRO and the Indian space programme">
      <form onSubmit={submit} className="space-y-4">
        {error && <ErrorNote>{error}</ErrorNote>}
        <Input label="Email" type="email" value={email} required autoComplete="email" onChange={(e) => setEmail(e.target.value)} />
        <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" />
        <Button type="submit" className="w-full" loading={busy}>Sign in</Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        New here? <Link to="/register" className="font-medium text-brand-600 hover:underline">Create an account</Link>
      </p>
    </AuthCard>
  );
}

export function RegisterPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [register, { isLoading }] = useRegisterMutation();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const strongEnough = form.password.length >= 8 && /[a-z]/i.test(form.password) && /\d/.test(form.password);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!strongEnough) return setError("Use at least 8 characters with letters and numbers.");
    try {
      await register(form).unwrap();
      const res = await dispatch(login({ email: form.email, password: form.password }));
      if (login.fulfilled.match(res)) navigate("/", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <AuthCard title="Create your account" subtitle="It takes a few seconds">
      <form onSubmit={submit} className="space-y-4">
        {error && <ErrorNote>{error}</ErrorNote>}
        <Input label="Full name" value={form.full_name} required autoComplete="name" onChange={(e) => set("full_name")(e.target.value)} />
        <Input label="Email" type="email" value={form.email} required autoComplete="email" onChange={(e) => set("email")(e.target.value)} />
        <PasswordInput value={form.password} onChange={set("password")} autoComplete="new-password"
          hint="At least 8 characters, with letters and numbers." />
        <Button type="submit" className="w-full" loading={isLoading}>Create account</Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        Already have an account? <Link to="/login" className="font-medium text-brand-600 hover:underline">Sign in</Link>
      </p>
    </AuthCard>
  );
}

function FullScreenSpinner() {
  return <div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6" /></div>;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAppSelector((s) => s.auth.status);
  const location = useLocation();
  if (status === "checking") return <FullScreenSpinner />;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Admin pages: non-admins are sent home (the server also answers 404 to them). */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const user = useAppSelector((s) => s.auth.user);
  if (!user?.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const status = useAppSelector((s) => s.auth.status);
  if (status === "checking") return <FullScreenSpinner />;
  if (status === "authenticated") return <Navigate to="/" replace />;
  return <>{children}</>;
}

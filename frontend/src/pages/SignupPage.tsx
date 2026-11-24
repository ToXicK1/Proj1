import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, JOIN_ROLES, api } from "../api";

export function SignupPage() {
  const [managed, setManaged] = useState<boolean | null>(null);
  useEffect(() => {
    api.authConfig().then((c) => setManaged(c.account_mode === "managed")).catch(() => setManaged(false));
  }, []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState("project_owner");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.signup(email, password, displayName, role);
      // Same message whether or not the email is already registered.
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (managed) {
    return (
      <section className="narrow-page stack-sm">
        <h1>Accounts are created by your administrator</h1>
        <p className="muted">Ask your administrator for an account. They will give you a temporary password, which
          you change the first time you sign in.</p>
        <Link to="/login">Back to sign in</Link>
      </section>
    );
  }

  if (sent) {
    return (
      <section className="card narrow">
        <h1>Check your email</h1>
        <p>
          If this address can receive mail, we have sent a link to verify it. The link expires in 24 hours.
        </p>
        <p>
          <Link to="/login">Back to sign in</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="card narrow">
      <h1>Create your account</h1>
      <p className="muted">The first account becomes the administrator. Everyone else joins once an administrator confirms their role.</p>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <label>
          Your name
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={120} required autoComplete="name" />
        </label>
        <label>
          Work email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label>
          Password (at least 12 characters)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={12}
            maxLength={128}
            required
            autoComplete="new-password"
          />
        </label>
        <label>
          I am joining as
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {JOIN_ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="muted">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </section>
  );
}

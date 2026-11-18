import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";

export function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.signup(email, password, displayName);
      // Same message whether or not the email is already registered.
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account. Try again.");
    } finally {
      setBusy(false);
    }
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
      <p className="muted">You will get your own workspace. You can create projects right away.</p>
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

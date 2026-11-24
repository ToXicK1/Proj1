import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useSession } from "../session";

/** The first page after signing in with a temporary password: nothing else opens until it is replaced. Also used
 * later to change one's own password. */
export function ChangePasswordPage() {
  const { state, refresh } = useSession();
  const navigate = useNavigate();
  const forced = state.status === "authenticated" && Boolean(state.user.must_change_password);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== again) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      await refresh();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the password. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="narrow-page stack">
      <h1>{forced ? "Choose your own password" : "Change your password"}</h1>
      {forced && (
        <p className="notice">You signed in with a temporary password from your administrator. Choose your own
          password to continue; the temporary one stops working.</p>
      )}
      <form className="stack-sm" onSubmit={(e) => void submit(e)}>
        <label>{forced ? "Temporary password" : "Current password"}
          <input type="password" autoComplete="current-password" required value={current}
            onChange={(e) => setCurrent(e.target.value)} /></label>
        <label>New password (at least 12 characters)
          <input type="password" autoComplete="new-password" required minLength={12} value={next}
            onChange={(e) => setNext(e.target.value)} /></label>
        <label>New password again
          <input type="password" autoComplete="new-password" required minLength={12} value={again}
            onChange={(e) => setAgain(e.target.value)} /></label>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
      </form>
    </section>
  );
}

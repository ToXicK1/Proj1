import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [message, setMessage] = useState("");
  // Verification tokens are single-use. React StrictMode runs effects twice in development, so the
  // request is guarded: the second run would otherwise send the same token again and fail.
  const submitted = useRef(false);

  useEffect(() => {
    if (submitted.current) return;
    submitted.current = true;
    if (!token) {
      setState("failed");
      setMessage("This link is missing its verification token.");
      return;
    }
    api
      .verifyEmail(token)
      .then(() => setState("done"))
      .catch((err: unknown) => {
        setState("failed");
        setMessage(err instanceof ApiError ? err.message : "Verification failed. Try again.");
      });
  }, [token]);

  return (
    <section className="card narrow">
      <h1>Email verification</h1>
      {state === "working" && <p>Verifying…</p>}
      {state === "done" && (
        <>
          <p>Your email is verified and your workspace is ready.</p>
          <p>
            <Link to="/login">Sign in to continue</Link>
          </p>
        </>
      )}
      {state === "failed" && (
        <>
          <p role="alert" className="error">{message}</p>
          <p>
            <Link to="/signup">Request a new account link</Link>
          </p>
        </>
      )}
    </section>
  );
}

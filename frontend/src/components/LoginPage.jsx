import { useState } from "react";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ACCOUNTS_KEY = "aicca_accounts";

function loadAccounts() {
  try {
    return JSON.parse(localStorage.getItem(ACCOUNTS_KEY)) || {};
  } catch {
    return {};
  }
}

function saveAccounts(accounts) {
  localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
}

/**
 * Standalone auth screen. There's no backend auth endpoint (per the
 * project's MVP scope), so accounts are kept client-side in localStorage,
 * keyed by email. Swap loadAccounts/saveAccounts + handleSubmit for real
 * API calls if a backend auth endpoint gets added later.
 */
export default function LoginPage({ onLoginSuccess, onBack }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isSignup = mode === "signup";

  function validate() {
    if (isSignup && name.trim().length < 2) {
      return "Enter your name.";
    }
    if (!EMAIL_RE.test(email.trim())) {
      return "Enter a valid email address.";
    }
    if (password.length < 6) {
      return "Password must be at least 6 characters.";
    }
    return "";
  }

  function handleSubmit(e) {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    const cleanEmail = email.trim().toLowerCase();
    const accounts = loadAccounts();

    if (isSignup) {
      if (accounts[cleanEmail]) {
        setError("An account with that email already exists — log in instead.");
        return;
      }
      setError("");
      setIsSubmitting(true);
      setTimeout(() => {
        accounts[cleanEmail] = { name: name.trim(), password };
        saveAccounts(accounts);
        setIsSubmitting(false);
        onLoginSuccess({ name: name.trim(), email: cleanEmail });
      }, 400);
      return;
    }

    // Login
    const account = accounts[cleanEmail];
    if (!account) {
      setError("No account found for that email — try creating one.");
      return;
    }
    if (account.password !== password) {
      setError("Incorrect password.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      onLoginSuccess({ name: account.name, email: cleanEmail });
    }, 400);
  }

  return (
    <div className="login-screen">
      <button className="back-link" onClick={onBack}>
        &larr; Back
      </button>

      <div className="login-card">
        <h1>{isSignup ? "Create your account" : "Welcome back"}</h1>
        <p className="subtitle">
          {isSignup
            ? "Sign up to start analyzing your React projects."
            : "Log in to pick up where you left off."}
        </p>

        {error && <div className="error-banner">{error}</div>}

        <form onSubmit={handleSubmit} noValidate>
          {isSignup && (
            <label className="field">
              <span className="field__label">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ada Lovelace"
                autoComplete="name"
              />
            </label>
          )}

          <label className="field">
            <span className="field__label">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </label>

          <label className="field">
            <span className="field__label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete={isSignup ? "new-password" : "current-password"}
            />
          </label>

          <button className="analyze-button login-submit" disabled={isSubmitting}>
            {isSubmitting ? "Please wait…" : isSignup ? "Create account" : "Log in"}
          </button>
        </form>

        <p className="login-toggle">
          {isSignup ? "Already have an account?" : "New here?"}{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => {
              setError("");
              setMode(isSignup ? "login" : "signup");
            }}
          >
            {isSignup ? "Log in" : "Create one"}
          </button>
        </p>

        <div className="login-divider">
          <span>or</span>
        </div>

        <button
          type="button"
          className="secondary-button login-guest"
          onClick={() => onLoginSuccess(null)}
        >
          Continue as guest
        </button>
      </div>
    </div>
  );
}
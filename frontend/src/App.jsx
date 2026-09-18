import { useEffect, useState } from "react";
import LandingPage from "./components/LandingPage.jsx";
import LoginPage from "./components/LoginPage.jsx";
import UploadScreen from "./components/UploadScreen.jsx";
import ResultsScreen from "./components/ResultsScreen.jsx";
import { useToast } from "./components/ToastProvider.jsx";
import "./App.css";

const VIEW = {
  LANDING: "landing",
  LOGIN: "login",
  UPLOAD: "upload",
  LOADING: "loading",
  RESULTS: "results",
};

const SESSION_KEY = "aicca_session_user";

export default function App() {
  const [view, setView] = useState(VIEW.LANDING);
  const [result, setResult] = useState(null);
  const [user, setUser] = useState(null);
  const { showToast } = useToast();

  // Restore a logged-in session on refresh so "register" actually sticks.
  useEffect(() => {
    const saved = localStorage.getItem(SESSION_KEY);
    if (saved) {
      try {
        setUser(JSON.parse(saved));
        setView(VIEW.UPLOAD);
      } catch {
        localStorage.removeItem(SESSION_KEY);
      }
    }
  }, []);

  function handleGetStarted() {
    setView(VIEW.LOGIN);
  }

  function handleLoginSuccess(userObj) {
    // userObj is null when the person chose "Continue as guest".
    setUser(userObj);
    if (userObj) {
      localStorage.setItem(SESSION_KEY, JSON.stringify(userObj));
    }
    setView(VIEW.UPLOAD);
  }

  function handleLogout() {
    setUser(null);
    localStorage.removeItem(SESSION_KEY);
    setResult(null);
    setView(VIEW.LANDING);
  }

  function handleAnalyzeStart() {
    setView(VIEW.LOADING);
  }

  function handleAnalyzeComplete(analysisResult) {
    setResult(analysisResult);
    setView(VIEW.RESULTS);
    const count = analysisResult.total_issues;
    showToast(
      count === 0
        ? "Analysis complete — no issues found."
        : `Analysis complete — ${count} issue${count !== 1 ? "s" : ""} found.`,
      "success"
    );
  }

  function handleAnalyzeError(message) {
    showToast(message, "error", 6000);
    setView(VIEW.UPLOAD);
  }

  function handleAnalyzeAnother() {
    setResult(null);
    setView(VIEW.UPLOAD);
  }

  return (
    <div className="app">
      {user && (view === VIEW.UPLOAD || view === VIEW.LOADING || view === VIEW.RESULTS) && (
        <div className="session-bar">
          <span className="session-bar__user">
            Signed in as <strong>{user.name}</strong>
          </span>
          <button className="link-button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}

      {view === VIEW.LANDING && <LandingPage onGetStarted={handleGetStarted} />}

      {view === VIEW.LOGIN && (
        <LoginPage
          onLoginSuccess={handleLoginSuccess}
          onBack={() => setView(VIEW.LANDING)}
        />
      )}

      {view === VIEW.UPLOAD && (
        <UploadScreen
          onAnalyzeStart={handleAnalyzeStart}
          onAnalyzeComplete={handleAnalyzeComplete}
          onAnalyzeError={handleAnalyzeError}
        />
      )}

      {view === VIEW.LOADING && (
        <div className="loading-screen">
          <div className="spinner" />
          <p>Analyzing your project — parsing files and building the issue graph&hellip;</p>
        </div>
      )}

      {view === VIEW.RESULTS && result && (
        <ResultsScreen result={result} onAnalyzeAnother={handleAnalyzeAnother} />
      )}
    </div>
  );
}
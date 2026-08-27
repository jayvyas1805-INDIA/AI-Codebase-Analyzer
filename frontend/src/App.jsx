import { useState } from "react";
import UploadScreen from "./components/UploadScreen.jsx";
import ResultsScreen from "./components/ResultsScreen.jsx";
import { useToast } from "./components/ToastProvider.jsx";
import "./App.css";

const VIEW = {
  UPLOAD: "upload",
  LOADING: "loading",
  RESULTS: "results",
};

export default function App() {
  const [view, setView] = useState(VIEW.UPLOAD);
  const [result, setResult] = useState(null);
  const { showToast } = useToast();

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

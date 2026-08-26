import { useState } from "react";
import UploadScreen from "./components/UploadScreen.jsx";
import ResultsScreen from "./components/ResultsScreen.jsx";
import "./App.css";

const VIEW = {
  UPLOAD: "upload",
  LOADING: "loading",
  RESULTS: "results",
};

export default function App() {
  const [view, setView] = useState(VIEW.UPLOAD);
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  function handleAnalyzeStart() {
    setErrorMessage(null);
    setView(VIEW.LOADING);
  }

  function handleAnalyzeComplete(analysisResult) {
    setResult(analysisResult);
    setView(VIEW.RESULTS);
  }

  function handleAnalyzeError(message) {
    setErrorMessage(message);
    setView(VIEW.UPLOAD);
  }

  function handleAnalyzeAnother() {
    setResult(null);
    setErrorMessage(null);
    setView(VIEW.UPLOAD);
  }

  return (
    <div className="app">
      {errorMessage && <div className="error-banner">{errorMessage}</div>}

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
          <p>Analyzing your project — parsing files and asking the AI to explain findings…</p>
        </div>
      )}

      {view === VIEW.RESULTS && result && (
        <ResultsScreen result={result} onAnalyzeAnother={handleAnalyzeAnother} />
      )}
    </div>
  );
}

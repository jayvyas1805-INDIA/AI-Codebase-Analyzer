import { useCallback, useEffect, useMemo, useState } from "react";
import IssueList from "./IssueList.jsx";
import IssueDetail from "./IssueDetail.jsx";
import SummaryBar from "./SummaryBar.jsx";
import { explainIssue } from "../api/analysisApi.js";

function useIsMobile(breakpoint = 860) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < breakpoint : false
  );

  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [breakpoint]);

  return isMobile;
}

export default function ResultsScreen({ result, onAnalyzeAnother }) {
  // Issues live in local state (not just `result.issues`) because we mutate
  // individual issues in place as their AI explanation arrives.
  const [issues, setIssues] = useState(result.issues);
  const [selectedId, setSelectedId] = useState(result.issues[0]?.id ?? null);
  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [explainingId, setExplainingId] = useState(null);
  const [explainError, setExplainError] = useState(null);
  const isMobile = useIsMobile();

  const selectedIssue = useMemo(
    () => issues.find((i) => i.id === selectedId) ?? null,
    [issues, selectedId]
  );

  // Fetches the AI explanation for one issue, on demand. Skips the call
  // entirely if it's already been fetched (or is currently in flight).
  const requestExplanation = useCallback(
    async (issue) => {
      if (!issue || issue.ai_explanation !== null) return;

      setExplainError(null);
      setExplainingId(issue.id);
      try {
        const updated = await explainIssue(result.job_id, issue.id);
        setIssues((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      } catch (err) {
        setExplainError(err.message);
      } finally {
        setExplainingId(null);
      }
    },
    [result.job_id]
  );

  // Auto-request an explanation whenever the selected issue changes
  // (covers both clicking a new issue AND the initial default selection).
  useEffect(() => {
    if (selectedIssue) {
      requestExplanation(selectedIssue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIssue?.id]);

  const hasParseWarnings =
    result.css_parse_errors.length > 0 || result.jsx_parse_errors.length > 0;

  const showListOnMobile = isMobile && !selectedId;
  const showDetailOnMobile = isMobile && !!selectedId;

  return (
    <div className="results-screen">
      <header className="dashboard-header">
        <div>
          <h1>Analysis Results</h1>
          <p className="dashboard-header__subtitle">
            {result.total_css_files_parsed} CSS files &middot; {result.total_jsx_files_parsed}{" "}
            JSX/JS files parsed
          </p>
        </div>
        <button className="secondary-button" onClick={onAnalyzeAnother}>
          Analyze another project
        </button>
      </header>

      <SummaryBar result={{ ...result, issues }} />

      {hasParseWarnings && (
        <div className="parse-warnings">
          <h3>Parse warnings</h3>
          {result.css_parse_errors.map((e, i) => (
            <p key={`css-err-${i}`}>{e}</p>
          ))}
          {result.jsx_parse_errors.map((e, i) => (
            <p key={`jsx-err-${i}`}>{e}</p>
          ))}
        </div>
      )}

      {issues.length === 0 ? (
        <div className="empty-project-state">
          <p>No issues found. This project's CSS class usage looks clean.</p>
        </div>
      ) : (
        <div className="dashboard-body">
          {(!isMobile || showListOnMobile) && (
            <IssueList
              issues={issues}
              selectedId={selectedId}
              onSelect={setSelectedId}
              severityFilter={severityFilter}
              onSeverityFilterChange={setSeverityFilter}
              typeFilter={typeFilter}
              onTypeFilterChange={setTypeFilter}
            />
          )}
          {(!isMobile || showDetailOnMobile) && (
            <IssueDetail
              issue={selectedIssue}
              onBack={() => setSelectedId(null)}
              isMobile={isMobile}
              isExplaining={explainingId === selectedIssue?.id}
              explainError={explainError}
            />
          )}
        </div>
      )}
    </div>
  );
}

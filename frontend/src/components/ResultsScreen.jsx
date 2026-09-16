import { useCallback, useEffect, useMemo, useState } from "react";
import IssueList from "./IssueList.jsx";
import IssueDetail from "./IssueDetail.jsx";
import ChatPanel from "./ChatPanel.jsx";
import SummaryBar from "./SummaryBar.jsx";
import { explainIssue, sendChatMessage, requestFix, downloadFixedProject } from "../api/analysisApi.js";

function useIsMobile(breakpoint = 900) {
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
  const [issues, setIssues] = useState(result.issues);
  const [selectedId, setSelectedId] = useState(result.issues[0]?.id ?? null);
  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [explainingId, setExplainingId] = useState(null);
  const [explainError, setExplainError] = useState(null);

  const [chatHistories, setChatHistories] = useState({});
  const [chatSendingId, setChatSendingId] = useState(null);
  const [chatError, setChatError] = useState(null);

  const [fixResults, setFixResults] = useState({}); // issueId -> FixResult
  const [fixingId, setFixingId] = useState(null);
  const [fixError, setFixError] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadError, setDownloadError] = useState(null);

  const isMobile = useIsMobile();

  const selectedIssue = useMemo(
    () => issues.find((i) => i.id === selectedId) ?? null,
    [issues, selectedId]
  );

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

  useEffect(() => {
    if (selectedIssue) {
      requestExplanation(selectedIssue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIssue?.id]);

  const handleSendChatMessage = useCallback(
    async (text) => {
      if (!selectedIssue) return;
      setChatError(null);
      setChatSendingId(selectedIssue.id);
      try {
        const res = await sendChatMessage(result.job_id, selectedIssue.id, text);
        setChatHistories((prev) => ({ ...prev, [selectedIssue.id]: res.history }));
      } catch (err) {
        setChatError(err.message);
      } finally {
        setChatSendingId(null);
      }
    },
    [result.job_id, selectedIssue]
  );

  const handleRequestFix = useCallback(
    async (issue) => {
      if (!issue) return;
      setFixError(null);
      setFixingId(issue.id);
      try {
        const fixResult = await requestFix(result.job_id, issue.id);
        setFixResults((prev) => ({ ...prev, [issue.id]: fixResult }));
      } catch (err) {
        setFixError(err.message);
      } finally {
        setFixingId(null);
      }
    },
    [result]
  );

  const handleDownloadFixedProject = useCallback(
    async (issue) => {
      if (!issue) return;
      setDownloadError(null);
      setDownloadingId(issue.id);
      try {
        await downloadFixedProject(result.job_id, issue.id);
      } catch (err) {
        setDownloadError(err.message);
      } finally {
        setDownloadingId(null);
      }
    },
    [result.job_id]
  );

  const hasParseWarnings =
    result.css_parse_errors.length > 0 || result.jsx_parse_errors.length > 0;

  const showListOnMobile = isMobile && !selectedId;
  const showDetailOnMobile = isMobile && !!selectedId;

  const detailPanel = (
    <IssueDetail
      issue={selectedIssue}
      onBack={() => setSelectedId(null)}
      isMobile={isMobile}
      isExplaining={explainingId === selectedIssue?.id}
      explainError={explainError}
      fixResult={selectedIssue ? fixResults[selectedIssue.id] : null}
      isFixing={fixingId === selectedIssue?.id}
      fixError={fixError}
      isDownloading={downloadingId === selectedIssue?.id}
      downloadError={downloadError}
      onRequestFix={() => handleRequestFix(selectedIssue)}
      onDownloadFixedProject={() => handleDownloadFixedProject(selectedIssue)}
    />
  );

  const chatPanel = (
    <ChatPanel
      issue={selectedIssue}
      messages={chatHistories[selectedIssue?.id] ?? []}
      onSendMessage={handleSendChatMessage}
      isSending={chatSendingId === selectedIssue?.id}
      sendError={chatError}
    />
  );

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
      ) : isMobile ? (
        // Mobile: only room for one "slot" at a time — list, or detail+chat stacked.
        <div className="dashboard-body dashboard-body--mobile">
          {showListOnMobile && (
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
          {showDetailOnMobile && (
            <div className="detail-column">
              {detailPanel}
              {chatPanel}
            </div>
          )}
        </div>
      ) : (
        // Desktop/tablet: list, detail, and chat as three independent sticky
        // columns, always visible together — chat never ends up "below the fold".
        <div className="dashboard-body">
          <IssueList
            issues={issues}
            selectedId={selectedId}
            onSelect={setSelectedId}
            severityFilter={severityFilter}
            onSeverityFilterChange={setSeverityFilter}
            typeFilter={typeFilter}
            onTypeFilterChange={setTypeFilter}
          />
          {detailPanel}
          {chatPanel}
        </div>
      )}
    </div>
  );
}

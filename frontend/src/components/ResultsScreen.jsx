import { useCallback, useEffect, useMemo, useState } from "react";

import IssueList from "./IssueList.jsx";
import IssueDetail from "./IssueDetail.jsx";
import ChatPanel from "./ChatPanel.jsx";
import SummaryBar from "./SummaryBar.jsx";
import BulkFixBar from "./BulkFixBar.jsx";

import {
  explainIssue,
  sendChatMessage,
  requestFix,
  downloadFixedProject,
  requestFixAll,
  downloadAllFixedProject,
} from "../api/analysisApi.js";


/* =========================================================
   MOBILE BREAKPOINT HOOK
   ========================================================= */

function useIsMobile(breakpoint = 900) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined"
      ? window.innerWidth < breakpoint
      : false
  );

  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [breakpoint]);

  return isMobile;
}


/* =========================================================
   RESULTS SCREEN
   ========================================================= */

export default function ResultsScreen({ result, onAnalyzeAnother }) {

  /* -------------------------------------------------------
     Responsive state
     ------------------------------------------------------- */

  const isMobile = useIsMobile();


  /* -------------------------------------------------------
     Issues
     ------------------------------------------------------- */

  const [issues, setIssues] = useState(result?.issues ?? []);

  const [selectedId, setSelectedId] = useState(
    result?.issues?.[0]?.id ?? null
  );

  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");


  /* -------------------------------------------------------
     Explanation state
     ------------------------------------------------------- */

  const [explainingId, setExplainingId] = useState(null);
  const [explainError, setExplainError] = useState(null);


  /* -------------------------------------------------------
     Chat state
     ------------------------------------------------------- */

  const [chatHistories, setChatHistories] = useState({});
  const [chatSendingId, setChatSendingId] = useState(null);
  const [chatError, setChatError] = useState(null);


  /* -------------------------------------------------------
     Individual fix state
     ------------------------------------------------------- */

  const [fixResults, setFixResults] = useState({});
  const [fixingId, setFixingId] = useState(null);
  const [fixError, setFixError] = useState(null);

  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadError, setDownloadError] = useState(null);


  /* -------------------------------------------------------
     Bulk fix state
     ------------------------------------------------------- */

  const [bulkFixResult, setBulkFixResult] = useState(null);
  const [isBulkFixing, setIsBulkFixing] = useState(false);
  const [bulkFixError, setBulkFixError] = useState(null);

  const [isBulkDownloading, setIsBulkDownloading] = useState(false);
  const [bulkDownloadError, setBulkDownloadError] = useState(null);


  /* =======================================================
     SELECTED ISSUE
     ======================================================= */

  const selectedIssue = useMemo(() => {
    if (!selectedId) {
      return null;
    }

    return (
      issues.find((issue) => issue.id === selectedId) ?? null
    );
  }, [issues, selectedId]);


  /* =======================================================
     EXPLAIN ISSUE
     ======================================================= */

  const handleExplainIssue = useCallback(
    async (issue) => {
      if (!issue) {
        return;
      }

      setExplainingId(issue.id);
      setExplainError(null);

      try {
        const explanation = await explainIssue(
          result.job_id,
          issue.id
        );

        console.log("AI EXPLANATION RESPONSE:", explanation);

        setIssues((currentIssues) =>
          currentIssues.map((currentIssue) =>
            currentIssue.id === issue.id
              ? {
                ...currentIssue,
                explanation,
              }
              : currentIssue
          )
        );
      } catch (err) {
        console.error("Explain issue error:", err);

        setExplainError(
          err?.message || "Failed to explain this issue."
        );
      } finally {
        setExplainingId(null);
      }
    },
    [result.job_id]
  );

  /* =======================================================
     REQUEST INDIVIDUAL FIX
     ======================================================= */

  const handleRequestFix = useCallback(
    async (issue) => {
      if (!issue) {
        return;
      }

      setFixingId(issue.id);
      setFixError(null);

      try {
        const fixResult = await requestFix(
          result.job_id,
          issue.id
        );

        setFixResults((currentResults) => ({
          ...currentResults,
          [issue.id]: fixResult,
        }));
      } catch (err) {
        console.error("Request fix error:", err);

        setFixError(
          err?.message || "Failed to generate a fix."
        );
      } finally {
        setFixingId(null);
      }
    },
    [result.job_id]
  );


  /* =======================================================
     DOWNLOAD INDIVIDUAL FIXED PROJECT
     ======================================================= */

  const handleDownloadFixedProject = useCallback(
    async (issue) => {
      if (!issue) {
        return;
      }

      setDownloadingId(issue.id);
      setDownloadError(null);

      try {
        await downloadFixedProject(
          result.job_id,
          issue.id
        );
      } catch (err) {
        console.error("Download fixed project error:", err);

        setDownloadError(
          err?.message || "Failed to download the fixed project."
        );
      } finally {
        setDownloadingId(null);
      }
    },
    [result.job_id]
  );


  /* =======================================================
     CHAT
     ======================================================= */

  const handleSendChatMessage = useCallback(
    async (message) => {
      if (!selectedIssue || !message?.trim()) {
        return;
      }

      const issueId = selectedIssue.id;

      setChatSendingId(issueId);
      setChatError(null);

      const userMessage = {
        role: "user",
        content: message,
      };

      setChatHistories((currentHistories) => ({
        ...currentHistories,
        [issueId]: [
          ...(currentHistories[issueId] ?? []),
          userMessage,
        ],
      }));

      try {
        const response = await sendChatMessage(
          result.job_id,
          selectedIssue.id,
          message
        );

        const assistantMessage = {
          role: "assistant",
          content:
            response?.message ??
            response?.reply ??
            response?.content ??
            String(response ?? ""),
        };

        setChatHistories((currentHistories) => ({
          ...currentHistories,
          [issueId]: [
            ...(currentHistories[issueId] ?? []),
            assistantMessage,
          ],
        }));
      } catch (err) {
        console.error("Chat error:", err);

        setChatError(
          err?.message || "Failed to send chat message."
        );
      } finally {
        setChatSendingId(null);
      }
    },
    [result.job_id, selectedIssue]
  );


  /* =======================================================
     BULK FIX
     ======================================================= */

  const handleFixAll = useCallback(async () => {
    setBulkFixError(null);
    setBulkFixResult(null);
    setIsBulkFixing(true);

    try {
      const bulkResult = await requestFixAll(result.job_id);

      setBulkFixResult(bulkResult);
    } catch (err) {
      console.error("Bulk fix error:", err);

      setBulkFixError(
        err?.message || "Failed to fix all issues."
      );
    } finally {
      setIsBulkFixing(false);
    }
  }, [result.job_id]);


  /* =======================================================
     DOWNLOAD ALL FIXED PROJECT
     ======================================================= */

  const handleDownloadAllFixed = useCallback(async () => {
    setBulkDownloadError(null);
    setIsBulkDownloading(true);

    try {
      await downloadAllFixedProject(result.job_id);
    } catch (err) {
      console.error("Bulk download error:", err);

      setBulkDownloadError(
        err?.message || "Failed to download the fixed project."
      );
    } finally {
      setIsBulkDownloading(false);
    }
  }, [result.job_id]);


  /* =======================================================
     PARSE WARNINGS
     ======================================================= */

  const hasParseWarnings =
    (result?.css_parse_errors?.length ?? 0) > 0 ||
    (result?.jsx_parse_errors?.length ?? 0) > 0;


  /* =======================================================
     MOBILE VIEW STATE
     ======================================================= */

  const showListOnMobile =
    isMobile && !selectedId;

  const showDetailOnMobile =
    isMobile && !!selectedId;


  /* =======================================================
     DETAIL PANEL
     ======================================================= */

  const detailPanel = (
    <IssueDetail
      issue={selectedIssue}
      onBack={() => setSelectedId(null)}

      isMobile={isMobile}

      isExplaining={
        explainingId === selectedIssue?.id
      }

      explainError={explainError}

      fixResult={
        selectedIssue
          ? fixResults[selectedIssue.id]
          : null
      }

      isFixing={
        fixingId === selectedIssue?.id
      }

      fixError={fixError}

      isDownloading={
        downloadingId === selectedIssue?.id
      }

      downloadError={downloadError}

      onExplainIssue={() =>
        handleExplainIssue(selectedIssue)
      }

      onRequestFix={() =>
        handleRequestFix(selectedIssue)
      }

      onDownloadFixedProject={() =>
        handleDownloadFixedProject(selectedIssue)
      }
    />
  );


  /* =======================================================
     CHAT PANEL
     ======================================================= */

  const chatPanel = (
    <ChatPanel
      issue={selectedIssue}

      messages={
        chatHistories[selectedIssue?.id] ?? []
      }

      onSendMessage={handleSendChatMessage}

      isSending={
        chatSendingId === selectedIssue?.id
      }

      sendError={chatError}
    />
  );


  /* =======================================================
     RENDER
     ======================================================= */

  return (
    <div className="results-screen">

      {/* =================================================
          HEADER
          ================================================= */}

      <header className="dashboard-header">

        <div>
          <h1>Analysis Results</h1>

          <p className="dashboard-header__subtitle">
            {result.total_css_files_parsed} CSS files
            {" · "}
            {result.total_jsx_files_parsed} JSX/JS files parsed
          </p>
        </div>

        <button
          className="secondary-button"
          onClick={onAnalyzeAnother}
        >
          Analyze another project
        </button>

      </header>


      {/* =================================================
          SUMMARY
          ================================================= */}

      <SummaryBar
        result={{
          ...result,
          issues,
        }}
      />


      {/* =================================================
          BULK FIX BAR
          ================================================= */}

      <BulkFixBar
        totalIssues={issues.length}

        bulkFixResult={bulkFixResult}
        isBulkFixing={isBulkFixing}
        bulkFixError={bulkFixError}

        isBulkDownloading={isBulkDownloading}
        bulkDownloadError={bulkDownloadError}

        onFixAll={handleFixAll}
        onDownloadAllFixed={handleDownloadAllFixed}
      />


      {/* =================================================
          PARSE WARNINGS
          ================================================= */}

      {hasParseWarnings && (
        <div className="parse-warnings">

          <h3>Parse warnings</h3>

          {(result.css_parse_errors ?? []).map(
            (error, index) => (
              <p key={`css-err-${index}`}>
                {error}
              </p>
            )
          )}

          {(result.jsx_parse_errors ?? []).map(
            (error, index) => (
              <p key={`jsx-err-${index}`}>
                {error}
              </p>
            )
          )}

        </div>
      )}


      {/* =================================================
          NO ISSUES
          ================================================= */}

      {issues.length === 0 ? (

        <div className="empty-project-state">
          <p>
            No issues found. This project's CSS class
            usage looks clean.
          </p>
        </div>

      ) : isMobile ? (

        /* =================================================
           MOBILE
           ================================================= */

        <div className="dashboard-body dashboard-body--mobile">

          {showListOnMobile && (
            <IssueList
              issues={issues}
              selectedId={selectedId}
              onSelect={setSelectedId}

              severityFilter={severityFilter}
              onSeverityFilterChange={
                setSeverityFilter
              }

              typeFilter={typeFilter}
              onTypeFilterChange={
                setTypeFilter
              }
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

        /* =================================================
           DESKTOP / TABLET
           ================================================= */

        <div className="dashboard-body">

          <IssueList
            issues={issues}
            selectedId={selectedId}
            onSelect={setSelectedId}

            severityFilter={severityFilter}
            onSeverityFilterChange={
              setSeverityFilter
            }

            typeFilter={typeFilter}
            onTypeFilterChange={
              setTypeFilter
            }
          />

          {detailPanel}

          {chatPanel}

        </div>
      )}

    </div>
  );
}
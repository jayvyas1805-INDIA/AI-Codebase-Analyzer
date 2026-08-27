import { SEVERITY_META, ISSUE_TYPE_META, FILE_LEVEL_ISSUE_TYPES } from "../utils/issueMeta.js";
import DiffTable from "./DiffTable.jsx";
import SkeletonLines from "./SkeletonLines.jsx";

export default function IssueDetail({ issue, onBack, isMobile, isExplaining, explainError }) {
  if (!issue) {
    return (
      <div className="issue-detail issue-detail--empty">
        <EmptyIcon />
        <p>Select an issue from the list to see its details.</p>
      </div>
    );
  }

  const sevMeta = SEVERITY_META[issue.severity] ?? { label: issue.severity };
  const typeMeta = ISSUE_TYPE_META[issue.issue_type] ?? { label: issue.issue_type };
  const isFileLevel = FILE_LEVEL_ISSUE_TYPES.has(issue.issue_type);
  const hasMultipleDefs = issue.css_definitions.length >= 2;
  const hasSingleDef = issue.css_definitions.length === 1;

  return (
    <div className="issue-detail">
      {isMobile && (
        <button className="back-link" onClick={onBack}>
          &larr; Back to issues
        </button>
      )}

      <div className="issue-detail__badges">
        <span className={`badge badge--${issue.severity}`}>{sevMeta.label} severity</span>
        <span className="badge badge--type">{typeMeta.label}</span>
        <span className="badge badge--confidence">{issue.confidence} confidence</span>
      </div>

      <h2 className={`issue-detail__class ${isFileLevel ? "issue-detail__class--file" : ""}`}>
        {isFileLevel ? issue.class_name : `.${issue.class_name}`}
      </h2>
      <p className="issue-detail__message">{issue.message}</p>

      {hasMultipleDefs && (
        <section>
          <h3>Definitions compared</h3>
          <DiffTable definitions={issue.css_definitions} />
        </section>
      )}

      {hasSingleDef && (
        <section>
          <h3>CSS definition</h3>
          <pre className="code-block">
            {issue.css_definitions[0].file_path}:{issue.css_definitions[0].line_number}
            {"\n"}.{issue.class_name} {"{"}
            {issue.css_definitions[0].declarations
              .map((d) => `\n  ${d.property}: ${d.value};`)
              .join("")}
            {"\n}"}
          </pre>
        </section>
      )}

      {issue.jsx_usages.length > 0 && (
        <section>
          <h3>Used in</h3>
          <ul className="usage-list">
            {issue.jsx_usages.map((u, i) => (
              <li key={i}>
                <code>
                  {u.file_path}:{u.line_number}
                </code>{" "}
                &lt;{u.element}&gt;
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="ai-section">
        <h3>AI explanation</h3>
        {isExplaining ? (
          <SkeletonLines lines={3} />
        ) : explainError ? (
          <p className="ai-error">
            <ErrorIcon /> {explainError}
          </p>
        ) : (
          <p>{issue.ai_explanation || "Not available."}</p>
        )}
      </section>

      {!isExplaining && !explainError && issue.ai_recommendation && (
        <section className="ai-section ai-section--recommendation">
          <h3>Recommendation</h3>
          <p>{issue.ai_recommendation}</p>
        </section>
      )}
    </div>
  );
}

function EmptyIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" className="empty-icon">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.5" />
      <path d="M20 20L16.5 16.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ verticalAlign: "-2px", marginRight: "4px" }}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5" />
      <path d="M12 8v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="12" cy="16" r="0.8" fill="currentColor" />
    </svg>
  );
}

import { SEVERITY_META, ISSUE_TYPE_META } from "../utils/issueMeta.js";

const SEVERITY_FILTERS = ["all", "high", "medium", "low"];
const TYPE_FILTERS = [
  "all",
  "css_conflict",
  "partial_overlap_class",
  "duplicate_class",
  "unused_css_class",
  "undefined_css_class",
];

export default function IssueList({
  issues,
  selectedId,
  onSelect,
  severityFilter,
  onSeverityFilterChange,
  typeFilter,
  onTypeFilterChange,
}) {
  const filtered = issues.filter(
    (i) =>
      (severityFilter === "all" || i.severity === severityFilter) &&
      (typeFilter === "all" || i.issue_type === typeFilter)
  );

  return (
    <div className="issue-list">
      <div className="filter-row">
        {SEVERITY_FILTERS.map((s) => (
          <button
            key={s}
            className={`chip ${severityFilter === s ? "chip--active" : ""}`}
            onClick={() => onSeverityFilterChange(s)}
          >
            {s === "all" ? "All severities" : SEVERITY_META[s].label}
          </button>
        ))}
      </div>

      <div className="filter-row">
        {TYPE_FILTERS.map((t) => (
          <button
            key={t}
            className={`chip ${typeFilter === t ? "chip--active" : ""}`}
            onClick={() => onTypeFilterChange(t)}
          >
            {t === "all" ? "All types" : ISSUE_TYPE_META[t]?.short ?? t}
          </button>
        ))}
      </div>

      <p className="issue-count">
        {filtered.length} issue{filtered.length !== 1 ? "s" : ""}
      </p>

      {filtered.length === 0 && <p className="empty-state">No issues match these filters.</p>}

      <ul className="issue-rows">
        {filtered.map((issue) => (
          <li key={issue.id}>
            <button
              className={`issue-row ${selectedId === issue.id ? "issue-row--selected" : ""}`}
              onClick={() => onSelect(issue.id)}
            >
              <span className={`dot dot--${issue.severity}`} aria-hidden="true" />
              <span className="issue-row__main">
                <span className="issue-row__class">.{issue.class_name}</span>
                <span className="issue-row__type">
                  {ISSUE_TYPE_META[issue.issue_type]?.short ?? issue.issue_type}
                </span>
              </span>
              <span className={`badge badge--${issue.severity} badge--small`}>
                {SEVERITY_META[issue.severity]?.label ?? issue.severity}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

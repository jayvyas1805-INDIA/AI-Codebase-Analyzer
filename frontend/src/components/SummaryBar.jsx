export default function SummaryBar({ result }) {
  const stats = [
    { label: "Issues found", value: result.total_issues, tone: "accent" },
    {
      label: "High severity",
      value: result.issues.filter((i) => i.severity === "high").length,
      tone: "high",
    },
    {
      label: "Medium severity",
      value: result.issues.filter((i) => i.severity === "medium").length,
      tone: "medium",
    },
    {
      label: "Low severity",
      value: result.issues.filter((i) => i.severity === "low").length,
      tone: "low",
    },
    {
      label: "Dynamic classNames",
      value: result.project_has_dynamic_classnames ? "Yes" : "No",
      tone: "neutral",
    },
  ];

  return (
    <div className="summary-bar">
      {stats.map((s) => (
        <div key={s.label} className={`stat stat--${s.tone}`}>
          <span className="stat__value">{s.value}</span>
          <span className="stat__label">{s.label}</span>
        </div>
      ))}
    </div>
  );
}

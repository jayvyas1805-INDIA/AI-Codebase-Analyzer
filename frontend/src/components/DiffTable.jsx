/**
 * The signature visual of the dashboard: shows every CSS property across
 * all definitions of a class name, one column per file, with rows where
 * the value DISAGREES highlighted. This directly mirrors the backend's own
 * conflict-detection logic (shared vs conflicting properties) rather than
 * being decorative — it's the actual evidence for the finding.
 */
export default function DiffTable({ definitions }) {
  if (definitions.length < 2) return null;

  const allProps = [...new Set(definitions.flatMap((d) => d.declarations.map((x) => x.property)))];

  return (
    <div className="diff-table-wrap">
      <table className="diff-table">
        <thead>
          <tr>
            <th className="diff-table__prop-header">property</th>
            {definitions.map((d) => {
              const parts = d.file_path.split(/[/\\]/);
              const filename = parts.pop();
              const dir = parts.join("/");
              return (
                <th key={d.file_path} title={d.file_path}>
                  <span className="diff-table__filename">{filename}</span>
                  {dir && <span className="diff-table__dir">{dir}/</span>}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {allProps.map((prop) => {
            const values = definitions.map(
              (d) => d.declarations.find((x) => x.property === prop)?.value ?? "—"
            );
            const distinct = new Set(values.filter((v) => v !== "—"));
            const conflicting = distinct.size > 1;

            return (
              <tr key={prop} className={conflicting ? "diff-row--conflict" : ""}>
                <td className="diff-table__prop">{prop}</td>
                {values.map((v, i) => (
                  <td key={i}>{v}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

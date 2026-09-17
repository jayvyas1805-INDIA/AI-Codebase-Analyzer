export default function BulkFixBar({
  totalIssues,
  bulkFixResult,
  isBulkFixing,
  bulkFixError,
  isBulkDownloading,
  bulkDownloadError,
  onFixAll,
  onDownloadAllFixed,
}) {
  if (totalIssues === 0) return null;

  return (
    <div className="bulk-fix-bar">
      <div className="bulk-fix-bar__main">
        <div className="bulk-fix-bar__copy">
          <h3>Fix all {totalIssues} issue{totalIssues !== 1 ? "s" : ""} at once</h3>
          <p>
            Runs the AI plan &rarr; patch &rarr; sandbox-validate loop across every issue,
            so you don&rsquo;t have to fix each one by hand. Nothing touches your real files
            until you download the result.
          </p>
        </div>
        <button className="primary-button" onClick={onFixAll} disabled={isBulkFixing}>
          {isBulkFixing ? "Fixing all issues…" : "Fix all issues with AI"}
        </button>
      </div>

      {bulkFixError && (
        <p className="ai-error bulk-fix-bar__error">{bulkFixError}</p>
      )}

      {bulkFixResult && (
        <div className="bulk-fix-bar__summary">
          <div className="bulk-fix-bar__stats">
            <span className="bulk-stat bulk-stat--success">{bulkFixResult.fixed_count} fixed</span>
            <span className="bulk-stat bulk-stat--fail">{bulkFixResult.failed_count} failed</span>
            <span className="bulk-stat bulk-stat--neutral">{bulkFixResult.skipped_count} not auto-fixable</span>
            <span className="bulk-stat bulk-stat--neutral">{bulkFixResult.total_issues} total</span>
          </div>

          {bulkFixResult.fixed_count > 0 && (
            <button
              className="secondary-button"
              onClick={onDownloadAllFixed}
              disabled={isBulkDownloading}
            >
              {isBulkDownloading
                ? "Packaging zip…"
                : `Download all ${bulkFixResult.fixed_count} fixed issue${bulkFixResult.fixed_count !== 1 ? "s" : ""} (.zip)`}
            </button>
          )}
          {bulkDownloadError && (
            <p className="ai-error bulk-fix-bar__error">{bulkDownloadError}</p>
          )}

          {(bulkFixResult.failed_count > 0 || bulkFixResult.skipped_count > 0) && (
            <details className="bulk-fix-bar__details">
              <summary>
                See which issues weren&rsquo;t fixed ({bulkFixResult.failed_count + bulkFixResult.skipped_count})
              </summary>
              <ul>
                {bulkFixResult.results
                  .filter((r) => !r.success)
                  .map((r) => (
                    <li key={r.issue_id}>
                      <code>.{r.class_name}</code> — {r.message}
                    </li>
                  ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

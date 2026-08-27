/**
 * Animated placeholder bars shown while content is loading (e.g. an AI
 * explanation being generated). Widths vary per line so it doesn't look
 * like a rigid block — mimics where text would actually wrap.
 */
export default function SkeletonLines({ lines = 3 }) {
  const widths = ["92%", "78%", "60%", "85%", "45%"];
  return (
    <div className="skeleton-lines" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton-line" style={{ width: widths[i % widths.length] }} />
      ))}
    </div>
  );
}

/**
 * Renders the subset of markdown the LLM actually produces in AI replies
 * (chat, explanations, recommendations): headings (#/##/###), fenced code
 * blocks, pipe tables, bullet/numbered lists, and paragraphs — each with
 * inline `code`, **bold**, and *italic*.
 *
 * Shared by ChatPanel.jsx and IssueDetail.jsx so every place the app shows
 * raw AI text renders it the same way, instead of some spots showing
 * literal "### " / "| a | b |" markdown notation and others not.
 *
 * 100% plain-text in, React elements out — never dangerouslySet, so
 * there's no HTML-injection surface from LLM output.
 */
export function renderRichText(text) {
  if (!text) return null;

  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i++;
      continue;
    }

    // Fenced code block ```...```
    if (line.trim().startsWith("```")) {
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing fence
      blocks.push({ type: "code", content: codeLines.join("\n") });
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, content: headingMatch[2] });
      i++;
      continue;
    }

    // Table: a header row followed by a |---|---| separator row
    if (line.includes("|") && lines[i + 1] && /^\s*\|?[\s:|-]+\|[\s:|-]*\|?\s*$/.test(lines[i + 1])) {
      const parseRow = (row) =>
        row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      const header = parseRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(parseRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    // Bullet or numbered list — consume consecutive list lines together
    const bulletMatch = line.match(/^\s*[-*]\s+(.*)/);
    const numberedMatch = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (bulletMatch || numberedMatch) {
      const ordered = !!numberedMatch;
      const items = [];
      while (i < lines.length) {
        const m = ordered ? lines[i].match(/^\s*\d+[.)]\s+(.*)/) : lines[i].match(/^\s*[-*]\s+(.*)/);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    // Paragraph — consume until a blank line or the start of another block type
    const paraLines = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !/^#{1,6}\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ type: "paragraph", lines: paraLines });
  }

  return blocks.map((block, idx) => {
    switch (block.type) {
      case "heading": {
        const Tag = `h${Math.min(block.level + 3, 6)}`; // h4/h5/h6 — stays proportionate inline
        return <Tag key={idx} className="md-heading">{renderInline(block.content)}</Tag>;
      }
      case "code":
        return (
          <pre key={idx} className="md-code">
            <code>{block.content}</code>
          </pre>
        );
      case "table":
        return (
          <div key={idx} className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>
                  {block.header.map((cell, c) => (
                    <th key={c}>{renderInline(cell)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c}>{renderInline(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case "list": {
        const ListTag = block.ordered ? "ol" : "ul";
        return (
          <ListTag key={idx} className="md-list">
            {block.items.map((item, li) => (
              <li key={li}>{renderInline(item)}</li>
            ))}
          </ListTag>
        );
      }
      case "paragraph":
      default:
        return (
          <p key={idx}>
            {block.lines.map((line, lIdx) => (
              <span key={lIdx}>
                {lIdx > 0 && <br />}
                {renderInline(line)}
              </span>
            ))}
          </p>
        );
    }
  });
}

function renderInline(line) {
  const parts = line
    .split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g)
    .filter((p) => p !== "");
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

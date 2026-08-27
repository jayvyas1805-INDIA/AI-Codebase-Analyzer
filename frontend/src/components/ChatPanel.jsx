import { useEffect, useRef, useState } from "react";

/**
 * Always-visible chat panel scoped to whichever issue is currently
 * selected. Message history and send logic are owned by the parent
 * (ResultsScreen) so they survive switching between issues and back.
 */
export default function ChatPanel({ issue, messages, onSendMessage, isSending, sendError }) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  if (!issue) {
    return (
      <div className="chat-panel chat-panel--empty">
        <p>Select an issue to ask questions about it.</p>
      </div>
    );
  }

  function handleSubmit(e) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || isSending) return;
    setDraft("");
    onSendMessage(text);
  }

  return (
    <div className="chat-panel">
      <h3 className="chat-panel__title">
        Ask about <code>.{issue.class_name}</code>
      </h3>

      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && !isSending && (
          <p className="chat-empty">
            Ask a follow-up question — e.g. "why does the last-loaded file win?"
          </p>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble chat-bubble--${m.role}`}>
            {m.content}
          </div>
        ))}

        {isSending && (
          <div className="chat-bubble chat-bubble--assistant chat-bubble--pending">
            <TypingDots />
          </div>
        )}

        {sendError && <div className="chat-error">{sendError}</div>}
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question about this issue…"
          disabled={isSending}
        />
        <button type="submit" disabled={isSending || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="typing-dots" aria-label="Thinking">
      <span />
      <span />
      <span />
    </span>
  );
}

import { useEffect, useRef, useState } from "react";
import { renderRichText } from "../utils/richText.jsx";

const SUGGESTED_PROMPTS = [
  "Why do these actually conflict?",
  "Is renaming safe here?",
  "Which definition should win?",
];

/**
 * Always-visible chat panel scoped to whichever issue is currently
 * selected. Message history and send logic are owned by the parent
 * (ResultsScreen) so they survive switching between issues and back.
 */
export default function ChatPanel({ issue, messages, onSendMessage, isSending, sendError }) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  if (!issue) {
    return (
      <div className="chat-panel chat-panel--empty">
        <AiGlyph size={22} />
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

  function handlePromptChip(prompt) {
    setDraft(prompt);
    inputRef.current?.focus();
  }

  return (
    <div className="chat-panel">
      <div className="chat-panel__header">
        <span className="chat-panel__live-dot" aria-hidden="true" />
        <h3 className="chat-panel__title">
          Ask about <code>.{issue.class_name}</code>
        </h3>
      </div>

      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && !isSending && (
          <div className="chat-empty">
            <p>Ask a follow-up — e.g. "why does the last-loaded file win?"</p>
            <div className="chat-prompt-chips">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="chat-prompt-chip"
                  onClick={() => handlePromptChip(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`chat-row chat-row--${m.role}`}>
            {m.role === "assistant" && (
              <div className="chat-avatar chat-avatar--assistant">
                <AiGlyph size={14} />
              </div>
            )}
            <div className={`chat-bubble chat-bubble--${m.role}`}>
              {m.role === "assistant" ? renderRichText(m.content) : m.content}
            </div>
            {m.role === "user" && <div className="chat-avatar chat-avatar--user">you</div>}
          </div>
        ))}

        {isSending && (
          <div className="chat-row chat-row--assistant">
            <div className="chat-avatar chat-avatar--assistant chat-avatar--pulse">
              <AiGlyph size={14} />
            </div>
            <div className="chat-bubble chat-bubble--assistant chat-bubble--pending">
              <TypingDots />
            </div>
          </div>
        )}

        {sendError && <div className="chat-error">{sendError}</div>}
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question about this issue…"
          disabled={isSending}
        />
        <button type="submit" disabled={isSending || !draft.trim()} aria-label="Send">
          <SendIcon />
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

function AiGlyph({ size = 16 }) {
  // A small angular spark, not a generic robot/sparkle emoji — reads as
  // "signal" rather than decoration, and scales cleanly at any size.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2L14.2 9.4L21.5 12L14.2 14.6L12 22L9.8 14.6L2.5 12L9.8 9.4L12 2Z"
        fill="currentColor"
      />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 12L20.5 4L14 20L11 13L3 12Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

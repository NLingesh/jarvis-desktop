import React, { useState, useEffect, useRef, useCallback } from 'react';
import './ChatView.css';
import { searchMemory } from '../../api/memory';
import { withTimeout } from '../../voiceDiagnostics';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  voiceCaption?: string;
}

interface MemoryChip {
  id: string;
  title: string;
  category: string;
}

const SUGGESTED_PROMPTS = [
  'What can you help me with?',
  'Summarize my recent activity',
  'Open my project files',
  'Set a reminder for tomorrow',
];

const ChatView: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [, setStreamingId] = useState<string | null>(null);
  const [memoryChips, setMemoryChips] = useState<MemoryChip[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current);
    }
    if (!input.trim()) {
      setMemoryChips([]);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const data = await searchMemory(input.trim());
        const chips: MemoryChip[] = (data.results || []).slice(0, 5).map((r: any) => ({
          id: r.id || r.path || Math.random().toString(),
          title: r.title || r.content?.slice(0, 40) || 'Memory',
          category: r.category || r.type || 'Memory',
        }));
        setMemoryChips(chips);
      } catch {
        setMemoryChips([]);
      }
    }, 400);
    return () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
      }
    };
  }, [input]);

  const dismissMemoryChip = useCallback((id: string) => {
    setMemoryChips((prev) => prev.filter((c) => c.id !== id));
  }, []);

  const handleSend = useCallback(
    async (providedText?: string) => {
      const text = (providedText ?? input).trim();
      if (!text || isLoading) return;
      setInput('');
      setMemoryChips([]);
      const userMsg: Message = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };
      const assistantId = `assistant-${Date.now()}`;
      const assistantMsg: Message = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        isStreaming: true,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setStreamingId(assistantId);
      setIsLoading(true);

      try {
        // Route typed chat through the orchestrator-backed /api/chat endpoint so
        // desktop commands dispatch real tools (open_folder, etc.) instead of the
        // bare-LLM /api/llm/generate path that only produced generic refusals.
        const api = (window as any).electronAPI;
        const token = api?.getSessionToken
          ? ((await api.getSessionToken()) as string | null)
          : null;
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers['X-Jarvis-Token'] = token;
        const session_id = localStorage.getItem('jarvis_chat_session') || undefined;
        // Bound the request so the panel can never hang in a streaming state
        // forever if the backend (or its LLM) stalls.
        const response = await withTimeout(
          fetch('/api/chat', {
            method: 'POST',
            headers,
            body: JSON.stringify({ message: text, session_id }),
          }),
          60000,
          'JARVIS took too long to respond. Please try again.',
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as {
          text?: string;
          session_id?: string;
          tool_results?: Array<{ tool?: string; result?: { success?: boolean } }>;
        };
        if (payload.session_id) localStorage.setItem('jarvis_chat_session', payload.session_id);
        const accumulated = payload.text || 'I did not receive a response.';
        const verified = (payload.tool_results || []).filter((t) => t.result?.success);
        const display = verified.length
          ? `${accumulated}\n\n${verified.map((t) => `✓ ${t.tool || 'action'} completed`).join('\n')}`
          : accumulated;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: display, isStreaming: false } : m,
          ),
        );
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: 'Sorry, I encountered an error. Please try again.',
                  isStreaming: false,
                }
              : m,
          ),
        );
      } finally {
        setIsLoading(false);
        setStreamingId(null);
      }
    },
    [input, isLoading],
  );

  const handleRegenerate = useCallback(
    async (messageId: string) => {
      const idx = messages.findIndex((m) => m.id === messageId);
      if (idx < 1) return;
      const prevUserMsg = messages[idx - 1];
      setMessages((prev) => prev.slice(0, idx));
      setInput(prevUserMsg.content);
      setTimeout(() => handleSend(), 50);
    },
    [messages, handleSend],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const formatContent = (text: string) => {
    const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match;
    let key = 0;

    while ((match = codeBlockRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(<span key={`t-${key++}`}>{text.slice(lastIndex, match.index)}</span>);
      }
      const lang = match[1] || 'code';
      const code = match[2];
      parts.push(
        <div key={`c-${key++}`} className="code-block">
          <div className="code-block-header">
            <span className="code-lang">{lang}</span>
            <button
              className="code-copy-btn"
              onClick={() => navigator.clipboard.writeText(code)}
              aria-label="Copy code"
            >
              Copy
            </button>
          </div>
          <pre className="code-pre">
            <code>{code}</code>
          </pre>
        </div>,
      );
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < text.length) {
      parts.push(<span key={`t-${key++}`}>{text.slice(lastIndex)}</span>);
    }

    return parts.length > 0 ? parts : text;
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="chat-view">
      {isEmpty ? (
        <div className="chat-empty">
          <div className="chat-empty-orb" aria-hidden="true" />
          <h2 className="chat-empty-title">Hello, I'm JARVIS</h2>
          <p className="chat-empty-subtitle">Your desktop companion. How can I help?</p>
          <div className="chat-suggestions">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                className="chat-suggestion"
                onClick={() => {
                  setInput(prompt);
                  void handleSend(prompt);
                }}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="chat-messages">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-bubble ${msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}
            >
              <div className="chat-bubble-content">
                {msg.role === 'assistant' ? formatContent(msg.content) : msg.content}
                {msg.isStreaming && <span className="chat-caret" aria-hidden="true" />}
              </div>
              {msg.role === 'assistant' && msg.content && !msg.isStreaming && (
                <button
                  className="chat-regenerate"
                  onClick={() => handleRegenerate(msg.id)}
                  aria-label="Regenerate response"
                  title="Regenerate"
                >
                  Regenerate
                </button>
              )}
              {msg.voiceCaption && (
                <div className="chat-voice-caption" aria-live="polite">
                  {msg.voiceCaption}
                </div>
              )}
              <time className="chat-time">
                {new Date(msg.timestamp).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </time>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {isLoading && messages.some((m) => m.isStreaming) && (
        <div className="chat-loading">
          <span className="loading-dot" />
          <span className="loading-dot" />
          <span className="loading-dot" />
        </div>
      )}

      {memoryChips.length > 0 && (
        <div className="memory-chips" aria-label="Related memories">
          {memoryChips.map((chip) => (
            <button
              key={chip.id}
              className="memory-chip"
              onClick={() => dismissMemoryChip(chip.id)}
              title={`${chip.category}: ${chip.title}`}
            >
              <span className="memory-chip-category">{chip.category}</span>
              <span className="memory-chip-title">{chip.title}</span>
              <span className="memory-chip-dismiss" aria-label="Dismiss">
                ×
              </span>
            </button>
          ))}
        </div>
      )}

      <form
        className="chat-input-form"
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
          aria-label="Chat message input"
          disabled={isLoading}
        />
        <button type="submit" disabled={!input.trim() || isLoading} aria-label="Send">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M2 8h12M9 4l4 4-4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </div>
  );
};

export default ChatView;

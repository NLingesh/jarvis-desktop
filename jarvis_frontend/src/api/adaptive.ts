function getBaseUrl(): string {
  const server = localStorage.getItem('serverUrl') || 'localhost:8000';
  const trimmed = server.trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function getBehaviorAnalysis(sessionId?: string): Promise<any> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  return request(`/api/adaptive/behavior${qs}`);
}

export function getInsights(): Promise<any> {
  return request('/api/adaptive/insights');
}

export function getSuggestions(sessionId?: string): Promise<{ suggestions: string[] }> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  return request(`/api/adaptive/suggestions${qs}`);
}

export function learnFromInteraction(payload: {
  session_id: string;
  user_input: string;
  response: string;
  tool_used?: string;
}): Promise<{ learned: boolean }> {
  return request('/api/adaptive/learn', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function recordFeedback(payload: {
  session_id: string;
  prediction: string;
  actual: string;
  correct: boolean;
}): Promise<any> {
  return request('/api/adaptive/feedback', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

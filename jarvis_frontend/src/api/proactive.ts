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

export function getProactiveSuggestions(): Promise<{ suggestions: any[] }> {
  return request('/api/proactive/suggestions');
}

export function createNotification(payload: {
  title: string;
  body: string;
  context?: Record<string, unknown>;
}): Promise<any> {
  return request('/api/proactive/notifications', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function sendSuggestionFeedback(
  suggestionId: string,
  action: string,
): Promise<{ feedback_recorded: boolean }> {
  return request(`/api/proactive/suggestions/${encodeURIComponent(suggestionId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

import { request } from './baseUrl';

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

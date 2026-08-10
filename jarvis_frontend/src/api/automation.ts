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

export function listWorkflows(): Promise<{ workflows: any[] }> {
  return request<{ workflows: any[] }>('/api/automation/workflows');
}

export function createWorkflow(payload: {
  name: string;
  trigger: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  enabled?: boolean;
}): Promise<any> {
  return request('/api/automation/workflows', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function executeWorkflow(
  workflowId: string,
  context?: Record<string, unknown>,
): Promise<any> {
  return request(`/api/automation/workflows/${encodeURIComponent(workflowId)}/execute`, {
    method: 'POST',
    body: JSON.stringify({ context }),
  });
}

export function deleteWorkflow(workflowId: string): Promise<{ deleted: boolean }> {
  return request(`/api/automation/workflows/${encodeURIComponent(workflowId)}`, {
    method: 'DELETE',
  });
}

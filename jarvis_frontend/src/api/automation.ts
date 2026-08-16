import { request } from './baseUrl';

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

import { request } from './baseUrl';

export function listTasks(type?: string, status?: string): Promise<{ tasks: any[] }> {
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (status) params.set('status', status);
  const qs = params.toString();
  return request<{ tasks: any[] }>(`/api/tasks/${qs ? `?${qs}` : ''}`);
}

export function createTask(payload: {
  title: string;
  type?: string;
  cron?: string;
  due_date?: string;
  payload?: Record<string, unknown>;
  project_id?: string;
}): Promise<any> {
  return request('/api/tasks/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateTask(taskId: string, payload: Record<string, unknown>): Promise<any> {
  return request(`/api/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function completeTask(taskId: string): Promise<{ id: string; status: string }> {
  return request<{ id: string; status: string }>(
    `/api/tasks/${encodeURIComponent(taskId)}/complete`,
    { method: 'POST' },
  );
}

export function deleteTask(taskId: string): Promise<{ deleted: boolean }> {
  return request(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
}

export type ToolResult = {
  success: boolean;
  message: string;
  data?: any;
};

import { request } from './baseUrl';

export { getBaseUrl, request } from './baseUrl';

export function searchFiles(q: string): Promise<{ results: any[] }> {
  return request<{ results: any[] }>(`/api/tools/files/search?q=${encodeURIComponent(q)}`);
}

export function readFile(path: string): Promise<{ path: string; content: string; size: number }> {
  return request<{ path: string; content: string; size: number }>(
    `/api/tools/files/read?path=${encodeURIComponent(path)}`,
  );
}

export function createFile(path: string, content: string): Promise<{ path: string; size: number }> {
  return request<{ path: string; size: number }>('/api/tools/files/create', {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  });
}

export function renameFile(
  oldPath: string,
  newPath: string,
  confirm = true,
): Promise<{ old_path: string; new_path: string }> {
  return request<{ old_path: string; new_path: string }>('/api/tools/files/rename', {
    method: 'POST',
    body: JSON.stringify({ old_path: oldPath, new_path: newPath, confirm }),
  });
}

export function deleteFile(path: string, confirm = true): Promise<{ deleted: string }> {
  return request<{ deleted: string }>('/api/tools/files/delete', {
    method: 'POST',
    body: JSON.stringify({ path, confirm }),
  });
}

export function createFolder(path: string, confirm = true): Promise<{ created: string }> {
  return request<{ created: string }>('/api/tools/files/folder', {
    method: 'POST',
    body: JSON.stringify({ path, confirm }),
  });
}

export function openApp(appName: string, confirm = true): Promise<{ opened: string }> {
  return request<{ opened: string }>('/api/tools/apps/open', {
    method: 'POST',
    body: JSON.stringify({ app_name: appName, confirm }),
  });
}

export function closeApp(
  appName = '',
  pid = 0,
  confirm = true,
): Promise<{ closed: string | number[] }> {
  return request<{ closed: string | number[] }>('/api/tools/apps/close', {
    method: 'POST',
    body: JSON.stringify({ app_name: appName, pid, confirm }),
  });
}

export function executeTerminal(
  command: string,
  confirm = true,
): Promise<{ task_id: string; preview: string; status: string }> {
  return request<{ task_id: string; preview: string; status: string }>(
    '/api/tools/terminal/execute',
    {
      method: 'POST',
      body: JSON.stringify({ command, confirm }),
    },
  );
}

export function getTerminalStatus(
  taskId: string,
): Promise<{ task_id: string; status: string; output: string; returncode: number | null }> {
  return request(`/api/tools/terminal/status/${taskId}`);
}

export function readClipboard(): Promise<{ text: string }> {
  return request<{ text: string }>('/api/tools/clipboard/read');
}

export function writeClipboard(text: string, confirm = true): Promise<{ written: number }> {
  return request<{ written: number }>('/api/tools/clipboard/write', {
    method: 'POST',
    body: JSON.stringify({ text, confirm }),
  });
}

export function takeScreenshot(confirm = true): Promise<{ image_base64: string; format: string }> {
  return request<{ image_base64: string; format: string }>('/api/tools/screenshot', {
    method: 'POST',
    body: JSON.stringify({ confirm }),
  });
}

export function undoLast(): Promise<{ undone: string }> {
  return request<{ undone: string }>('/api/tools/undo', { method: 'POST' });
}

export function getAuditLog(): Promise<{ audit: any[] }> {
  return request<{ audit: any[] }>('/api/tools/audit');
}

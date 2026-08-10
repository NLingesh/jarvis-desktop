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

export function listProjects(): Promise<{ projects: any[] }> {
  return request('/api/projects/');
}

export function analyzeProject(projectId: string): Promise<any> {
  const encoded = encodeURIComponent(projectId);
  return request(`/api/projects/${encoded}/analysis`);
}

export function getGitStatus(projectPath: string): Promise<any> {
  const qs = `?project_path=${encodeURIComponent(projectPath)}`;
  return request(`/api/git/status${qs}`);
}

export function getGitDiff(projectPath: string, filePath?: string): Promise<any> {
  const params = new URLSearchParams({ project_path: projectPath });
  if (filePath) params.set('file_path', filePath);
  return request(`/api/git/diff?${params.toString()}`);
}

export function getGitLog(projectPath: string, limit: number = 20): Promise<any> {
  const qs = `?project_path=${encodeURIComponent(projectPath)}&limit=${limit}`;
  return request(`/api/git/log${qs}`);
}

export function createGitCommit(projectPath: string, message: string): Promise<any> {
  return request('/api/git/commit', {
    method: 'POST',
    body: JSON.stringify({ project_path: projectPath, message }),
  });
}

export function getGitBranches(projectPath: string): Promise<any> {
  const qs = `?project_path=${encodeURIComponent(projectPath)}`;
  return request(`/api/git/branches${qs}`);
}

export function searchCode(query: string, paths?: string[]): Promise<any> {
  const params = new URLSearchParams({ q: query });
  if (paths && paths.length) params.set('paths', paths.join(','));
  return request(`/api/code/search?${params.toString()}`);
}

export function explainCode(filePath: string, lineStart?: number, lineEnd?: number): Promise<any> {
  return request('/api/code/explain', {
    method: 'POST',
    body: JSON.stringify({ file_path: filePath, line_start: lineStart, line_end: lineEnd }),
  });
}

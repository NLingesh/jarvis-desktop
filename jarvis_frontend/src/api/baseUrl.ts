export function getBaseUrl(): string {
  if (typeof window !== 'undefined' && (window as any).electronAPI) {
    return window.location.origin;
  }
  const server = localStorage.getItem('serverUrl') || '127.0.0.1:8000';
  const trimmed = server.trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

export async function getAuthToken(): Promise<string | null> {
  if (typeof window !== 'undefined' && (window as any).electronAPI?.getSessionToken) {
    try {
      return (await (window as any).electronAPI.getSessionToken()) as string | null;
    } catch {
      /* IPC unavailable or rejected */
    }
  }
  return null;
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAuthToken();
  return token ? { 'X-Jarvis-Token': token } : {};
}

async function _fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders()),
      ...((init?.headers as Record<string, string> | undefined) ?? {}),
    },
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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const data = await _fetchJson<T>(path, init);
  const approval = data as unknown as { approval_required?: boolean; approval_id?: string };
  if (approval.approval_required && approval.approval_id) {
    let body: Record<string, unknown> = {};
    if (init?.body) {
      try {
        body = JSON.parse(init.body as string) as Record<string, unknown>;
      } catch {
        /* non-JSON body */
      }
    }
    return _fetchJson<T>(path, {
      ...init,
      body: JSON.stringify({ ...body, approval_id: approval.approval_id }),
    });
  }
  return data;
}

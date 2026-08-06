export type VaultNote = {
  path: string;
  id: string;
  title: string;
  type: string;
  tags: string[];
  aliases: string[];
  favorite: boolean;
  status?: string | null;
  created?: string | null;
  modified?: string | null;
  links: string[];
  body: string;
  folder: string;
  score?: number;
};

export type VaultMeta = {
  total: number;
  by_type: Record<string, number>;
  root: string;
  favorites: number;
  templates: Record<string, { folder: string; body: string }>;
  folders: string[];
};

export type TagCount = { tag: string; count: number };

export type CreateNoteInput = {
  title: string;
  content?: string;
  folder?: string;
  type?: string;
  tags?: string[];
  status?: string;
  source?: string;
  favorite?: boolean;
};

export type UpdateNoteInput = {
  content?: string;
  title?: string;
  tags?: string[];
  status?: string;
  favorite?: boolean;
};

export type SearchParams = {
  q?: string;
  tag?: string;
  type?: string;
  recent?: boolean;
  favorite?: boolean;
  limit?: number;
};

export function getBaseUrl(): string {
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

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : '';
}

export function getMeta(): Promise<VaultMeta> {
  return request<{ meta: VaultMeta }>('/api/vault/meta').then((d) => d.meta);
}

export function listNotes(params: {
  folder?: string;
  tag?: string;
  type?: string;
  favorite?: boolean;
  limit?: number;
}): Promise<VaultNote[]> {
  return request<{ notes: VaultNote[] }>(`/api/vault/notes${qs(params)}`).then((d) => d.notes);
}

export function getNote(path: string): Promise<VaultNote> {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return request<{ note: VaultNote }>(`/api/vault/note/${encoded}`).then((d) => d.note);
}

export function createNote(input: CreateNoteInput): Promise<VaultNote> {
  return request<{ note: VaultNote }>('/api/vault/notes', {
    method: 'POST',
    body: JSON.stringify(input),
  }).then((d) => d.note);
}

export function updateNote(path: string, input: UpdateNoteInput): Promise<VaultNote> {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return request<{ note: VaultNote }>(`/api/vault/note/${encoded}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  }).then((d) => d.note);
}

export function deleteNote(path: string): Promise<void> {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return request<{ deleted: string }>(`/api/vault/note/${encoded}`, { method: 'DELETE' }).then(
    () => undefined,
  );
}

export function appendNote(path: string, text: string): Promise<VaultNote> {
  return request<{ note: VaultNote }>('/api/vault/note/append', {
    method: 'POST',
    body: JSON.stringify({ path, text }),
  }).then((d) => d.note);
}

export function renameNote(path: string, title: string): Promise<VaultNote> {
  return request<{ note: VaultNote }>('/api/vault/note/rename', {
    method: 'POST',
    body: JSON.stringify({ path, title }),
  }).then((d) => d.note);
}

export function moveNote(path: string, folder: string): Promise<VaultNote> {
  return request<{ note: VaultNote }>('/api/vault/note/move', {
    method: 'POST',
    body: JSON.stringify({ path, folder }),
  }).then((d) => d.note);
}

export function archiveNote(path: string): Promise<VaultNote> {
  return request<{ note: VaultNote }>('/api/vault/note/archive', {
    method: 'POST',
    body: JSON.stringify({ path }),
  }).then((d) => d.note);
}

export function searchNotes(params: SearchParams): Promise<VaultNote[]> {
  return request<{ results: VaultNote[] }>(`/api/vault/search${qs(params)}`).then((d) => d.results);
}

export function getTags(): Promise<TagCount[]> {
  return request<{ tags: TagCount[] }>('/api/vault/tags').then((d) => d.tags);
}

export function getFolders(): Promise<string[]> {
  return request<{ folders: string[] }>('/api/vault/folders').then((d) => d.folders);
}

export function createFolder(folder: string): Promise<{ folder: string }> {
  return request<{ folder: string }>('/api/vault/folders', {
    method: 'POST',
    body: JSON.stringify({ folder }),
  });
}

export function reindexVault(): Promise<{ status: string }> {
  return request<{ status: string }>('/api/vault/index', { method: 'POST' });
}

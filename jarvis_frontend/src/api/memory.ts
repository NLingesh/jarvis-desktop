import { request } from './baseUrl';

export { getBaseUrl, request } from './baseUrl';

export function searchMemory(q: string): Promise<{ results: any[] }> {
  return request<{ results: any[] }>(`/api/memory/search?q=${encodeURIComponent(q)}`);
}

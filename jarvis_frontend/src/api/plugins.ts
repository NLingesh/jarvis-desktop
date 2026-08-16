import { request } from './baseUrl';

export { getBaseUrl, request } from './baseUrl';

export function listPlugins(): Promise<{ plugins: any[] }> {
  return request<{ plugins: any[] }>('/api/plugins/');
}

export function enablePlugin(name: string): Promise<{ name: string; enabled: boolean }> {
  return request<{ name: string; enabled: boolean }>(
    `/api/plugins/${encodeURIComponent(name)}/enable`,
    { method: 'POST' },
  );
}

export function disablePlugin(name: string): Promise<{ name: string; enabled: boolean }> {
  return request<{ name: string; enabled: boolean }>(
    `/api/plugins/${encodeURIComponent(name)}/disable`,
    { method: 'POST' },
  );
}

export function getPluginPermissions(
  name: string,
): Promise<{ name: string; permissions: string[]; grants: any[] }> {
  return request(`/api/plugins/${encodeURIComponent(name)}/permissions`);
}

export function grantPermission(
  name: string,
  permission: string,
): Promise<{ name: string; permission: string; granted: boolean }> {
  return request<{ name: string; permission: string; granted: boolean }>(
    `/api/plugins/${encodeURIComponent(name)}/grant`,
    {
      method: 'POST',
      body: JSON.stringify({ permission }),
    },
  );
}

export function revokePermission(
  name: string,
  permission: string,
): Promise<{ name: string; permission: string; revoked: boolean }> {
  return request<{ name: string; permission: string; revoked: boolean }>(
    `/api/plugins/${encodeURIComponent(name)}/revoke`,
    {
      method: 'POST',
      body: JSON.stringify({ permission }),
    },
  );
}

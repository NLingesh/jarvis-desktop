import { request } from './baseUrl';

export function getSecurityStatus(): Promise<any> {
  return request('/api/security/status');
}

export function getPrivacySettings(): Promise<any> {
  return request('/api/security/privacy');
}

export function updatePrivacySetting(key: string, value: string): Promise<any> {
  return request('/api/security/privacy', {
    method: 'POST',
    body: JSON.stringify({ key, value }),
  });
}

export function exportUserData(): Promise<any> {
  return request('/api/security/export');
}

export function deleteUserData(confirm: boolean): Promise<any> {
  return request('/api/security/data', {
    method: 'DELETE',
    body: JSON.stringify({ confirm }),
  });
}

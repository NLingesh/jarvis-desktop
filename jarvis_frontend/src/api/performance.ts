import { request } from './baseUrl';

export function getMetrics(): Promise<any> {
  return request('/api/performance/metrics');
}

export function getHealth(): Promise<any> {
  return request('/api/performance/health');
}

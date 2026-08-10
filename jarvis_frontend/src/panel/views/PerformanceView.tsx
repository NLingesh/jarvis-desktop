import React, { useState, useCallback, useEffect } from 'react';
import './PerformanceView.css';
import { getMetrics, getHealth } from '../../api/performance';

type Tab = 'metrics' | 'health';

const PerformanceView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('metrics');
  const [metrics, setMetrics] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMetrics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getMetrics();
      setMetrics(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load metrics');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHealth();
      setHealth(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'metrics') {
      loadMetrics();
    } else {
      loadHealth();
    }
  }, [tab, loadMetrics, loadHealth]);

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h}h ${m}m ${s}s`;
  };

  return (
    <div className="performance-view">
      <div className="performance-tabs">
        <button
          className={`performance-tab ${tab === 'metrics' ? 'active' : ''}`}
          onClick={() => setTab('metrics')}
        >
          Metrics
        </button>
        <button
          className={`performance-tab ${tab === 'health' ? 'active' : ''}`}
          onClick={() => setTab('health')}
        >
          Health
        </button>
      </div>

      {error && <div className="performance-error">{error}</div>}

      {tab === 'metrics' && (
        <div className="performance-metrics">
          {loading ? (
            <div className="performance-loading">Loading metrics...</div>
          ) : metrics ? (
            <div className="metrics-grid">
              <div className="metric-card">
                <span className="metric-value">{formatUptime(metrics.uptime_seconds || 0)}</span>
                <span className="metric-label">Uptime</span>
              </div>
              <div className="metric-card">
                <span className="metric-value">{metrics.requests_per_minute || 0}</span>
                <span className="metric-label">Requests/min</span>
              </div>
              <div className="metric-card">
                <span className="metric-value">{Math.round(metrics.avg_latency_ms || 0)}ms</span>
                <span className="metric-label">Avg Latency</span>
              </div>
              <div className="metric-card">
                <span className="metric-value">
                  {Object.keys(metrics.error_counts || {}).length}
                </span>
                <span className="metric-label">Error Endpoints</span>
              </div>
            </div>
          ) : (
            <div className="performance-empty">No metrics available.</div>
          )}
        </div>
      )}

      {tab === 'health' && (
        <div className="performance-health">
          {loading ? (
            <div className="performance-loading">Loading health...</div>
          ) : health ? (
            <div className="health-grid">
              <div className="health-item">
                <span className="health-label">Status</span>
                <span className={`health-value ${health.status}`}>{health.status}</span>
              </div>
              {Object.entries(health.checks || {}).map(([key, value]) => (
                <div key={key} className="health-item">
                  <span className="health-label">{key.replace(/_/g, ' ')}</span>
                  <span className="health-value">{String(value)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="performance-empty">No health data available.</div>
          )}
        </div>
      )}
    </div>
  );
};

export default PerformanceView;

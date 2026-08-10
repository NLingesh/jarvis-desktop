import React, { useState, useCallback, useEffect } from 'react';
import './SecurityView.css';
import {
  getSecurityStatus,
  getPrivacySettings,
  updatePrivacySetting,
  exportUserData,
  deleteUserData,
} from '../../api/security';

type Tab = 'status' | 'privacy' | 'data';

const SecurityView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('status');
  const [status, setStatus] = useState<any>(null);
  const [privacy, setPrivacy] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSecurityStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load security status');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPrivacy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getPrivacySettings();
      setPrivacy(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load privacy settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'status') {
      loadStatus();
    } else if (tab === 'privacy') {
      loadPrivacy();
    } else {
      setLoading(false);
    }
  }, [tab, loadStatus, loadPrivacy]);

  const handlePrivacyChange = useCallback(
    async (key: string, value: string) => {
      try {
        await updatePrivacySetting(key, value);
        await loadPrivacy();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update setting');
      }
    },
    [loadPrivacy],
  );

  const handleExport = useCallback(async () => {
    try {
      const data = await exportUserData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `jarvis-data-export-${new Date().toISOString().split('T')[0]}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export data');
    }
  }, []);

  const handleDelete = useCallback(async () => {
    if (deleteConfirm !== 'DELETE') return;
    try {
      await deleteUserData(true);
      setDeleteConfirm('');
      alert('All user data has been deleted.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete data');
    }
  }, [deleteConfirm]);

  return (
    <div className="security-view">
      <div className="security-tabs">
        <button
          className={`security-tab ${tab === 'status' ? 'active' : ''}`}
          onClick={() => setTab('status')}
        >
          Status
        </button>
        <button
          className={`security-tab ${tab === 'privacy' ? 'active' : ''}`}
          onClick={() => setTab('privacy')}
        >
          Privacy
        </button>
        <button
          className={`security-tab ${tab === 'data' ? 'active' : ''}`}
          onClick={() => setTab('data')}
        >
          Data
        </button>
      </div>

      {error && <div className="security-error">{error}</div>}

      {tab === 'status' && (
        <div className="security-status">
          {loading ? (
            <div className="security-loading">Loading security status...</div>
          ) : status ? (
            <div className="status-grid">
              <div className="status-item">
                <span className="status-label">Encryption</span>
                <span
                  className={`status-value ${status.encryption_enabled ? 'enabled' : 'disabled'}`}
                >
                  {status.encryption_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Authentication</span>
                <span className={`status-value ${status.auth_enabled ? 'enabled' : 'disabled'}`}>
                  {status.auth_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Audit Logging</span>
                <span className="status-value enabled">
                  {status.audit_logging ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Permissions</span>
                <span className="status-value enabled">
                  {status.permission_system ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Audit Entries</span>
                <span className="status-value">{status.recent_audit_entries ?? 0}</span>
              </div>
            </div>
          ) : (
            <div className="security-empty">No status available.</div>
          )}
        </div>
      )}

      {tab === 'privacy' && (
        <div className="security-privacy">
          {loading ? (
            <div className="security-loading">Loading privacy settings...</div>
          ) : privacy ? (
            <div className="privacy-list">
              {Object.entries(privacy).map(([key, value]) => (
                <div key={key} className="privacy-item">
                  <span className="privacy-label">{key.replace(/_/g, ' ')}</span>
                  <select
                    value={String(value)}
                    onChange={(e) => handlePrivacyChange(key, e.target.value)}
                    className="privacy-select"
                  >
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </div>
              ))}
            </div>
          ) : (
            <div className="security-empty">No privacy settings available.</div>
          )}
        </div>
      )}

      {tab === 'data' && (
        <div className="security-data">
          <div className="data-actions">
            <button className="security-btn" onClick={handleExport}>
              Export My Data
            </button>
          </div>

          <div className="data-danger">
            <h4>Danger Zone</h4>
            <p className="data-hint">
              This will permanently delete all your data. This action cannot be undone.
            </p>
            <input
              type="text"
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              placeholder='Type "DELETE" to confirm'
              className="delete-input"
            />
            <button
              className="security-btn danger"
              onClick={handleDelete}
              disabled={deleteConfirm !== 'DELETE'}
            >
              Delete All Data
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default SecurityView;

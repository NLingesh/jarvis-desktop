import React, { useState, useCallback, useEffect } from 'react';
import './PluginsView.css';
import {
  listPlugins,
  enablePlugin,
  disablePlugin,
  getPluginPermissions,
  grantPermission,
  revokePermission,
} from '../../api/plugins';
import { getAuditLog } from '../../api/tools';

export interface Plugin {
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  permissions: string[];
  tools: string[];
  intents: string[];
}

const PluginsView: React.FC = () => {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null);
  const [pluginPermissions, setPluginPermissions] = useState<string[]>([]);
  const [grants, setGrants] = useState<Record<string, boolean>>({});
  const [auditLog, setAuditLog] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'permissions' | 'audit'>('permissions');

  const loadPlugins = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listPlugins();
      setPlugins(data.plugins || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plugins');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlugins();
  }, [loadPlugins]);

  const handleToggle = useCallback(
    async (plugin: Plugin) => {
      try {
        if (plugin.enabled) {
          await disablePlugin(plugin.name);
        } else {
          await enablePlugin(plugin.name);
        }
        setPlugins((prev) =>
          prev.map((p) => (p.name === plugin.name ? { ...p, enabled: !p.enabled } : p)),
        );
        if (selectedPlugin?.name === plugin.name) {
          setSelectedPlugin((prev) => (prev ? { ...prev, enabled: !prev.enabled } : prev));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to toggle plugin');
      }
    },
    [selectedPlugin],
  );

  const handleSelectPlugin = useCallback(async (plugin: Plugin) => {
    setSelectedPlugin(plugin);
    setActiveTab('permissions');
    try {
      const perms = await getPluginPermissions(plugin.name);
      setPluginPermissions(perms.permissions || []);
      const grantMap: Record<string, boolean> = {};
      for (const g of perms.grants || []) {
        grantMap[g.name] = g.granted;
      }
      setGrants(grantMap);
    } catch {
      setPluginPermissions([]);
      setGrants({});
    }
  }, []);

  const handleGrant = useCallback(
    async (permission: string) => {
      if (!selectedPlugin) return;
      try {
        await grantPermission(selectedPlugin.name, permission);
        setGrants((prev) => ({ ...prev, [permission]: true }));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to grant permission');
      }
    },
    [selectedPlugin],
  );

  const handleRevoke = useCallback(
    async (permission: string) => {
      if (!selectedPlugin) return;
      try {
        await revokePermission(selectedPlugin.name, permission);
        setGrants((prev) => ({ ...prev, [permission]: false }));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to revoke permission');
      }
    },
    [selectedPlugin],
  );

  const loadAuditLog = useCallback(async () => {
    try {
      const data = await getAuditLog();
      setAuditLog(data.audit || []);
    } catch {
      setAuditLog([]);
    }
  }, []);

  useEffect(() => {
    if (selectedPlugin && activeTab === 'audit') {
      loadAuditLog();
    }
  }, [selectedPlugin, activeTab, loadAuditLog]);

  return (
    <div className="plugins-view">
      <div className="plugins-layout">
        <div className="plugins-list">
          <div className="plugins-list-header">
            <h3>Plugins</h3>
            <button
              className="plugins-refresh-btn"
              onClick={loadPlugins}
              aria-label="Refresh plugins"
            >
              Refresh
            </button>
          </div>
          {error && <div className="plugins-error">{error}</div>}
          {loading ? (
            <div className="plugins-loading">Loading plugins...</div>
          ) : plugins.length === 0 ? (
            <div className="plugins-empty">No plugins installed.</div>
          ) : (
            <div className="plugins-items">
              {plugins.map((plugin) => (
                <button
                  key={plugin.name}
                  className={`plugin-item ${selectedPlugin?.name === plugin.name ? 'selected' : ''} ${plugin.enabled ? 'enabled' : 'disabled'}`}
                  onClick={() => handleSelectPlugin(plugin)}
                >
                  <div className="plugin-item-header">
                    <span className="plugin-item-name">{plugin.name}</span>
                    <span
                      className={`plugin-status-badge ${plugin.enabled ? 'enabled' : 'disabled'}`}
                    >
                      {plugin.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </div>
                  <p className="plugin-item-desc">{plugin.description}</p>
                  <div className="plugin-item-meta">
                    <span>v{plugin.version}</span>
                    <span>{plugin.permissions.length} permissions</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="plugins-detail">
          {selectedPlugin ? (
            <>
              <div className="plugins-detail-header">
                <div>
                  <h3>{selectedPlugin.name}</h3>
                  <p className="plugins-detail-version">v{selectedPlugin.version}</p>
                </div>
                <label className="plugin-toggle">
                  <input
                    type="checkbox"
                    checked={selectedPlugin.enabled}
                    onChange={() => handleToggle(selectedPlugin)}
                    aria-label={`${selectedPlugin.enabled ? 'Disable' : 'Enable'} ${selectedPlugin.name}`}
                  />
                  <span className="toggle-slider" aria-hidden="true" />
                </label>
              </div>
              <p className="plugins-detail-desc">{selectedPlugin.description}</p>

              <div className="plugins-detail-tabs">
                <button
                  className={`plugins-tab ${activeTab === 'permissions' ? 'active' : ''}`}
                  onClick={() => setActiveTab('permissions')}
                >
                  Permissions
                </button>
                <button
                  className={`plugins-tab ${activeTab === 'audit' ? 'active' : ''}`}
                  onClick={() => setActiveTab('audit')}
                >
                  Audit Log
                </button>
              </div>

              {activeTab === 'permissions' && (
                <div className="plugins-permissions">
                  {pluginPermissions.length === 0 ? (
                    <p className="plugins-empty-text">No permissions required.</p>
                  ) : (
                    <div className="permissions-list">
                      {pluginPermissions.map((perm) => (
                        <div key={perm} className="permission-item">
                          <span className="permission-name">{perm}</span>
                          {grants[perm] ? (
                            <button
                              className="permission-btn revoke"
                              onClick={() => handleRevoke(perm)}
                            >
                              Revoke
                            </button>
                          ) : (
                            <button
                              className="permission-btn grant"
                              onClick={() => handleGrant(perm)}
                            >
                              Grant
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'audit' && (
                <div className="plugins-audit">
                  {auditLog.length === 0 ? (
                    <p className="plugins-empty-text">No audit entries.</p>
                  ) : (
                    <div className="audit-list">
                      {auditLog.slice(0, 20).map((entry, idx) => (
                        <div key={idx} className="audit-item">
                          <span className="audit-command">{entry.command}</span>
                          <span className="audit-target">{entry.target}</span>
                          <span
                            className={`audit-result ${entry.result?.startsWith('success') ? 'success' : 'error'}`}
                          >
                            {entry.result}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="plugins-detail-empty">
              <p>Select a plugin to view details and permissions.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PluginsView;

import React, { useState, useCallback, useEffect } from 'react';
import './AutomationView.css';
import {
  listWorkflows,
  createWorkflow,
  executeWorkflow,
  deleteWorkflow,
} from '../../api/automation';

export interface Workflow {
  id: string;
  name: string;
  trigger: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  enabled: boolean;
  created_at?: string;
}

const AutomationView: React.FC = () => {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [triggerJson, setTriggerJson] = useState('{"condition": "always"}');
  const [actionsJson, setActionsJson] = useState('[{"type": "notify", "message": "Hello"}]');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listWorkflows();
      setWorkflows(data.workflows || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflows');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = useCallback(async () => {
    if (!name.trim()) return;
    let trigger: Record<string, unknown> = {};
    let actions: Array<Record<string, unknown>> = [];
    try {
      trigger = JSON.parse(triggerJson || '{}');
      actions = JSON.parse(actionsJson || '[]');
    } catch {
      setError('Invalid JSON');
      return;
    }
    try {
      await createWorkflow({ name: name.trim(), trigger, actions });
      setName('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workflow');
    }
  }, [name, triggerJson, actionsJson, load]);

  const handleExecute = useCallback(async (id: string) => {
    try {
      await executeWorkflow(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to execute workflow');
    }
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteWorkflow(id);
      setWorkflows((prev) => prev.filter((w) => w.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete workflow');
    }
  }, []);

  return (
    <div className="automation-view">
      <div className="automation-create">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Workflow name"
          className="automation-input"
        />
        <textarea
          value={triggerJson}
          onChange={(e) => setTriggerJson(e.target.value)}
          placeholder='Trigger JSON, e.g. {"condition":"always"}'
          className="automation-json"
          rows={3}
        />
        <textarea
          value={actionsJson}
          onChange={(e) => setActionsJson(e.target.value)}
          placeholder='Actions JSON, e.g. [{"type":"notify","message":"Hi"}]'
          className="automation-json"
          rows={4}
        />
        <button className="automation-add-btn" onClick={handleCreate}>
          Create Workflow
        </button>
      </div>

      {error && <div className="automation-error">{error}</div>}

      {loading ? (
        <div className="automation-loading">Loading workflows...</div>
      ) : workflows.length === 0 ? (
        <div className="automation-empty">No workflows yet.</div>
      ) : (
        <div className="automation-items">
          {workflows.map((wf) => (
            <div key={wf.id} className={`workflow-item ${wf.enabled ? '' : 'disabled'}`}>
              <div className="workflow-item-main">
                <span className="workflow-name">{wf.name}</span>
                <span className={`workflow-status ${wf.enabled ? 'enabled' : 'disabled'}`}>
                  {wf.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="workflow-item-actions">
                <button className="workflow-btn execute" onClick={() => handleExecute(wf.id)}>
                  Execute
                </button>
                <button className="workflow-btn delete" onClick={() => handleDelete(wf.id)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default AutomationView;

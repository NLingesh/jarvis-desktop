import React, { useState, useCallback, useEffect } from 'react';
import './TasksView.css';
import { listTasks, createTask, completeTask, deleteTask } from '../../api/tasks';

export interface Task {
  id: string;
  title: string;
  status: string;
  priority: string;
  due_date?: string;
  project_id?: string;
  type?: string;
  cron?: string;
  next_run?: string;
  enabled?: boolean;
  payload?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

type Tab = 'tasks' | 'automation';

const TasksView: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState('task');
  const [newCron, setNewCron] = useState('');
  const [activeTab, setActiveTab] = useState<Tab>('tasks');

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTasks();
      setTasks(data.tasks || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'tasks') {
      loadTasks();
    }
  }, [activeTab, loadTasks]);

  const handleCreate = useCallback(async () => {
    if (!newTitle.trim()) return;
    try {
      await createTask({
        title: newTitle.trim(),
        type: newType,
        cron: newCron || undefined,
      });
      setNewTitle('');
      setNewCron('');
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task');
    }
  }, [newTitle, newType, newCron, loadTasks]);

  const handleComplete = useCallback(async (id: string) => {
    try {
      await completeTask(id);
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, status: 'completed' } : t)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete task');
    }
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteTask(id);
      setTasks((prev) => prev.filter((t) => t.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete task');
    }
  }, []);

  return (
    <div className="tasks-view">
      <div className="tasks-tabs">
        <button
          className={`tasks-tab ${activeTab === 'tasks' ? 'active' : ''}`}
          onClick={() => setActiveTab('tasks')}
        >
          Tasks
        </button>
        <button
          className={`tasks-tab ${activeTab === 'automation' ? 'active' : ''}`}
          onClick={() => setActiveTab('automation')}
        >
          Automation
        </button>
      </div>

      {activeTab === 'tasks' && (
        <div className="tasks-list">
          <div className="tasks-create">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="New task..."
              className="tasks-input"
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="tasks-select"
            >
              <option value="task">Task</option>
              <option value="reminder">Reminder</option>
              <option value="job">Job</option>
            </select>
            <input
              type="text"
              value={newCron}
              onChange={(e) => setNewCron(e.target.value)}
              placeholder="cron (optional)"
              className="tasks-input"
            />
            <button className="tasks-add-btn" onClick={handleCreate}>
              Add
            </button>
          </div>

          {error && <div className="tasks-error">{error}</div>}

          {loading ? (
            <div className="tasks-loading">Loading tasks...</div>
          ) : tasks.length === 0 ? (
            <div className="tasks-empty">No tasks yet.</div>
          ) : (
            <div className="tasks-items">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  className={`task-item ${task.status === 'completed' ? 'completed' : ''}`}
                >
                  <div className="task-item-main">
                    <span className="task-title">{task.title}</span>
                    <span className={`task-status ${task.status}`}>{task.status}</span>
                  </div>
                  <div className="task-item-meta">
                    <span className="task-type">{task.type}</span>
                    {task.cron && <span className="task-cron">{task.cron}</span>}
                    {task.due_date && <span className="task-due">{task.due_date}</span>}
                  </div>
                  <div className="task-item-actions">
                    {task.status !== 'completed' && (
                      <button className="task-btn complete" onClick={() => handleComplete(task.id)}>
                        Complete
                      </button>
                    )}
                    <button className="task-btn delete" onClick={() => handleDelete(task.id)}>
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'automation' && (
        <div className="automation-placeholder">
          <p>Workflow builder coming soon.</p>
        </div>
      )}
    </div>
  );
};

export default TasksView;

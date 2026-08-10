import React, { useState, useCallback, useEffect } from 'react';
import './ProactiveView.css';
import {
  getProactiveSuggestions,
  createNotification,
  sendSuggestionFeedback,
} from '../../api/proactive';

export interface Suggestion {
  id: string;
  type: string;
  text: string;
  priority: string;
  action?: string;
}

type Tab = 'suggestions' | 'notifications';

const ProactiveView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('suggestions');
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notifTitle, setNotifTitle] = useState('');
  const [notifBody, setNotifBody] = useState('');

  const loadSuggestions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getProactiveSuggestions();
      setSuggestions(data.suggestions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load suggestions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'suggestions') {
      loadSuggestions();
    }
  }, [tab, loadSuggestions]);

  const handleFeedback = useCallback(async (suggestion: Suggestion, action: string) => {
    try {
      await sendSuggestionFeedback(suggestion.id, action);
      setSuggestions((prev) => prev.filter((s) => s.id !== suggestion.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record feedback');
    }
  }, []);

  const handleCreateNotification = useCallback(async () => {
    if (!notifTitle.trim() || !notifBody.trim()) return;
    try {
      const notif = await createNotification({
        title: notifTitle.trim(),
        body: notifBody.trim(),
      });
      setNotifications((prev) => [notif, ...prev]);
      setNotifTitle('');
      setNotifBody('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create notification');
    }
  }, [notifTitle, notifBody]);

  return (
    <div className="proactive-view">
      <div className="proactive-tabs">
        <button
          className={`proactive-tab ${tab === 'suggestions' ? 'active' : ''}`}
          onClick={() => setTab('suggestions')}
        >
          Suggestions
        </button>
        <button
          className={`proactive-tab ${tab === 'notifications' ? 'active' : ''}`}
          onClick={() => setTab('notifications')}
        >
          Notifications
        </button>
      </div>

      {error && <div className="proactive-error">{error}</div>}

      {tab === 'suggestions' && (
        <div className="proactive-suggestions">
          <div className="proactive-actions">
            <button className="proactive-btn" onClick={loadSuggestions}>
              Refresh
            </button>
          </div>

          {loading ? (
            <div className="proactive-loading">Loading suggestions...</div>
          ) : suggestions.length === 0 ? (
            <div className="proactive-empty">No suggestions right now.</div>
          ) : (
            <div className="suggestions-list">
              {suggestions.map((s) => (
                <div key={s.id} className={`suggestion-item ${s.priority}`}>
                  <div className="suggestion-content">
                    <span className="suggestion-type">{s.type}</span>
                    <p className="suggestion-text">{s.text}</p>
                  </div>
                  <div className="suggestion-actions">
                    <button
                      className="suggestion-btn accept"
                      onClick={() => handleFeedback(s, 'action')}
                    >
                      Accept
                    </button>
                    <button
                      className="suggestion-btn dismiss"
                      onClick={() => handleFeedback(s, 'dismiss')}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'notifications' && (
        <div className="proactive-notifications">
          <div className="notification-create">
            <input
              type="text"
              value={notifTitle}
              onChange={(e) => setNotifTitle(e.target.value)}
              placeholder="Notification title"
              className="notification-input"
            />
            <textarea
              value={notifBody}
              onChange={(e) => setNotifBody(e.target.value)}
              placeholder="Notification body"
              className="notification-textarea"
              rows={3}
            />
            <button className="proactive-btn" onClick={handleCreateNotification}>
              Send Notification
            </button>
          </div>

          {notifications.length === 0 ? (
            <div className="proactive-empty">No notifications yet.</div>
          ) : (
            <div className="notifications-list">
              {notifications.map((n, idx) => (
                <div key={idx} className={`notification-item ${n.priority}`}>
                  <div className="notification-header">
                    <span className="notification-title">{n.title}</span>
                    <span className={`notification-priority ${n.priority}`}>{n.priority}</span>
                  </div>
                  <p className="notification-body">{n.body}</p>
                  <span className="notification-time">{n.timestamp}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ProactiveView;

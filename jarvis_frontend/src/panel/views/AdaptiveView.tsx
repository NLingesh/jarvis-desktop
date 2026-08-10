import React, { useState, useCallback, useEffect } from 'react';
import './AdaptiveView.css';
import {
  getBehaviorAnalysis,
  getInsights,
  learnFromInteraction,
  recordFeedback,
} from '../../api/adaptive';

export interface Pattern {
  id: string;
  pattern_type: string;
  trigger: string;
  action: string;
  confidence: number;
  occurrences: number;
  last_occurrence: string;
}

type Tab = 'behavior' | 'insights' | 'feedback';

const AdaptiveView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('behavior');
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [insights, setInsights] = useState<any>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBehavior = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getBehaviorAnalysis();
      setPatterns(data.frequent_commands || []);
      setSuggestions(data.suggested_actions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load behavior');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadInsights = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getInsights();
      setInsights(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load insights');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'behavior') {
      loadBehavior();
    } else if (tab === 'insights') {
      loadInsights();
    } else {
      setLoading(false);
    }
  }, [tab, loadBehavior, loadInsights]);

  const handleLearn = useCallback(async () => {
    try {
      await learnFromInteraction({
        session_id: 'demo',
        user_input: 'open browser',
        response: 'Opening browser...',
        tool_used: 'apps.open',
      });
      await loadBehavior();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to learn');
    }
  }, [loadBehavior]);

  const handleFeedback = useCallback(
    async (prediction: string, correct: boolean) => {
      try {
        await recordFeedback({
          session_id: 'demo',
          prediction,
          actual: correct ? prediction : 'different',
          correct,
        });
        await loadInsights();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to record feedback');
      }
    },
    [loadInsights],
  );

  return (
    <div className="adaptive-view">
      <div className="adaptive-tabs">
        <button
          className={`adaptive-tab ${tab === 'behavior' ? 'active' : ''}`}
          onClick={() => setTab('behavior')}
        >
          Behavior
        </button>
        <button
          className={`adaptive-tab ${tab === 'insights' ? 'active' : ''}`}
          onClick={() => setTab('insights')}
        >
          Insights
        </button>
        <button
          className={`adaptive-tab ${tab === 'feedback' ? 'active' : ''}`}
          onClick={() => setTab('feedback')}
        >
          Feedback
        </button>
      </div>

      {error && <div className="adaptive-error">{error}</div>}

      {tab === 'behavior' && (
        <div className="adaptive-behavior">
          <div className="adaptive-actions">
            <button className="adaptive-btn" onClick={handleLearn}>
              Simulate Learning
            </button>
            <button className="adaptive-btn secondary" onClick={loadBehavior}>
              Refresh
            </button>
          </div>

          {suggestions.length > 0 && (
            <div className="adaptive-suggestions">
              <h4>Suggestions</h4>
              <ul>
                {suggestions.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}

          {loading ? (
            <div className="adaptive-loading">Loading behavior...</div>
          ) : patterns.length === 0 ? (
            <div className="adaptive-empty">No patterns learned yet.</div>
          ) : (
            <div className="adaptive-patterns">
              {patterns.map((p) => (
                <div key={p.id} className="pattern-item">
                  <div className="pattern-header">
                    <span className="pattern-type">{p.pattern_type}</span>
                    <span className="pattern-confidence">{Math.round(p.confidence * 100)}%</span>
                  </div>
                  <div className="pattern-body">
                    <div className="pattern-row">
                      <span className="pattern-label">Trigger</span>
                      <span className="pattern-value">{p.trigger}</span>
                    </div>
                    <div className="pattern-row">
                      <span className="pattern-label">Action</span>
                      <span className="pattern-value">{p.action}</span>
                    </div>
                  </div>
                  <div className="pattern-footer">
                    <span>Used {p.occurrences}x</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'insights' && (
        <div className="adaptive-insights">
          {loading ? (
            <div className="adaptive-loading">Loading insights...</div>
          ) : insights ? (
            <div className="insights-grid">
              <div className="insight-card">
                <span className="insight-value">{insights.total_patterns ?? 0}</span>
                <span className="insight-label">Patterns</span>
              </div>
              <div className="insight-card">
                <span className="insight-value">
                  {Math.round((insights.feedback_accuracy ?? 0) * 100)}%
                </span>
                <span className="insight-label">Accuracy</span>
              </div>
              <div className="insight-card">
                <span className="insight-value">
                  {Object.keys(insights.pattern_types || {}).length}
                </span>
                <span className="insight-label">Types</span>
              </div>
              <div className="insight-card full">
                <span className="insight-label">Top Pattern Types</span>
                <div className="insight-types">
                  {(insights.pattern_types || {}).map(([type, count]: [string, number]) => (
                    <div key={type} className="insight-type">
                      <span>{type}</span>
                      <span className="insight-count">{String(count)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="adaptive-empty">No insights available.</div>
          )}
        </div>
      )}

      {tab === 'feedback' && (
        <div className="adaptive-feedback">
          <p className="adaptive-hint">Help JARVIS learn by rating predictions.</p>
          <div className="feedback-actions">
            <button className="adaptive-btn" onClick={() => handleFeedback('open browser', true)}>
              Correct: open browser
            </button>
            <button
              className="adaptive-btn secondary"
              onClick={() => handleFeedback('open browser', false)}
            >
              Wrong: open browser
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdaptiveView;

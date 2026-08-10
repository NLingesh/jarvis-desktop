import React, { useState, useCallback, useEffect } from 'react';
import './ModelsView.css';

export interface OllamaModel {
  name: string;
  size_bytes: number;
  size_gb: number;
  status?: string;
}

export interface ModelStatus {
  id: string;
  name: string;
  provider: string;
  status: 'ok' | 'error' | 'downloading';
  latency: number | null;
  size: string;
  downloading?: boolean;
  downloadProgress?: number;
}

const ModelsView: React.FC = () => {
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [activeModel, setActiveModel] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadName, setDownloadName] = useState('');
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<Record<string, number>>({});

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/models/ollama');
      if (!res.ok) throw new Error('Failed to load models');
      const data = await res.json();
      const ollamaModels: ModelStatus[] = (data.models || []).map((m: any) => ({
        id: m.name,
        name: m.name,
        provider: 'Ollama',
        status: 'ok' as const,
        latency: null,
        size: m.size_gb ? `${m.size_gb.toFixed(1)} GB` : '—',
        size_bytes: m.size_bytes,
      }));
      setModels(ollamaModels);
      if (ollamaModels.length > 0 && !activeModel) {
        setActiveModel(ollamaModels[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load models');
    } finally {
      setLoading(false);
    }
  }, [activeModel]);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const handleDownload = useCallback(async () => {
    const name = downloadName.trim();
    if (!name || isDownloading) return;
    setIsDownloading(true);
    setDownloadProgress((prev) => ({ ...prev, [name]: 0 }));
    try {
      const res = await fetch('/api/models/ollama/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error('Download failed');
      const text = await res.text();
      const lines = text.split('\n').filter(Boolean);
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.completed && parsed.total) {
            setDownloadProgress((prev) => ({
              ...prev,
              [name]: Math.round((parsed.completed / parsed.total) * 100),
            }));
          }
        } catch {
          // ignore non-JSON lines
        }
      }
      setDownloadProgress((prev) => ({ ...prev, [name]: 100 }));
      await loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setIsDownloading(false);
      setDownloadName('');
    }
  }, [downloadName, isDownloading, loadModels]);

  const handleDelete = useCallback(
    async (name: string) => {
      try {
        const res = await fetch(`/api/models/ollama/${encodeURIComponent(name)}`, {
          method: 'DELETE',
        });
        if (!res.ok) throw new Error('Delete failed');
        setModels((prev) => prev.filter((m) => m.id !== name));
        if (activeModel === name) {
          setActiveModel('');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed');
      }
    },
    [activeModel],
  );

  const toggleModel = useCallback((id: string) => {
    setActiveModel((prev) => (prev === id ? '' : id));
  }, []);

  return (
    <div className="models-view">
      <div className="models-header">
        <h3>Models</h3>
        <button className="models-refresh-btn" onClick={loadModels} aria-label="Refresh models">
          Refresh
        </button>
      </div>

      {error && <div className="models-error">{error}</div>}

      {loading ? (
        <div className="models-loading">Loading models...</div>
      ) : models.length === 0 ? (
        <div className="models-empty">
          <p>No models installed.</p>
          <p className="models-empty-hint">Download a model below to get started.</p>
        </div>
      ) : (
        <div className="models-list">
          {models.map((model) => (
            <div
              key={model.id}
              className={`model-row ${model.status === 'error' ? 'error' : ''} ${activeModel === model.id ? 'active' : ''}`}
            >
              <div className="model-info">
                <div className="model-header">
                  <span className="model-name">{model.name}</span>
                  <span className="model-badge" data-status={model.status}>
                    {model.status === 'ok'
                      ? 'OK'
                      : model.status === 'downloading'
                        ? 'Downloading'
                        : 'Error'}
                  </span>
                </div>
                <div className="model-meta">
                  <span>{model.provider}</span>
                  <span>{model.size}</span>
                </div>
                {downloadProgress[model.id] !== undefined && downloadProgress[model.id] < 100 && (
                  <div className="model-download-progress">
                    <div className="model-progress-bar">
                      <div
                        className="model-progress-fill"
                        style={{ width: `${downloadProgress[model.id]}%` }}
                      />
                    </div>
                    <span className="model-progress-text">{downloadProgress[model.id]}%</span>
                  </div>
                )}
              </div>
              <div className="model-actions">
                <button
                  className={`model-switch-btn ${activeModel === model.id ? 'active' : ''}`}
                  onClick={() => toggleModel(model.id)}
                  aria-pressed={activeModel === model.id}
                >
                  {activeModel === model.id ? 'Active' : 'Switch'}
                </button>
                <button
                  className="model-remove-btn"
                  aria-label="Remove model"
                  title="Remove"
                  onClick={() => handleDelete(model.id)}
                >
                  &times;
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="models-footer">
        <div className="models-download-bar">
          <input
            type="text"
            value={downloadName}
            onChange={(e) => setDownloadName(e.target.value)}
            placeholder="Model name (e.g. llama3.1)"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleDownload();
            }}
            disabled={isDownloading}
          />
          <button
            className="model-download-btn"
            onClick={handleDownload}
            disabled={!downloadName.trim() || isDownloading}
          >
            {isDownloading ? 'Downloading...' : 'Download'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ModelsView;

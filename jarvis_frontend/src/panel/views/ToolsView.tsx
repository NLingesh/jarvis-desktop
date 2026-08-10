import React, { useState, useCallback, useEffect } from 'react';
import './ToolsView.css';
import {
  createFile,
  openApp,
  executeTerminal,
  readClipboard,
  undoLast,
  getAuditLog,
  searchFiles,
} from '../../api/tools';
import { captureScreenshot, ocrImage } from '../../api/vision';

interface Tool {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  requiresConfirm: boolean;
  permission: string;
}

const TOOLS: Tool[] = [
  {
    id: 'files',
    name: 'Files',
    description: 'Browse and manage files',
    icon: '📁',
    color: '#00ff88',
    requiresConfirm: true,
    permission: 'files.write',
  },
  {
    id: 'search',
    name: 'Search',
    description: 'Search files and content',
    icon: '🔍',
    color: '#00ffff',
    requiresConfirm: false,
    permission: 'files.read',
  },
  {
    id: 'apps',
    name: 'Apps',
    description: 'Open and close applications',
    icon: '💻',
    color: '#b366ff',
    requiresConfirm: true,
    permission: 'apps.control',
  },
  {
    id: 'terminal',
    name: 'Terminal',
    description: 'Execute commands',
    icon: '⚙️',
    color: '#ffb020',
    requiresConfirm: true,
    permission: 'terminal.execute',
  },
  {
    id: 'clipboard',
    name: 'Clipboard',
    description: 'Access clipboard',
    icon: '📋',
    color: '#5b8cff',
    requiresConfirm: true,
    permission: 'clipboard.access',
  },
  {
    id: 'screenshot',
    name: 'Screenshot',
    description: 'Capture screen',
    icon: '📷',
    color: '#ff66aa',
    requiresConfirm: true,
    permission: 'screen.capture',
  },
  {
    id: 'ocr',
    name: 'OCR',
    description: 'Extract text from image',
    icon: '📄',
    color: '#ff8833',
    requiresConfirm: true,
    permission: 'vision.ocr',
  },
  {
    id: 'undo',
    name: 'Undo',
    description: 'Undo last action',
    icon: '↩️',
    color: '#ff8833',
    requiresConfirm: false,
    permission: 'system.undo',
  },
  {
    id: 'audit',
    name: 'Audit Log',
    description: 'View recent actions',
    icon: '📜',
    color: '#cccccc',
    requiresConfirm: false,
    permission: 'audit.read',
  },
];

const ToolsView: React.FC = () => {
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [toolState, setToolState] = useState<'idle' | 'confirm' | 'running' | 'done'>('idle');
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [auditLog, setAuditLog] = useState<any[]>([]);
  const [_loadingAudit, setLoadingAudit] = useState(false);

  const loadAudit = useCallback(async () => {
    setLoadingAudit(true);
    try {
      const data = await getAuditLog();
      setAuditLog(data.audit || []);
    } catch {
      setAuditLog([]);
    } finally {
      setLoadingAudit(false);
    }
  }, []);

  useEffect(() => {
    if (activeTool === 'audit') {
      loadAudit();
    }
  }, [activeTool, loadAudit]);

  const handleToolClick = useCallback((id: string) => {
    setActiveTool(id);
    setToolState('confirm');
    setResult(null);
    setError(null);
  }, []);

  const confirmTool = useCallback(async () => {
    if (!activeTool) return;
    setToolState('running');
    setError(null);
    setResult(null);

    try {
      let data: any;
      switch (activeTool) {
        case 'files':
          data = await createFile('~/Documents/test.txt', 'Hello from JARVIS');
          break;
        case 'search':
          data = await searchFiles('test');
          break;
        case 'apps':
          data = await openApp('firefox', true);
          break;
        case 'terminal':
          data = await executeTerminal('echo "Hello from JARVIS"', true);
          break;
        case 'clipboard':
          data = await readClipboard();
          break;
        case 'screenshot':
          data = await captureScreenshot(true);
          break;
        case 'ocr':
          data = await ocrImage('');
          break;
        case 'undo':
          data = await undoLast();
          break;
        case 'audit':
          data = { loaded: true };
          break;
        default:
          data = { success: true };
      }
      setResult(JSON.stringify(data, null, 2));
      setToolState('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setToolState('done');
    }
  }, [activeTool]);

  const resetTool = useCallback(() => {
    setToolState('idle');
    setActiveTool(null);
    setResult(null);
    setError(null);
  }, []);

  const activeToolData = TOOLS.find((t) => t.id === activeTool);

  return (
    <div className="tools-view">
      {!activeTool ? (
        <div className="tools-grid">
          {TOOLS.map((tool) => (
            <button
              key={tool.id}
              className="tool-card"
              onClick={() => handleToolClick(tool.id)}
              aria-label={`Open ${tool.name}`}
              title={tool.description}
            >
              <span className="tool-icon" style={{ color: tool.color }} aria-hidden="true">
                {tool.icon}
              </span>
              <span className="tool-name">{tool.name}</span>
              <span className="tool-desc">{tool.description}</span>
              {tool.requiresConfirm && <span className="tool-confirm-badge">Confirm</span>}
            </button>
          ))}
        </div>
      ) : (
        <div className="tool-flow">
          <div className="tool-flow-header">
            <span className="tool-flow-icon" aria-hidden="true">
              {activeToolData?.icon}
            </span>
            <h3 className="tool-flow-title">{activeToolData?.name}</h3>
            <span className="tool-flow-permission">{activeToolData?.permission}</span>
          </div>

          {toolState === 'confirm' && (
            <div className="tool-confirm">
              <div className="tool-confirm-card">
                <h4>Confirmation Required</h4>
                <p>This action requires confirmation because it may modify your system.</p>
                <div className="tool-confirm-details">
                  <div className="tool-confirm-detail">
                    <span className="tool-confirm-label">Tool:</span>
                    <span className="tool-confirm-value">{activeToolData?.name}</span>
                  </div>
                  <div className="tool-confirm-detail">
                    <span className="tool-confirm-label">Permission:</span>
                    <span className="tool-confirm-value">{activeToolData?.permission}</span>
                  </div>
                  <div className="tool-confirm-detail">
                    <span className="tool-confirm-label">Risk:</span>
                    <span className="tool-confirm-value">
                      {activeToolData?.requiresConfirm ? 'Medium' : 'Low'}
                    </span>
                  </div>
                </div>
                <div className="tool-confirm-actions">
                  <button className="tool-btn tool-btn-secondary" onClick={resetTool}>
                    Cancel
                  </button>
                  <button className="tool-btn tool-btn-primary" onClick={confirmTool}>
                    Confirm & Run
                  </button>
                </div>
              </div>
            </div>
          )}

          {toolState === 'running' && (
            <div className="tool-running">
              <div className="tool-spinner" aria-hidden="true" />
              <p>Running {activeToolData?.name}...</p>
            </div>
          )}

          {toolState === 'done' && (
            <div className="tool-result">
              {error ? (
                <div className="tool-error">
                  <div className="tool-result-icon" aria-hidden="true">
                    ✗
                  </div>
                  <p className="tool-result-text error">{error}</p>
                </div>
              ) : (
                <div className="tool-success">
                  <div className="tool-result-icon" aria-hidden="true">
                    ✓
                  </div>
                  <p className="tool-result-text">Action completed successfully.</p>
                </div>
              )}
              {result && activeTool === 'screenshot' && (
                <div className="tool-screenshot-preview">
                  <img
                    src={`data:image/png;base64,${JSON.parse(result).image_base64}`}
                    alt="Screenshot"
                  />
                </div>
              )}
              {result && activeTool === 'ocr' && (
                <div className="tool-ocr-result">
                  <pre>{JSON.parse(result).text || 'No text found.'}</pre>
                </div>
              )}
              {result && activeTool !== 'screenshot' && activeTool !== 'ocr' && (
                <pre className="tool-result-json">{result}</pre>
              )}
              {activeTool === 'audit' && auditLog.length > 0 && (
                <div className="tool-audit-log">
                  <h4>Recent Actions</h4>
                  <div className="audit-entries">
                    {auditLog.slice(0, 10).map((entry, idx) => (
                      <div key={idx} className="audit-entry">
                        <span className="audit-command">{entry.command}</span>
                        <span className="audit-target">{entry.target}</span>
                        <span className="audit-result">{entry.result}</span>
                        <span className="audit-time">
                          {entry.timestamp ? new Date(entry.timestamp).toLocaleString() : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="tool-result-actions">
                <button className="tool-btn tool-btn-secondary" onClick={resetTool}>
                  Back
                </button>
                <button
                  className="tool-btn tool-btn-undo"
                  onClick={async () => {
                    try {
                      const data = await undoLast();
                      setResult(JSON.stringify(data, null, 2));
                      setError(null);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : 'Undo failed');
                    }
                  }}
                >
                  Undo Last
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ToolsView;

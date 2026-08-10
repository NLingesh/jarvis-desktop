import React, { useState, useCallback, useEffect, useRef } from 'react';
import './Panel.css';
import {
  ChatView,
  MemoryView,
  FilesView,
  ModelsView,
  PluginsView,
  SettingsView,
  ToolsView,
  TasksView,
  AutomationView,
  AdaptiveView,
  ProactiveView,
  SecurityView,
  PerformanceView,
  ProjectsView,
  CodeView,
} from './views';
import { usePanelChoreography } from './usePanelChoreography';
import LoadingSpinner from '../components/LoadingSpinner';

export type PanelView =
  | 'chat'
  | 'memory'
  | 'files'
  | 'models'
  | 'plugins'
  | 'settings'
  | 'tools'
  | 'tasks'
  | 'automation'
  | 'adaptive'
  | 'proactive'
  | 'security'
  | 'performance'
  | 'projects'
  | 'code';

export interface PanelProps {
  open: boolean;
  view: PanelView;
  onViewChange: (view: PanelView) => void;
  onClose: () => void;
  orbPosition: { x: number; y: number };
  onToggleTalk?: () => void;
  className?: string;
  fillWindow?: boolean;
}

const VIEWS: { id: PanelView; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'memory', label: 'Memory' },
  { id: 'files', label: 'Files' },
  { id: 'models', label: 'Models' },
  { id: 'plugins', label: 'Plugins' },
  { id: 'settings', label: 'Settings' },
  { id: 'tools', label: 'Tools' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'automation', label: 'Automation' },
  { id: 'adaptive', label: 'Adaptive' },
  { id: 'proactive', label: 'Proactive' },
  { id: 'security', label: 'Security' },
  { id: 'performance', label: 'Performance' },
  { id: 'projects', label: 'Projects' },
  { id: 'code', label: 'Code' },
];

const STORAGE_KEY = 'jarvis-panel-position';

const Panel: React.FC<PanelProps> = ({
  open,
  view,
  onViewChange,
  onClose,
  orbPosition,
  onToggleTalk,
  className,
  fillWindow = false,
}) => {
  const { state: choreography, position } = usePanelChoreography(open, orbPosition);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [dragPosition, setDragPosition] = useState<{ x: number; y: number } | null>(null);
  const [graceTimer, setGraceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const lastClickTime = useRef(0);
  const dragPositionRef = useRef<{ x: number; y: number } | null>(null);
  const isDraggingRef = useRef(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        JSON.parse(stored);
      }
    } catch {
      // ignore
    }
  }, []);

  const handleDragStart = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      if ((e.target as HTMLElement).closest('button, input, select, a, [role="button"]')) return;
      if (fillWindow) return;
      e.preventDefault();
      e.stopPropagation();
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
      const startX = clientX - (dragPosition ?? position).x;
      const startY = clientY - (dragPosition ?? position).y;
      setDragOffset({ x: startX, y: startY });
      setIsDragging(true);
      isDraggingRef.current = true;
    },
    [position, dragPosition, fillWindow],
  );

  useEffect(() => {
    if (!isDragging) return;
    const handleMove = (e: MouseEvent | TouchEvent) => {
      const clientX =
        'touches' in e ? (e as TouchEvent).touches[0].clientX : (e as MouseEvent).clientX;
      const clientY =
        'touches' in e ? (e as TouchEvent).touches[0].clientY : (e as MouseEvent).clientY;
      const next = {
        x: Math.round(clientX - dragOffset.x),
        y: Math.round(clientY - dragOffset.y),
      };
      dragPositionRef.current = next;
      setDragPosition(next);
    };
    const handleUp = () => {
      isDraggingRef.current = false;
      setIsDragging(false);
      setDragPosition(null);
      dragPositionRef.current = null;
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    window.addEventListener('touchmove', handleMove);
    window.addEventListener('touchend', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
      window.removeEventListener('touchmove', handleMove);
      window.removeEventListener('touchend', handleUp);
    };
  }, [isDragging, dragOffset]);

  const handlePanelClick = useCallback((e: React.MouseEvent) => {
    const now = Date.now();
    if (now - lastClickTime.current > 300) {
      lastClickTime.current = now;
    } else {
      return;
    }
    const target = e.target as HTMLElement;
    if (target.closest('.panel-header') && !target.closest('button')) return;
  }, []);

  useEffect(() => {
    setIsTransitioning(true);
    const timer = setTimeout(() => setIsTransitioning(false), 180);
    return () => clearTimeout(timer);
  }, [view]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (graceTimer) clearTimeout(graceTimer);
      const timer = setTimeout(() => {
        if (!panelRef.current?.contains(e.target as Node)) {
          onClose();
        }
      }, 300);
      setGraceTimer(timer);
    },
    [graceTimer, onClose],
  );

  useEffect(() => {
    return () => {
      if (graceTimer) clearTimeout(graceTimer);
    };
  }, [graceTimer]);

  if (!choreography.isOpen) return null;

  return (
    <div
      className={`panel-overlay ${open ? 'open' : ''} ${choreography.phase}`}
      onMouseDown={handleMouseDown}
      aria-hidden={!open}
    >
      <div
        ref={panelRef}
        className={`panel ${className || ''} ${isDragging ? 'dragging' : ''} ${fillWindow ? 'panel-fill' : ''}`}
        style={{
          left: fillWindow ? 0 : (dragPosition ?? position).x,
          top: fillWindow ? 0 : (dragPosition ?? position).y,
          width: fillWindow ? '100%' : 'var(--panel-width)',
          maxWidth: fillWindow ? 'none' : 'var(--panel-max-width)',
          maxHeight: fillWindow ? 'none' : 'var(--panel-max-height)',
          transform: choreography.phase === 'collapsing' ? 'scale(0.95)' : 'scale(1)',
          opacity: choreography.phase === 'collapsing' ? 0 : 1,
          transition: `all ${choreography.phase === 'expanding' ? '220ms' : '180ms'} cubic-bezier(0.16, 1, 0.3, 1)`,
        }}
        role="dialog"
        aria-label="JARVIS panel"
        onClick={handlePanelClick}
      >
        <div
          className="panel-header"
          onMouseDown={handleDragStart}
          onTouchStart={handleDragStart}
          role="banner"
        >
          <div className="panel-header-left">
            <div className="panel-mini-orb" aria-hidden="true">
              <span className="mini-orb-inner" />
            </div>
            <select className="panel-model-picker" aria-label="Select model" defaultValue="jarvis">
              <option value="jarvis">JARVIS</option>
              <option value="llama">Llama 3</option>
              <option value="mistral">Mistral</option>
            </select>
          </div>
          <div className="panel-header-actions">
            <button
              className="panel-ptt-btn"
              onClick={onToggleTalk}
              aria-label="Push to talk"
              title="Hold to talk"
            >
              Talk
            </button>
            <button
              className="panel-close-btn"
              onClick={onClose}
              aria-label="Close panel"
              title="Close"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M3 3L11 11M11 3L3 11"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </div>

        <div className="panel-view-switcher" role="tablist" aria-label="Panel views">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              role="tab"
              aria-selected={view === v.id}
              className={`panel-view-tab ${view === v.id ? 'active' : ''}`}
              onClick={() => onViewChange(v.id)}
              tabIndex={view === v.id ? 0 : -1}
            >
              {v.label}
            </button>
          ))}
        </div>

        <div className="panel-content" role="tabpanel">
          {isTransitioning ? (
            <LoadingSpinner size="sm" label="Loading..." />
          ) : (
            <>
              {view === 'chat' && <ChatView />}
              {view === 'memory' && <MemoryView />}
              {view === 'files' && <FilesView />}
              {view === 'models' && <ModelsView />}
              {view === 'plugins' && <PluginsView />}
              {view === 'settings' && <SettingsView />}
              {view === 'tools' && <ToolsView />}
              {view === 'tasks' && <TasksView />}
              {view === 'automation' && <AutomationView />}
              {view === 'adaptive' && <AdaptiveView />}
              {view === 'proactive' && <ProactiveView />}
              {view === 'security' && <SecurityView />}
              {view === 'performance' && <PerformanceView />}
              {view === 'projects' && <ProjectsView />}
              {view === 'code' && <CodeView />}
            </>
          )}
        </div>

        <div className="panel-footer">
          <form
            className="panel-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              const input = e.currentTarget.querySelector('input') as HTMLInputElement;
              const text = input?.value.trim();
              if (text) {
                input.value = '';
                onToggleTalk?.();
              }
            }}
          >
            <button
              type="button"
              className="input-mic-btn"
              aria-label="Hold to talk"
              onMouseDown={(e) => {
                e.preventDefault();
                onToggleTalk?.();
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect
                  x="5"
                  y="2"
                  width="6"
                  height="8"
                  rx="3"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <path
                  d="M4 10a4 4 0 0 0 8 0"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
                <line
                  x1="8"
                  y1="14"
                  x2="8"
                  y2="14.01"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
            <input
              type="text"
              className="panel-text-input"
              placeholder="Type a message or hold to talk..."
              aria-label="Message input"
              autoComplete="off"
            />
            <button type="submit" className="input-send-btn" aria-label="Send message">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M2 8h12M9 4l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default Panel;

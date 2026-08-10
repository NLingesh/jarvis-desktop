import React, { useState, useCallback, useEffect } from 'react';
import './ProjectsView.css';
import {
  listProjects,
  getGitStatus,
  getGitDiff,
  getGitLog,
  createGitCommit,
  getGitBranches,
} from '../../api/developer';

export interface Project {
  id: string;
  name: string;
  path: string;
  tech_stack: string[];
  git?: {
    branch: string;
    dirty: boolean;
    status: string;
  };
  recent_files?: string[];
  analyzed_at?: string;
}

type Tab = 'projects' | 'git';

const ProjectsView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('projects');
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [gitStatus, setGitStatus] = useState<any>(null);
  const [gitDiff, setGitDiff] = useState<string>('');
  const [gitLog, setGitLog] = useState<string>('');
  const [gitBranches, setGitBranches] = useState<string[]>([]);
  const [commitMessage, setCommitMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProjects();
      setProjects(data.projects || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'projects') {
      loadProjects();
    }
  }, [tab, loadProjects]);

  const handleSelect = useCallback(async (project: Project) => {
    setSelected(project);
    setError(null);
    try {
      const [status, diff, log, branches] = await Promise.all([
        getGitStatus(project.path),
        getGitDiff(project.path),
        getGitLog(project.path),
        getGitBranches(project.path),
      ]);
      setGitStatus(status);
      setGitDiff(diff.diff || '');
      setGitLog(log.log || '');
      setGitBranches(branches.branches || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load git info');
    }
  }, []);

  const handleCommit = useCallback(async () => {
    if (!selected || !commitMessage.trim()) return;
    try {
      await createGitCommit(selected.path, commitMessage.trim());
      setCommitMessage('');
      await handleSelect(selected);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to commit');
    }
  }, [selected, commitMessage, handleSelect]);

  return (
    <div className="projects-view">
      <div className="projects-tabs">
        <button
          className={`projects-tab ${tab === 'projects' ? 'active' : ''}`}
          onClick={() => setTab('projects')}
        >
          Projects
        </button>
        <button
          className={`projects-tab ${tab === 'git' ? 'active' : ''}`}
          onClick={() => setTab('git')}
        >
          Git
        </button>
      </div>

      {error && <div className="projects-error">{error}</div>}

      {tab === 'projects' && (
        <div className="projects-list">
          {loading ? (
            <div className="projects-loading">Scanning for projects...</div>
          ) : projects.length === 0 ? (
            <div className="projects-empty">No projects found.</div>
          ) : (
            <div className="projects-items">
              {projects.map((p) => (
                <button
                  key={p.id}
                  className={`project-item ${selected?.id === p.id ? 'selected' : ''}`}
                  onClick={() => handleSelect(p)}
                >
                  <div className="project-header">
                    <span className="project-name">{p.name}</span>
                    {p.git?.dirty && <span className="project-dirty">dirty</span>}
                  </div>
                  <div className="project-tech">
                    {p.tech_stack.map((t) => (
                      <span key={t} className="tech-badge">
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="project-path">{p.path}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'git' && selected && (
        <div className="git-detail">
          <div className="git-section">
            <h4>Status</h4>
            <pre className="git-status">{JSON.stringify(gitStatus, null, 2)}</pre>
          </div>
          <div className="git-section">
            <h4>Branches</h4>
            <div className="git-branches">
              {gitBranches.map((b) => (
                <span key={b} className="branch-badge">
                  {b}
                </span>
              ))}
            </div>
          </div>
          <div className="git-section">
            <h4>Diff</h4>
            <pre className="git-diff">{gitDiff || 'No changes'}</pre>
          </div>
          <div className="git-section">
            <h4>Log</h4>
            <pre className="git-log">{gitLog || 'No commits'}</pre>
          </div>
          <div className="git-commit">
            <input
              type="text"
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="Commit message"
              className="commit-input"
            />
            <button className="commit-btn" onClick={handleCommit} disabled={!commitMessage.trim()}>
              Commit
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectsView;

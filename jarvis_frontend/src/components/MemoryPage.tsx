import React, { useEffect, useState } from 'react';
import {
  VaultNote,
  appendNote,
  archiveNote,
  createFolder,
  createNote,
  deleteNote,
  getFolders,
  getMeta,
  getTags,
  listNotes,
  moveNote,
  reindexVault,
  renameNote,
  searchNotes,
  updateNote,
} from '../api/vault';
import './MemoryPage.css';

interface MemoryPageProps {
  onClose: () => void;
}

const NOTE_TYPES = ['knowledge', 'idea', 'task', 'project', 'daily', 'conversation', 'person'];

const MemoryPage: React.FC<MemoryPageProps> = ({ onClose }) => {
  const [notes, setNotes] = useState<VaultNote[]>([]);
  const [folders, setFolders] = useState<string[]>([]);
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([]);
  const [vaultRoot, setVaultRoot] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<VaultNote | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState('knowledge');
  const [newFolder, setNewFolder] = useState('');
  const [newContent, setNewContent] = useState('');

  const load = async (query?: string) => {
    try {
      setError(null);
      if (query) {
        setNotes(await searchNotes({ q: query, limit: 50 }));
      } else {
        setNotes(await listNotes({ limit: 200 }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load notes');
    }
  };

  useEffect(() => {
    load();
    getMeta()
      .then((meta) => setVaultRoot(meta.root))
      .catch(() => {});
    getTags()
      .then(setTags)
      .catch(() => {});
    getFolders()
      .then(setFolders)
      .catch(() => {});
  }, []);

  const handleSearch = (value: string) => {
    setSearch(value);
    window.setTimeout(() => load(value.trim() || undefined), 300);
  };

  const loadFolder = async (folder: string) => {
    try {
      setNotes(await listNotes({ folder, limit: 200 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load folder');
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const note = await createNote({
        title: newTitle.trim(),
        type: newType,
        folder: newFolder.trim() || undefined,
        content: newContent,
      });
      setNewTitle('');
      setNewContent('');
      setShowNew(false);
      setSelected(note);
      load();
      getFolders()
        .then(setFolders)
        .catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create note');
    }
  };

  const toggleFavorite = async (note: VaultNote) => {
    const updated = await updateNote(note.path, { favorite: !note.favorite });
    if (selected && selected.path === note.path) setSelected(updated);
    load(search.trim() || undefined);
  };

  const handleRename = async () => {
    if (!selected) return;
    const title = window.prompt('New title', selected.title);
    if (!title || title.trim() === selected.title) return;
    const updated = await renameNote(selected.path, title.trim());
    setSelected(updated);
    load(search.trim() || undefined);
  };

  const handleMove = async () => {
    if (!selected) return;
    const folder = window.prompt(
      'Move to folder (e.g. Knowledge, Projects/Portal)',
      selected.folder,
    );
    if (folder === null) return;
    const updated = await moveNote(selected.path, folder.trim());
    setSelected(updated);
    getFolders()
      .then(setFolders)
      .catch(() => {});
    load(search.trim() || undefined);
  };

  const handleArchive = async () => {
    if (!selected) return;
    const updated = await archiveNote(selected.path);
    setSelected(null);
    if (updated) load(search.trim() || undefined);
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm(`Delete "${selected.title}" permanently?`)) return;
    await deleteNote(selected.path);
    setSelected(null);
    load(search.trim() || undefined);
  };

  const handleAppend = async () => {
    if (!selected) return;
    const text = window.prompt('Text to append (Markdown supported)');
    if (!text || !text.trim()) return;
    const updated = await appendNote(selected.path, text.trim());
    setSelected(updated);
    load(search.trim() || undefined);
  };

  const handleReindex = async () => {
    try {
      await reindexVault();
      await load(search.trim() || undefined);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reindex failed');
    }
  };

  const handleOpenVault = async () => {
    const api = (window as any).electronAPI;
    if (api?.openVault) {
      await api.openVault();
    } else if (api?.getVaultPath) {
      const vaultPath = await api.getVaultPath();
      window.alert(`Vault folder: ${vaultPath}`);
    } else {
      window.alert(`Vault folder: ${vaultRoot}`);
    }
  };

  const handleCreateFolder = async () => {
    const name = window.prompt('New folder name (e.g. Knowledge/Python)');
    if (!name || !name.trim()) return;
    try {
      await createFolder(name.trim());
      getFolders()
        .then(setFolders)
        .catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create folder');
    }
  };

  return (
    <div className="memory-overlay">
      <div className="memory-panel">
        <div className="memory-header">
          <h2>Memory Vault</h2>
          <span className="memory-root" title="Vault root folder">
            {vaultRoot}
          </span>
          <div className="memory-actions">
            <button onClick={handleOpenVault} title="Open the vault folder in your file manager">
              Open Vault
            </button>
            <button onClick={handleReindex} title="Reindex search">
              ↻ Reindex
            </button>
            <button onClick={onClose} className="close-btn">
              ✕
            </button>
          </div>
        </div>

        {error && (
          <div className="memory-error" role="alert">
            {error} <button onClick={() => setError(null)}>✕</button>
          </div>
        )}

        <div className="memory-toolbar">
          <input
            type="search"
            placeholder="Search notes…"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            aria-label="Search notes"
          />
          <button onClick={() => setShowNew(!showNew)}>{showNew ? '−' : '+'} New note</button>
        </div>

        {showNew && (
          <form className="memory-new-note" onSubmit={handleCreate}>
            <div className="memory-new-row">
              <input
                placeholder="Title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                aria-label="Note title"
              />
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                aria-label="Note type"
              >
                {NOTE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <input
                placeholder="Folder (optional)"
                list="memory-folders"
                value={newFolder}
                onChange={(e) => setNewFolder(e.target.value)}
                aria-label="Note folder"
              />
              <datalist id="memory-folders">
                {folders.map((f) => (
                  <option key={f} value={f} />
                ))}
              </datalist>
            </div>
            <textarea
              placeholder="Content (Markdown, [[wikilinks]] supported)"
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              rows={4}
              aria-label="Note content"
            />
            <button type="submit" className="primary">
              Create
            </button>
          </form>
        )}

        <div className="memory-main">
          <div className="memory-list">
            {notes.length === 0 && (
              <p className="memory-empty">No notes yet. Create your first one!</p>
            )}
            {notes.map((note) => (
              <div
                key={note.path}
                className={`memory-item ${selected?.path === note.path ? 'selected' : ''}`}
                onClick={() => setSelected(note)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') setSelected(note);
                }}
              >
                <div className="memory-item-title">
                  <span className="memory-item-name">{note.title}</span>
                  <span className={`memory-badge type-${note.type}`}>{note.type}</span>
                  <button
                    className={`favorite ${note.favorite ? 'on' : ''}`}
                    title={note.favorite ? 'Remove favorite' : 'Favorite'}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFavorite(note);
                    }}
                  >
                    {note.favorite ? '★' : '☆'}
                  </button>
                </div>
                <div className="memory-item-meta">
                  {note.folder && <span>{note.folder}</span>}
                  {note.tags.slice(0, 4).map((t) => (
                    <span className="memory-tag" key={t}>
                      #{t}
                    </span>
                  ))}
                  {note.modified && (
                    <span className="memory-date">{note.modified.slice(0, 10)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="memory-detail">
            {selected ? (
              <>
                <div className="memory-detail-header">
                  <h3>{selected.title}</h3>
                  <div className="memory-detail-actions">
                    <button onClick={handleAppend}>Append</button>
                    <button onClick={handleRename}>Rename</button>
                    <button onClick={handleMove}>Move</button>
                    <button onClick={handleArchive}>Archive</button>
                    <button onClick={handleDelete} className="danger">
                      Delete
                    </button>
                  </div>
                </div>
                <div className="memory-detail-meta">
                  {selected.links.length > 0 && (
                    <p>Links: {selected.links.map((l) => `[[${l}]]`).join(', ')}</p>
                  )}
                </div>
                <pre className="memory-body">{selected.body}</pre>
              </>
            ) : (
              <p className="memory-empty">Select a note to view it.</p>
            )}
          </div>

          <div className="memory-sidebar">
            <div className="memory-sidebar-section">
              <h4>
                Tags{' '}
                <button
                  onClick={() =>
                    getTags()
                      .then(setTags)
                      .catch(() => {})
                  }
                >
                  ↻
                </button>
              </h4>
              {tags.slice(0, 30).map((t) => (
                <button key={t.tag} className="memory-tag-btn" onClick={() => handleSearch(t.tag)}>
                  #{t.tag} ({t.count})
                </button>
              ))}
            </div>
            <div className="memory-sidebar-section">
              <h4>
                Folders <button onClick={handleCreateFolder}>+</button>
              </h4>
              {folders.map((f) => (
                <button key={f} className="memory-folder-btn" onClick={() => loadFolder(f)}>
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MemoryPage;

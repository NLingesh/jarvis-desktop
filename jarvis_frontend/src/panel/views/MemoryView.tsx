import React, { useState, useEffect, useMemo } from 'react';
import './MemoryView.css';

export interface MemoryItem {
  id: string;
  title: string;
  category: string;
  content: string;
  tags: string[];
  pinned: boolean;
  modified: string;
}

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'Projects', label: 'Projects' },
  { id: 'Notes', label: 'Notes' },
  { id: 'Conversations', label: 'Conversations' },
  { id: 'Tasks', label: 'Tasks' },
  { id: 'Preferences', label: 'Preferences' },
  { id: 'Knowledge', label: 'Knowledge' },
  { id: 'Daily Notes', label: 'Daily Notes' },
];

const MemoryView: React.FC = () => {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [recentTags, setRecentTags] = useState<string[]>([]);

  useEffect(() => {
    setLoading(true);
    setTimeout(() => {
      const mockItems: MemoryItem[] = [
        {
          id: '1',
          title: 'Project Architecture',
          category: 'Projects',
          content:
            'JARVIS uses React 18 with TypeScript, Electron for desktop, FastAPI for backend...',
          tags: ['architecture', 'design', 'react'],
          pinned: true,
          modified: '2026-08-05',
        },
        {
          id: '2',
          title: 'Meeting Notes - Sprint Planning',
          category: 'Conversations',
          content: 'Discussed Q3 roadmap priorities. Focus on voice pipeline and memory system...',
          tags: ['meeting', 'sprint', 'planning'],
          pinned: false,
          modified: '2026-08-04',
        },
        {
          id: '3',
          title: 'API Integration Guide',
          category: 'Knowledge',
          content: 'The backend exposes REST endpoints at /api/ for chat, memory, tools, vault...',
          tags: ['api', 'backend', 'integration'],
          pinned: false,
          modified: '2026-08-03',
        },
        {
          id: '4',
          title: 'Daily Note - 2026-08-05',
          category: 'Daily Notes',
          content:
            '# 2026-08-05\n\n## Tasks\n- [x] Phase 1 foundation\n- [ ] Phase 2 orb system\n\n## Notes\nGreat progress on the voice pipeline...',
          tags: ['daily', '2026-08'],
          pinned: true,
          modified: '2026-08-05',
        },
        {
          id: '5',
          title: 'Preferred Response Style',
          category: 'Preferences',
          content: 'User prefers concise responses. Use brief, direct language...',
          tags: ['preferences', 'communication'],
          pinned: false,
          modified: '2026-08-02',
        },
      ];
      setItems(mockItems);
      setLoading(false);
    }, 300);
  }, []);

  useEffect(() => {
    const tags = items.flatMap((item) => item.tags);
    const unique = Array.from(new Set(tags)).slice(0, 10);
    setRecentTags(unique);
  }, [items]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      const matchesCategory = category === 'all' || item.category === category;
      const matchesSearch =
        !search.trim() ||
        item.title.toLowerCase().includes(search.toLowerCase()) ||
        item.content.toLowerCase().includes(search.toLowerCase()) ||
        item.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()));
      const matchesTag = !activeTag || item.tags.includes(activeTag);
      return matchesCategory && matchesSearch && matchesTag;
    });
  }, [items, category, search, activeTag]);

  const pinnedItems = useMemo(() => items.filter((i) => i.pinned), [items]);

  const handleTagClick = (tag: string) => {
    setActiveTag(activeTag === tag ? null : tag);
  };

  const togglePin = (item: MemoryItem) => {
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, pinned: !i.pinned } : i)));
    if (selected?.id === item.id) {
      setSelected((prev) => (prev ? { ...prev, pinned: !prev.pinned } : null));
    }
  };

  return (
    <div className="memory-view">
      <div className="memory-search-bar">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search memory..."
          aria-label="Search memory"
        />
      </div>

      <div className="memory-categories" role="tablist" aria-label="Memory categories">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            role="tab"
            aria-selected={category === cat.id}
            className={`memory-cat-btn ${category === cat.id ? 'active' : ''}`}
            onClick={() => setCategory(cat.id)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {recentTags.length > 0 && (
        <div className="memory-tags-bar" aria-label="Filter by tags">
          {recentTags.map((tag) => (
            <button
              key={tag}
              className={`memory-tag-chip ${activeTag === tag ? 'active' : ''}`}
              onClick={() => handleTagClick(tag)}
            >
              {tag}
            </button>
          ))}
          {activeTag && (
            <button className="memory-tag-clear" onClick={() => setActiveTag(null)}>
              Clear filter
            </button>
          )}
        </div>
      )}

      <div className="memory-panes">
        <div className="memory-list-pane">
          {pinnedItems.length > 0 && category === 'all' && !activeTag && (
            <div className="memory-section">
              <h4 className="memory-section-title">Pinned</h4>
              {pinnedItems.map((item) => (
                <button
                  key={item.id}
                  className={`memory-item-btn ${selected?.id === item.id ? 'selected' : ''}`}
                  onClick={() => setSelected(item)}
                >
                  <span className="memory-item-pin" aria-hidden="true">
                    ★
                  </span>
                  <span className="memory-item-title-text">{item.title}</span>
                  <span className="memory-item-meta">{item.modified}</span>
                </button>
              ))}
            </div>
          )}

          <div className="memory-section">
            <h4 className="memory-section-title">
              {category === 'all' ? 'All Items' : category} ({filtered.length})
            </h4>
            {loading ? (
              <div className="memory-loading">Loading...</div>
            ) : filtered.length === 0 ? (
              <div className="memory-empty-state">
                <p>No items found.</p>
                {activeTag && (
                  <button className="memory-clear-filter" onClick={() => setActiveTag(null)}>
                    Clear tag filter
                  </button>
                )}
              </div>
            ) : (
              filtered.map((item) => (
                <button
                  key={item.id}
                  className={`memory-item-btn ${selected?.id === item.id ? 'selected' : ''}`}
                  onClick={() => setSelected(item)}
                >
                  <span className="memory-item-title-text">{item.title}</span>
                  <span className="memory-item-tags">
                    {item.tags.slice(0, 2).map((t) => (
                      <span key={t} className="memory-tag">
                        {t}
                      </span>
                    ))}
                  </span>
                  <span className="memory-item-meta">{item.modified}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="memory-detail-pane">
          {selected ? (
            <div className="memory-detail">
              <div className="memory-detail-header">
                <h3 className="memory-detail-title">{selected.title}</h3>
                <button
                  className="memory-pin-btn"
                  aria-label={selected.pinned ? 'Unpin' : 'Pin'}
                  onClick={() => togglePin(selected)}
                >
                  {selected.pinned ? '★' : '☆'}
                </button>
              </div>
              <div className="memory-detail-meta">
                <span className="memory-detail-category">{selected.category}</span>
                <span className="memory-detail-date">{selected.modified}</span>
              </div>
              <div className="memory-detail-tags">
                {selected.tags.map((t) => (
                  <button
                    key={t}
                    className={`memory-tag ${activeTag === t ? 'active' : ''}`}
                    onClick={() => handleTagClick(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
              <div className="memory-detail-body">{selected.content}</div>
            </div>
          ) : (
            <div className="memory-detail-empty">
              <p>Select an item to view details.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MemoryView;

import React, { useState, useCallback, useEffect } from 'react';
import './CodeView.css';
import { searchCode, explainCode } from '../../api/developer';

type Tab = 'search' | 'explain';

const CodeView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('search');
  const [query, setQuery] = useState('');
  const [searchPaths, setSearchPaths] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [explainFile, setExplainFile] = useState('');
  const [explainStart, setExplainStart] = useState('');
  const [explainEnd, setExplainEnd] = useState('');
  const [explanation, setExplanation] = useState<any>(null);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const paths = searchPaths
        .split(',')
        .map((p) => p.trim())
        .filter(Boolean);
      const data = await searchCode(query.trim(), paths);
      setSearchResults(data.results || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setSearching(false);
    }
  }, [query, searchPaths]);

  const handleExplain = useCallback(async () => {
    if (!explainFile.trim()) return;
    setExplaining(true);
    setError(null);
    try {
      const data = await explainCode(
        explainFile.trim(),
        explainStart ? Number(explainStart) : undefined,
        explainEnd ? Number(explainEnd) : undefined,
      );
      setExplanation(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Explanation failed');
    } finally {
      setExplaining(false);
    }
  }, [explainFile, explainStart, explainEnd]);

  useEffect(() => {
    if (tab === 'search') {
      setExplanation(null);
    } else {
      setSearchResults([]);
    }
  }, [tab]);

  return (
    <div className="code-view">
      <div className="code-tabs">
        <button
          className={`code-tab ${tab === 'search' ? 'active' : ''}`}
          onClick={() => setTab('search')}
        >
          Search
        </button>
        <button
          className={`code-tab ${tab === 'explain' ? 'active' : ''}`}
          onClick={() => setTab('explain')}
        >
          Explain
        </button>
      </div>

      {error && <div className="code-error">{error}</div>}

      {tab === 'search' && (
        <div className="code-search">
          <div className="search-bar">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search code..."
              className="search-input"
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
            <input
              type="text"
              value={searchPaths}
              onChange={(e) => setSearchPaths(e.target.value)}
              placeholder="Paths (comma separated)"
              className="search-paths"
            />
            <button className="search-btn" onClick={handleSearch} disabled={searching}>
              {searching ? 'Searching...' : 'Search'}
            </button>
          </div>
          <div className="search-results">
            {searchResults.length === 0 ? (
              <div className="code-empty">No results yet.</div>
            ) : (
              searchResults.map((r, i) => (
                <div key={i} className="search-result">
                  <div className="result-file">
                    {r.file}:{r.line}
                  </div>
                  <pre className="result-content">{r.content}</pre>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {tab === 'explain' && (
        <div className="code-explain">
          <div className="explain-bar">
            <input
              type="text"
              value={explainFile}
              onChange={(e) => setExplainFile(e.target.value)}
              placeholder="File path"
              className="explain-input"
            />
            <input
              type="text"
              value={explainStart}
              onChange={(e) => setExplainStart(e.target.value)}
              placeholder="Start line"
              className="explain-input"
            />
            <input
              type="text"
              value={explainEnd}
              onChange={(e) => setExplainEnd(e.target.value)}
              placeholder="End line"
              className="explain-input"
            />
            <button className="explain-btn" onClick={handleExplain} disabled={explaining}>
              {explaining ? 'Explaining...' : 'Explain'}
            </button>
          </div>
          {explanation && (
            <div className="explain-result">
              <div className="explain-file">{explanation.file}</div>
              <pre className="explain-snippet">{explanation.snippet}</pre>
              <div className="explain-text">{explanation.explanation}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default CodeView;

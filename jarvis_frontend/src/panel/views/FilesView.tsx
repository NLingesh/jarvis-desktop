import React, { useState, useCallback, useRef } from 'react';
import './FilesView.css';

interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'folder';
  size?: string;
  modified?: string;
  content?: string;
  children?: FileNode[];
}

const FILES_TREE: FileNode[] = [
  {
    name: 'Documents',
    path: '/home/user/Documents',
    type: 'folder',
    children: [
      { name: 'Projects', path: '/home/user/Documents/Projects', type: 'folder', children: [] },
      {
        name: 'Notes.md',
        path: '/home/user/Documents/Notes.md',
        type: 'file',
        size: '2.4 KB',
        modified: '2026-08-05',
      },
    ],
  },
  {
    name: 'Downloads',
    path: '/home/user/Downloads',
    type: 'folder',
    children: [
      {
        name: 'report.pdf',
        path: '/home/user/Downloads/report.pdf',
        type: 'file',
        size: '1.2 MB',
        modified: '2026-08-04',
      },
    ],
  },
  {
    name: 'Desktop',
    path: '/home/user/Desktop',
    type: 'folder',
    children: [],
  },
];

const FilesView: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['/home/user/Documents']));
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const toggleFolder = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      setSelectedFile({
        name: files[0].name,
        path: files[0].name,
        type: 'file',
        size: `${(files[0].size / 1024).toFixed(1)} KB`,
        modified: new Date().toISOString().slice(0, 10),
      });
    }
  }, []);

  const renderNode = (node: FileNode, depth = 0) => {
    const isExpanded = expanded.has(node.path);
    const isSelected = selectedFile?.path === node.path;

    if (node.type === 'folder') {
      return (
        <div key={node.path} className="file-node">
          <button
            className={`file-folder-btn ${isSelected ? 'selected' : ''}`}
            style={{ paddingLeft: `${depth * 16 + 12}px` }}
            onClick={() => {
              toggleFolder(node.path);
            }}
            aria-expanded={isExpanded}
          >
            <span className="file-arrow" aria-hidden="true">
              {isExpanded ? '▼' : '▶'}
            </span>
            <span className="file-icon">&#128193;</span>
            <span className="file-name">{node.name}</span>
          </button>
          {isExpanded && node.children && (
            <div className="file-children">
              {node.children.map((child) => renderNode(child, depth + 1))}
            </div>
          )}
        </div>
      );
    }

    return (
      <div key={node.path} className="file-node">
        <button
          className={`file-file-btn ${isSelected ? 'selected' : ''}`}
          style={{ paddingLeft: `${depth * 16 + 28}px` }}
          onClick={() => setSelectedFile(node)}
        >
          <span className="file-icon">&#128196;</span>
          <span className="file-name">{node.name}</span>
        </button>
      </div>
    );
  };

  return (
    <div
      className={`files-view ${isDragOver ? 'drag-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="files-layout">
        <div className="files-tree">
          <div className="files-tree-header">
            <span>Files</span>
            <button
              className="files-add-btn"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Add file"
              title="Add file"
            >
              +
            </button>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  setSelectedFile({
                    name: file.name,
                    path: file.name,
                    type: 'file',
                    size: `${(file.size / 1024).toFixed(1)} KB`,
                    modified: new Date().toISOString().slice(0, 10),
                  });
                }
              }}
            />
          </div>
          <div className="files-tree-content">{FILES_TREE.map((node) => renderNode(node))}</div>
        </div>

        <div className="files-preview">
          {selectedFile ? (
            <div className="files-preview-content">
              <div className="files-preview-header">
                <span className="files-preview-icon">&#128196;</span>
                <h3 className="files-preview-name">{selectedFile.name}</h3>
              </div>
              <div className="files-preview-meta">
                {selectedFile.size && <span>Size: {selectedFile.size}</span>}
                {selectedFile.modified && <span>Modified: {selectedFile.modified}</span>}
                <span>Type: {selectedFile.type}</span>
              </div>
              <div className="files-preview-body">
                <p className="files-preview-placeholder">
                  Preview of {selectedFile.name} would appear here.
                </p>
                {selectedFile.content && <pre>{selectedFile.content}</pre>}
              </div>
            </div>
          ) : (
            <div className="files-preview-empty">
              <div className="files-drop-icon" aria-hidden="true">
                &#128309;
              </div>
              <p>Drop a file on the orb to start</p>
              <p className="files-preview-hint">or select a file from the tree</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default FilesView;

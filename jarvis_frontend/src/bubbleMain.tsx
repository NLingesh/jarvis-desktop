import React from 'react';
import ReactDOM from 'react-dom/client';
import BubbleApp from './bubble.tsx';
import './tokens.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BubbleApp />
  </React.StrictMode>,
);

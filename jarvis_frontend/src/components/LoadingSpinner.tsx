import React from 'react';
import './LoadingSpinner.css';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  label?: string;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ size = 'md', label = 'Loading...' }) => {
  return (
    <div className="loading-spinner" role="status" aria-label={label}>
      <div className={`loading-spinner-ring loading-spinner-${size}`} />
      <span className="loading-spinner-label">{label}</span>
    </div>
  );
};

export default LoadingSpinner;

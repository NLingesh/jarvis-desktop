import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import NotificationToast, { Toast, ToastType } from './NotificationToast';

interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: ToastType, title: string, message?: string, duration?: number) => string;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let toastId = 0;

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, title: string, message?: string, duration = 4000) => {
      const id = `toast-${++toastId}`;
      setToasts((prev) => [...prev, { id, type, title, message, duration }]);
      return id;
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ toasts, addToast, dismissToast }}>
      {children}
      <div className="toast-container" aria-label="Notifications">
        {toasts.map((toast) => (
          <NotificationToast key={toast.id} toast={toast} onDismiss={dismissToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      toasts: [],
      addToast: (_type: ToastType, title: string, message?: string, _duration?: number) => {
        console.warn('useToast used outside ToastProvider', title, message);
        return '';
      },
      dismissToast: () => {},
    };
  }
  return ctx;
}

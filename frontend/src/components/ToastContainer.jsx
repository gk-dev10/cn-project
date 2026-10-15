import React from 'react';

export default function ToastContainer({ toasts = [] }) {
  if (toasts.length === 0) return null;

  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast">
          <span>{toast.type === 'error' ? '🚨' : '⚡'}</span>
          <span>{toast.message}</span>
        </div>
      ))}
    </div>
  );
}

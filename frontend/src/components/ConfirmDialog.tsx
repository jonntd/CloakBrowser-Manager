interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * In-app confirmation modal. Tauri's WebView does not implement
 * window.confirm (it returns falsy without showing anything), so
 * destructive actions must go through this dialog instead.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={loading ? undefined : onCancel}
    >
      <div
        className="w-full max-w-sm mx-4 rounded-lg border border-border bg-surface-1 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-gray-100 mb-2">{title}</h3>
        <p className="text-sm text-gray-400 mb-5 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={onCancel}
            disabled={loading}
          >
            取消
          </button>
          <button
            type="button"
            className="btn-danger"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "处理中..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

import './ModalDialog.css';

export default function ModalDialog({
  isOpen,
  title,
  message,
  confirmLabel = 'OK',
  cancelLabel = '',
  onConfirm,
  onCancel,
  danger = false,
}) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onCancel || onConfirm}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{message}</p>
        <div className="modal-actions">
          {cancelLabel && (
            <button className="modal-btn secondary" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button
            className={`modal-btn ${danger ? 'danger' : 'primary'}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onOpenSettings,
  onRenameConversation,
  onDeleteConversation,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editingTitle, setEditingTitle] = useState('');

  const startRename = (conversation) => {
    setEditingId(conversation.id);
    setEditingTitle(conversation.title || 'New Conversation');
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const saveRename = async () => {
    const trimmed = editingTitle.trim();
    if (!trimmed || !editingId) return;
    await onRenameConversation(editingId, trimmed);
    cancelRename();
  };

  const handleDelete = async (conversation) => {
    await onDeleteConversation(conversation);
    if (editingId === conversation.id) {
      cancelRename();
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title-row">
          <h1>LLM Council</h1>
          <button
            className="settings-btn"
            onClick={onOpenSettings}
            title="Settings"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
              <path d="M16.167 12.5a1.375 1.375 0 0 0 .275 1.517l.05.05a1.667 1.667 0 1 1-2.359 2.358l-.05-.05a1.375 1.375 0 0 0-1.516-.275 1.375 1.375 0 0 0-.834 1.258v.142a1.667 1.667 0 1 1-3.333 0v-.075a1.375 1.375 0 0 0-.9-1.258 1.375 1.375 0 0 0-1.517.275l-.05.05a1.667 1.667 0 1 1-2.358-2.359l.05-.05a1.375 1.375 0 0 0 .275-1.516 1.375 1.375 0 0 0-1.258-.834h-.142a1.667 1.667 0 0 1 0-3.333h.075a1.375 1.375 0 0 0 1.258-.9 1.375 1.375 0 0 0-.275-1.517l-.05-.05A1.667 1.667 0 1 1 5.867 3.55l.05.05a1.375 1.375 0 0 0 1.516.275h.067a1.375 1.375 0 0 0 .833-1.258V2.5a1.667 1.667 0 0 1 3.334 0v.075a1.375 1.375 0 0 0 .833 1.258 1.375 1.375 0 0 0 1.517-.275l.05-.05a1.667 1.667 0 1 1 2.358 2.358l-.05.05a1.375 1.375 0 0 0-.275 1.517v.067a1.375 1.375 0 0 0 1.258.833h.142a1.667 1.667 0 0 1 0 3.334h-.075a1.375 1.375 0 0 0-1.258.833Z" />
            </svg>
          </button>
        </div>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => {
                if (editingId !== conv.id) onSelectConversation(conv.id);
              }}
            >
              {editingId === conv.id ? (
                <div className="conversation-edit-row" onClick={(e) => e.stopPropagation()}>
                  <input
                    className="conversation-title-input"
                    value={editingTitle}
                    onChange={(e) => setEditingTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveRename();
                      if (e.key === 'Escape') cancelRename();
                    }}
                    autoFocus
                  />
                  <button className="conversation-action-btn save" onClick={saveRename}>
                    Save
                  </button>
                  <button className="conversation-action-btn" onClick={cancelRename}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="conversation-title-row">
                  <div className="conversation-title">
                    {conv.title || 'New Conversation'}
                  </div>
                  <div className="conversation-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="conversation-icon-btn"
                      title="Rename"
                      aria-label="Rename"
                      onClick={() => startRename(conv)}
                    >
                      <svg
                        width="13"
                        height="13"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M12 20h9" />
                        <path d="m16.5 3.5 4 4L8 20l-5 1 1-5 12.5-12.5z" />
                      </svg>
                    </button>
                    <button
                      className="conversation-icon-btn delete"
                      title="Delete"
                      aria-label="Delete"
                      onClick={() => handleDelete(conv)}
                    >
                      <svg
                        width="13"
                        height="13"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M3 6h18" />
                        <path d="M8 6V4h8v2" />
                        <path d="M19 6l-1 14H6L5 6" />
                        <path d="M10 11v6" />
                        <path d="M14 11v6" />
                      </svg>
                    </button>
                  </div>
                </div>
              )}
              <div className="conversation-meta">
                {conv.message_count} messages
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

import { useState, useEffect, useMemo, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './ChatInterface.css';

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
  disabled,
  availableModels,
  councilModels,
  chairmanModel,
  onAddCouncilModel,
  onRemoveCouncilModel,
  onChangeChairmanModel,
  usdInrRate,
}) {
  const [input, setInput] = useState('');
  const [showModelSettings, setShowModelSettings] = useState(false);
  const messagesEndRef = useRef(null);

  const modelsById = useMemo(
    () => new Map((availableModels || []).map((model) => [model.id, model])),
    [availableModels]
  );

  const addableModels = useMemo(() => {
    const selected = new Set(councilModels || []);
    return (availableModels || []).filter((model) => !selected.has(model.id));
  }, [availableModels, councilModels]);

  const estimatedInputTokens = useMemo(() => {
    const trimmed = input.trim();
    if (!trimmed) return 0;
    return Math.max(1, Math.ceil(trimmed.length / 4));
  }, [input]);

  const estimatedStage1Usd = useMemo(() => {
    if (!estimatedInputTokens || !(councilModels || []).length) return 0;
    return (councilModels || []).reduce((sum, modelId) => {
      const model = modelsById.get(modelId);
      const promptPrice = model?.prompt_cost_per_token || 0;
      return sum + (promptPrice * estimatedInputTokens);
    }, 0);
  }, [estimatedInputTokens, councilModels, modelsById]);

  const estimatedStage1Inr = estimatedStage1Usd * (usdInrRate || 0);
  const hasPricingData = useMemo(() => (
    (councilModels || []).some((modelId) => {
      const model = modelsById.get(modelId);
      return (model?.prompt_cost_per_token || 0) > 0;
    })
  ), [councilModels, modelsById]);
  const inrCostLabel = useMemo(() => {
    if (estimatedStage1Inr <= 0) return '₹0.00';
    if (estimatedStage1Inr < 0.01) return '< ₹0.01';
    return `₹${estimatedStage1Inr.toFixed(2)}`;
  }, [estimatedStage1Inr]);
  const usdCostLabel = useMemo(() => {
    if (estimatedStage1Usd <= 0) return '$0.000000';
    if (estimatedStage1Usd < 0.0001) return '< $0.0001';
    return `$${estimatedStage1Usd.toFixed(6)}`;
  }, [estimatedStage1Usd]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading && !disabled) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const councilSummary = useMemo(() => {
    const count = (councilModels || []).length;
    const chairName = modelsById.get(chairmanModel)?.name || chairmanModel || 'None';
    const shortChair = chairName.split('/').pop();
    return `${count} models · Chairman: ${shortChair}`;
  }, [councilModels, chairmanModel, modelsById]);

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <svg className="empty-state-icon" width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v3" />
            <path d="M12 18v3" />
            <path d="M4 12h3" />
            <path d="M17 12h3" />
            <path d="M6.3 6.3l2.1 2.1" />
            <path d="M15.6 15.6l2.1 2.1" />
            <path d="M17.7 6.3l-2.1 2.1" />
            <path d="M8.4 15.6l-2.1 2.1" />
            <circle cx="12" cy="12" r="4" />
          </svg>
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to begin deliberation</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <svg className="empty-state-icon" width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3v3" />
              <path d="M12 18v3" />
              <path d="M4 12h3" />
              <path d="M17 12h3" />
              <path d="M6.3 6.3l2.1 2.1" />
              <path d="M15.6 15.6l2.1 2.1" />
              <path d="M17.7 6.3l-2.1 2.1" />
              <path d="M8.4 15.6l-2.1 2.1" />
              <circle cx="12" cy="12" r="4" />
            </svg>
            <h2>The Council Awaits</h2>
            <p>Pose a question and let multiple LLMs deliberate</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        {/* Collapsible model settings */}
        <div className="input-toolbar">
          <button
            type="button"
            className={`model-toggle-btn ${showModelSettings ? 'active' : ''}`}
            onClick={() => setShowModelSettings(!showModelSettings)}
            title="Configure models"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
            <span className="model-toggle-label">{councilSummary}</span>
            <svg className={`model-toggle-chevron ${showModelSettings ? 'open' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          <span className="cost-estimate">
            {hasPricingData
              ? `Est. ${inrCostLabel} (${usdCostLabel}) · ~${estimatedInputTokens} tokens · ₹${(usdInrRate || 0).toFixed(0)}/USD`
              : 'Loading model pricing…'}
          </span>
        </div>

        {showModelSettings && (
          <div className="input-model-settings">
            <div className="inline-setting-group">
              <div className="inline-setting-label">Council Models</div>
              <div className="inline-model-chips">
                {(councilModels || []).map((modelId) => (
                  <span key={modelId} className="inline-model-chip">
                    {modelsById.get(modelId)?.name || modelId}
                    <button
                      type="button"
                      className="inline-chip-remove"
                      onClick={() => onRemoveCouncilModel(modelId)}
                      disabled={(councilModels || []).length <= 2 || disabled}
                      title="Remove model"
                    >
                      &times;
                    </button>
                  </span>
                ))}
                {addableModels.length > 0 && (
                  <select
                    className="inline-model-add"
                    value=""
                    disabled={disabled}
                    onChange={(e) => onAddCouncilModel(e.target.value)}
                  >
                    <option value="">+ Add...</option>
                    {addableModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            <div className="inline-setting-group chairman-group">
              <div className="inline-setting-label">Chairman</div>
              <select
                className="inline-model-select"
                value={chairmanModel || ''}
                disabled={disabled || !(availableModels || []).length}
                onChange={(e) => onChangeChairmanModel(e.target.value)}
              >
                {chairmanModel && !modelsById.has(chairmanModel) && (
                  <option value={chairmanModel}>{chairmanModel}</option>
                )}
                {!(availableModels || []).length && (
                  <option value="">No models loaded</option>
                )}
                {(availableModels || []).map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Textarea + send button row */}
        <div className="input-row">
          <textarea
            className="message-input"
            placeholder="Ask your question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading || disabled}
            rows={2}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading || disabled}
            title="Send (Enter)"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}

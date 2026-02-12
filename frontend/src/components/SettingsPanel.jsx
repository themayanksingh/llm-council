import { useState, useMemo } from 'react';
import { configStore } from '../api';
import './SettingsPanel.css';

export default function SettingsPanel({
  isOpen,
  onClose,
  config,
  onConfigChange,
}) {
  const [apiKeyInput, setApiKeyInput] = useState(config.apiKey || '');
  const [showKey, setShowKey] = useState(false);
  const [sessionOnly, setSessionOnly] = useState(configStore.isSessionOnly());

  // Group available models by provider
  const groupedModels = useMemo(() => {
    const groups = {};
    for (const m of config.availableModels || []) {
      const provider = m.provider || 'other';
      if (!groups[provider]) groups[provider] = [];
      groups[provider].push(m);
    }
    // Sort providers alphabetically
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [config.availableModels]);

  // Models not yet in council (for the add dropdown)
  const addableModels = useMemo(() => {
    const selected = new Set(config.councilModels || []);
    return (config.availableModels || []).filter((m) => !selected.has(m.id));
  }, [config.availableModels, config.councilModels]);

  const groupedAddable = useMemo(() => {
    const groups = {};
    for (const m of addableModels) {
      const provider = m.provider || 'other';
      if (!groups[provider]) groups[provider] = [];
      groups[provider].push(m);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [addableModels]);

  if (!isOpen) return null;

  const handleSaveKey = () => {
    configStore.setApiKey(apiKeyInput);
    onConfigChange({ apiKey: apiKeyInput });
  };

  const handleSessionOnlyToggle = () => {
    const next = !sessionOnly;
    setSessionOnly(next);
    configStore.setSessionOnly(next);
  };

  const handleAddModel = (modelId) => {
    if (!modelId) return;
    const current = config.councilModels || [];
    if (current.includes(modelId)) return;
    const next = [...current, modelId];
    configStore.setCouncilModels(next);
    onConfigChange({ councilModels: next });
  };

  const handleRemoveModel = (modelId) => {
    const current = config.councilModels || [];
    const next = current.filter((id) => id !== modelId);
    if (next.length < 2) return; // enforce minimum
    configStore.setCouncilModels(next);
    onConfigChange({ councilModels: next });
  };

  const handleChairmanChange = (modelId) => {
    configStore.setChairmanModel(modelId);
    onConfigChange({ chairmanModel: modelId });
  };

  const handleResetDefaults = () => {
    configStore.clearAll();
    onConfigChange({
      apiKey: '',
      councilModels: config.defaults?.council || [],
      chairmanModel: config.defaults?.chairman || '',
    });
    setApiKeyInput('');
    setSessionOnly(false);
  };

  // Helper: display name for a model ID
  const modelName = (id) => {
    const m = (config.availableModels || []).find((m) => m.id === id);
    return m ? m.name : id.split('/').pop();
  };

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="settings-close" onClick={onClose}>
            &times;
          </button>
        </div>

        {/* API Key */}
        <section className="settings-section">
          <h3>OpenRouter API Key</h3>
          <p className="settings-warning">
            Your key is stored in this browser only and sent directly to
            OpenRouter. Never share it.
          </p>
          <div className="api-key-row">
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder="sk-or-v1-..."
              className="api-key-input"
            />
            <button
              className="btn-small"
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? 'Hide' : 'Show'}
            </button>
            <button className="btn-small btn-primary" onClick={handleSaveKey}>
              Save
            </button>
          </div>
          <label className="session-toggle">
            <input
              type="checkbox"
              checked={sessionOnly}
              onChange={handleSessionOnlyToggle}
            />
            Session only (clear key when tab closes)
          </label>
        </section>

        {/* Council Models */}
        <section className="settings-section">
          <h3>Council Models</h3>
          <p className="settings-hint">
            Select at least 2 models. They will answer your question and rank
            each other.
          </p>
          <div className="model-chips">
            {(config.councilModels || []).map((id) => (
              <span key={id} className="model-chip">
                {modelName(id)}
                <button
                  className="chip-remove"
                  onClick={() => handleRemoveModel(id)}
                  disabled={(config.councilModels || []).length <= 2}
                  title="Remove"
                >
                  &times;
                </button>
              </span>
            ))}
          </div>
          {addableModels.length > 0 && (
            <select
              className="model-add-select"
              value=""
              onChange={(e) => handleAddModel(e.target.value)}
            >
              <option value="">+ Add model...</option>
              {groupedAddable.map(([provider, models]) => (
                <optgroup key={provider} label={provider}>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
        </section>

        {/* Chairman Model */}
        <section className="settings-section">
          <h3>Chairman Model</h3>
          <p className="settings-hint">
            Synthesizes the final answer from all responses and rankings.
          </p>
          <select
            className="model-add-select"
            value={config.chairmanModel || ''}
            onChange={(e) => handleChairmanChange(e.target.value)}
          >
            {groupedModels.map(([provider, models]) => (
              <optgroup key={provider} label={provider}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </section>

        {/* Reset */}
        <section className="settings-section">
          <button className="btn-reset" onClick={handleResetDefaults}>
            Reset to Defaults
          </button>
        </section>
      </div>
    </div>
  );
}

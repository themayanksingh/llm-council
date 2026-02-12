/**
 * API client for the LLM Council backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

// --- localStorage / sessionStorage helpers ---

const STORAGE_KEYS = {
  apiKey: 'llm_council_api_key',
  councilModels: 'llm_council_models',
  chairmanModel: 'llm_council_chairman',
  sessionOnly: 'llm_council_session_only',
};

function getStore() {
  // If user opted for session-only, use sessionStorage (cleared on tab close)
  const sessionOnly = localStorage.getItem(STORAGE_KEYS.sessionOnly) === 'true';
  return sessionOnly ? sessionStorage : localStorage;
}

export const configStore = {
  getApiKey() {
    // Check sessionStorage first (session-only mode), then localStorage
    return sessionStorage.getItem(STORAGE_KEYS.apiKey)
      || localStorage.getItem(STORAGE_KEYS.apiKey)
      || '';
  },
  setApiKey(key) {
    getStore().setItem(STORAGE_KEYS.apiKey, key);
    // Clean the other store
    const other = getStore() === sessionStorage ? localStorage : sessionStorage;
    other.removeItem(STORAGE_KEYS.apiKey);
  },

  getCouncilModels() {
    const stored = localStorage.getItem(STORAGE_KEYS.councilModels);
    return stored ? JSON.parse(stored) : null;
  },
  setCouncilModels(models) {
    localStorage.setItem(STORAGE_KEYS.councilModels, JSON.stringify(models));
  },

  getChairmanModel() {
    return localStorage.getItem(STORAGE_KEYS.chairmanModel) || null;
  },
  setChairmanModel(model) {
    localStorage.setItem(STORAGE_KEYS.chairmanModel, model);
  },

  isSessionOnly() {
    return localStorage.getItem(STORAGE_KEYS.sessionOnly) === 'true';
  },
  setSessionOnly(val) {
    localStorage.setItem(STORAGE_KEYS.sessionOnly, val ? 'true' : 'false');
    // If switching to session-only, move the key to sessionStorage
    if (val) {
      const key = localStorage.getItem(STORAGE_KEYS.apiKey);
      if (key) {
        sessionStorage.setItem(STORAGE_KEYS.apiKey, key);
        localStorage.removeItem(STORAGE_KEYS.apiKey);
      }
    } else {
      const key = sessionStorage.getItem(STORAGE_KEYS.apiKey);
      if (key) {
        localStorage.setItem(STORAGE_KEYS.apiKey, key);
        sessionStorage.removeItem(STORAGE_KEYS.apiKey);
      }
    }
  },

  clearAll() {
    Object.values(STORAGE_KEYS).forEach((k) => {
      localStorage.removeItem(k);
      sessionStorage.removeItem(k);
    });
  },
};

// --- API client ---

export const api = {
  /**
   * Fetch available models from OpenRouter via backend.
   */
  async getAvailableModels(apiKey) {
    const headers = {};
    if (apiKey) headers['X-OpenRouter-Key'] = apiKey;

    const response = await fetch(`${API_BASE}/api/models`, { headers });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch models');
    }
    return response.json();
  },

  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content, config = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (config.apiKey) headers['X-OpenRouter-Key'] = config.apiKey;

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          content,
          council_models: config.councilModels || undefined,
          chairman_model: config.chairmanModel || undefined,
        }),
      }
    );
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId
   * @param {string} content
   * @param {object} config - { apiKey, councilModels, chairmanModel }
   * @param {function} onEvent - (eventType, data) => void
   */
  async sendMessageStream(conversationId, content, config, onEvent) {
    const headers = { 'Content-Type': 'application/json' };
    if (config.apiKey) headers['X-OpenRouter-Key'] = config.apiKey;

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          content,
          council_models: config.councilModels || undefined,
          chairman_model: config.chairmanModel || undefined,
        }),
      }
    );

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
  },
};

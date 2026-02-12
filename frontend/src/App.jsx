import { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import SettingsPanel from './components/SettingsPanel';
import ModalDialog from './components/ModalDialog';
import { api, configStore } from './api';
import './App.css';

const FALLBACK_DEFAULTS = {
  council: [
    'openai/gpt-5.2',
    'anthropic/claude-sonnet-4.5',
    'google/gemini-3-pro-preview',
    'x-ai/grok-4',
  ],
  chairman: 'google/gemini-3-pro-preview',
};

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hasServerApiAccess, setHasServerApiAccess] = useState(false);
  const [usdInrRate, setUsdInrRate] = useState(83.0);
  const [pendingDeleteConversation, setPendingDeleteConversation] = useState(null);
  const [errorDialog, setErrorDialog] = useState(null);

  // Config state - models will be populated from backend defaults
  // Only use localStorage if user has explicitly customized
  const [config, setConfig] = useState({
    apiKey: configStore.getApiKey(),
    councilModels: null,  // Will be set from backend defaults
    chairmanModel: null, // Will be set from backend defaults
    availableModels: [],
    defaults: { council: [], chairman: '' },
  });

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Fetch available models when API key changes (or when using server-side fallback key)
  const fetchModels = useCallback(async (apiKey) => {
    const isCustomized = configStore.isModelsCustomized();
    try {
      const data = await api.getAvailableModels(apiKey);
      setHasServerApiAccess(true);
      setConfig((prev) => ({
        ...prev,
        availableModels: data.models || [],
        defaults: data.defaults || prev.defaults,
        // Only use localStorage if user explicitly customized, otherwise use latest from backend
        councilModels: (isCustomized && prev.councilModels) 
          ? prev.councilModels 
          : data.defaults?.council || prev.defaults?.council || [],
        chairmanModel: (isCustomized && prev.chairmanModel) 
          ? prev.chairmanModel 
          : data.defaults?.chairman || prev.defaults?.chairman || '',
      }));
    } catch (err) {
      setHasServerApiAccess(false);
      setConfig((prev) => ({
        ...prev,
        defaults: prev.defaults?.council?.length ? prev.defaults : FALLBACK_DEFAULTS,
        councilModels: (isCustomized && prev.councilModels) 
          ? prev.councilModels 
          : prev.defaults?.council || FALLBACK_DEFAULTS.council,
        chairmanModel: (isCustomized && prev.chairmanModel) 
          ? prev.chairmanModel 
          : prev.defaults?.chairman || FALLBACK_DEFAULTS.chairman,
      }));
      console.error('Failed to fetch models:', err);
    }
  }, []);

  useEffect(() => {
    fetchModels(config.apiKey);
  }, [config.apiKey, fetchModels]);

  useEffect(() => {
    const fetchFxRate = async () => {
      try {
        const data = await api.getUsdInrRate();
        if (typeof data.usd_inr === 'number' && data.usd_inr > 0) {
          setUsdInrRate(data.usd_inr);
        }
      } catch (error) {
        console.error('Failed to fetch USD/INR rate:', error);
      }
    };
    fetchFxRate();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, title: newConv.title, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleRenameConversation = async (conversationId, title) => {
    try {
      const updated = await api.renameConversation(conversationId, title);
      setConversations((prev) => prev.map((conv) => (
        conv.id === conversationId ? { ...conv, title: updated.title } : conv
      )));
      if (currentConversationId === conversationId) {
        setCurrentConversation((prev) => (
          prev ? { ...prev, title: updated.title } : prev
        ));
      }
    } catch (error) {
      console.error('Failed to rename conversation:', error);
      setErrorDialog({
        title: 'Rename Failed',
        message: error.message || 'Failed to rename conversation',
      });
    }
  };

  const handleDeleteConversation = async (conversation) => {
    setPendingDeleteConversation(conversation);
  };

  const confirmDeleteConversation = async () => {
    if (!pendingDeleteConversation) return;
    const conversationId = pendingDeleteConversation.id;

    try {
      await api.deleteConversation(conversationId);
      const refreshed = await api.listConversations();
      setConversations(refreshed);

      if (currentConversationId === conversationId) {
        const nextConversationId = refreshed.length > 0 ? refreshed[0].id : null;
        setCurrentConversationId(nextConversationId);
        if (!nextConversationId) {
          setCurrentConversation(null);
        }
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      setErrorDialog({
        title: 'Delete Failed',
        message: error.message || 'Failed to delete conversation',
      });
    } finally {
      setPendingDeleteConversation(null);
    }
  };

  const handleConfigChange = (updates) => {
    if (Object.prototype.hasOwnProperty.call(updates, 'councilModels')) {
      configStore.setCouncilModels(updates.councilModels);
    }
    if (Object.prototype.hasOwnProperty.call(updates, 'chairmanModel')) {
      configStore.setChairmanModel(updates.chairmanModel);
    }
    setConfig((prev) => ({ ...prev, ...updates }));
  };

  const handleAddCouncilModel = (modelId) => {
    if (!modelId) return;
    const current = config.councilModels || [];
    if (current.includes(modelId)) return;
    const next = [...current, modelId];
    configStore.setCouncilModels(next);
    setConfig((prev) => ({ ...prev, councilModels: next }));
  };

  const handleRemoveCouncilModel = (modelId) => {
    const current = config.councilModels || [];
    const next = current.filter((id) => id !== modelId);
    if (next.length < 2) return;
    configStore.setCouncilModels(next);
    setConfig((prev) => ({ ...prev, councilModels: next }));
  };

  const handleChangeChairmanModel = (modelId) => {
    configStore.setChairmanModel(modelId);
    setConfig((prev) => ({ ...prev, chairmanModel: modelId }));
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;
    const canSend = Boolean(config.apiKey || hasServerApiAccess);

    if (!canSend) {
      setSettingsOpen(true);
      return;
    }

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming, passing config
      await api.sendMessageStream(
        currentConversationId,
        content,
        {
          apiKey: config.apiKey,
          councilModels: config.councilModels,
          chairmanModel: config.chairmanModel,
        },
        (eventType, event) => {
          switch (eventType) {
            case 'stage1_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage1 = true;
                return { ...prev, messages };
              });
              break;

            case 'stage1_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage1 = event.data;
                lastMsg.loading.stage1 = false;
                return { ...prev, messages };
              });
              break;

            case 'stage2_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage2 = true;
                return { ...prev, messages };
              });
              break;

            case 'stage2_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage2 = event.data;
                lastMsg.metadata = event.metadata;
                lastMsg.loading.stage2 = false;
                return { ...prev, messages };
              });
              break;

            case 'stage3_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage3 = true;
                return { ...prev, messages };
              });
              break;

            case 'stage3_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage3 = event.data;
                lastMsg.loading.stage3 = false;
                return { ...prev, messages };
              });
              break;

            case 'title_complete':
              loadConversations();
              break;

            case 'complete':
              loadConversations();
              setIsLoading(false);
              break;

            case 'error':
              console.error('Stream error:', event.message);
              setIsLoading(false);
              break;

            default:
              console.log('Unknown event type:', eventType);
          }
        }
      );
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onOpenSettings={() => setSettingsOpen(true)}
        onRenameConversation={handleRenameConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <div className="main-area">
        {!Boolean(config.apiKey || hasServerApiAccess) && (
          <div className="api-key-banner">
            <span>Set your OpenRouter API key to get started.</span>
            <button onClick={() => setSettingsOpen(true)}>Open Settings</button>
          </div>
        )}
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          disabled={!Boolean(config.apiKey || hasServerApiAccess)}
          availableModels={config.availableModels}
          councilModels={config.councilModels || []}
          chairmanModel={config.chairmanModel || ''}
          onAddCouncilModel={handleAddCouncilModel}
          onRemoveCouncilModel={handleRemoveCouncilModel}
          onChangeChairmanModel={handleChangeChairmanModel}
          usdInrRate={usdInrRate}
        />
      </div>
      <SettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        config={config}
        onConfigChange={handleConfigChange}
      />
      <ModalDialog
        isOpen={Boolean(pendingDeleteConversation)}
        title="Delete Conversation"
        message={`Delete "${pendingDeleteConversation?.title || 'New Conversation'}"? This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={confirmDeleteConversation}
        onCancel={() => setPendingDeleteConversation(null)}
        danger
      />
      <ModalDialog
        isOpen={Boolean(errorDialog)}
        title={errorDialog?.title || 'Error'}
        message={errorDialog?.message || 'Something went wrong.'}
        confirmLabel="OK"
        onConfirm={() => setErrorDialog(null)}
      />
    </div>
  );
}

export default App;

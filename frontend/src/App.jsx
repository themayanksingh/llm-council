import { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import SettingsPanel from './components/SettingsPanel';
import { api, configStore } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Config state (hydrated from localStorage)
  const [config, setConfig] = useState({
    apiKey: configStore.getApiKey(),
    councilModels: configStore.getCouncilModels(),
    chairmanModel: configStore.getChairmanModel(),
    availableModels: [],
    defaults: { council: [], chairman: '' },
  });

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Fetch available models when API key changes
  const fetchModels = useCallback(async (apiKey) => {
    if (!apiKey) return;
    try {
      const data = await api.getAvailableModels(apiKey);
      setConfig((prev) => ({
        ...prev,
        availableModels: data.models || [],
        defaults: data.defaults || prev.defaults,
        // Apply defaults if no localStorage selections
        councilModels: prev.councilModels || data.defaults.council,
        chairmanModel: prev.chairmanModel || data.defaults.chairman,
      }));
    } catch (err) {
      console.error('Failed to fetch models:', err);
    }
  }, []);

  useEffect(() => {
    fetchModels(config.apiKey);
  }, [config.apiKey, fetchModels]);

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

  const handleConfigChange = (updates) => {
    setConfig((prev) => ({ ...prev, ...updates }));
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    if (!config.apiKey) {
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
      />
      <div className="main-area">
        {!config.apiKey && (
          <div className="api-key-banner">
            <span>Set your OpenRouter API key to get started.</span>
            <button onClick={() => setSettingsOpen(true)}>Open Settings</button>
          </div>
        )}
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          disabled={!config.apiKey}
        />
      </div>
      <SettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        config={config}
        onConfigChange={handleConfigChange}
      />
    </div>
  );
}

export default App;

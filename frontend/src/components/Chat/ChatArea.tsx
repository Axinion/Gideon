import { useRef, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { shouldAutoplayFinishedReply, useTtsStore } from '../../lib/tts';
import { stripThinkTags } from '../../lib/message-text';
import { Sparkles, PanelRightOpen, PanelRightClose, Database, Lightbulb, PenLine, Code2, ArrowUpRight, Plus, Cpu } from 'lucide-react';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatArea() {
  const activeId = useAppStore((s) => s.activeId);
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const createConversation = useAppStore((s) => s.createConversation);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const wasStreaming = useRef(false);
  const lastScrollTop = useRef(0);
  const isCurrentChatStreaming = streamState.isStreaming && streamState.conversationId === activeId;

  // Autoplay: speak a reply once it is finished, never while it streams -- a
  // partial sentence would be synthesized and then cut off by the next chunk.
  // autoSpokenId fences the message so re-renders cannot repeat it.
  const voiceOutputEnabled = useAppStore((s) => s.settings.voiceOutputEnabled);
  const voiceAutoplay = useAppStore((s) => s.settings.voiceAutoplay);
  // Probe the backend as soon as voice output is switched on. Without this the
  // first reply could never autoplay: `available` is only set by ensureHealth,
  // which until now ran solely from the per-message read-aloud button -- and
  // that button does not exist until a reply is already on screen.
  useEffect(() => {
    if (!voiceOutputEnabled) return;
    useTtsStore.getState().ensureHealth();
  }, [voiceOutputEnabled]);

  // Speak on the falling edge of a stream -- the moment a reply finishes -- and
  // never merely because a finished reply happens to be on screen. Opening the
  // app or switching conversations would otherwise read stale history aloud,
  // and browsers block that anyway: playback with no preceding user gesture is
  // rejected outright, so the failure would be silent in both senses.
  const streamingConversationRef = useRef<string | null>(null);
  useEffect(() => {
    const last = messages[messages.length - 1];
    const tts = useTtsStore.getState();
    const justFinished = shouldAutoplayFinishedReply(
      streamingConversationRef.current,
      activeId,
      streamState.isStreaming,
      last,
      tts.autoSpokenId,
    );
    streamingConversationRef.current = isCurrentChatStreaming ? activeId : null;

    if (!justFinished) return;
    if (!voiceOutputEnabled || !voiceAutoplay) return;

    if (!last || last.role !== 'assistant' || activeId === null) return;

    // Model loading may still be in flight when a fast reply completes. Wait
    // for the probe, then confirm that this is still the active finished reply.
    const completedConversationId = activeId;
    const completedMessageId = last.id;
    void tts.ensureHealth().then(() => {
      const app = useAppStore.getState();
      const currentTts = useTtsStore.getState();
      const currentLast = app.messages[app.messages.length - 1];
      if (app.activeId !== completedConversationId || app.streamState.isStreaming) return;
      if (!app.settings.voiceOutputEnabled || !app.settings.voiceAutoplay) return;
      if (currentLast?.id !== completedMessageId || currentTts.available !== true) return;
      if (currentTts.autoSpokenId === completedMessageId) return;

      const text = stripThinkTags(currentLast.content);
      if (!text) return;
      currentTts.markAutoSpoken(completedMessageId);
      void currentTts.speak(completedMessageId, text);
    });
  }, [activeId, messages, streamState.isStreaming, isCurrentChatStreaming, voiceOutputEnabled, voiceAutoplay]);
  const currentStreamContent = isCurrentChatStreaming ? streamState.content : '';

  const suggestPrompt = (prompt: string) => {
    window.dispatchEvent(new CustomEvent('jarvis:prompt', { detail: prompt }));
  };

  const startNewChat = () => {
    if (messages.length > 0) createConversation(selectedModel);
    navigate('/');
  };

  useEffect(() => {
    if (messages.length === 0 && !isCurrentChatStreaming) return;
    // Sending a message always pins the view to the bottom, even if the
    // user had scrolled up to read earlier messages.
    if (isCurrentChatStreaming && !wasStreaming.current) {
      shouldAutoScroll.current = true;
    }
    wasStreaming.current = isCurrentChatStreaming;
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, currentStreamContent, isCurrentChatStreaming]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    const distance = scrollHeight - scrollTop - clientHeight;
    const scrolledUp = scrollTop < lastScrollTop.current;
    lastScrollTop.current = scrollTop;
    if (scrolledUp && distance >= 1) {
      // Any upward scroll away from the bottom stops autoscroll immediately,
      // so streaming content never fights the user (no jitter). Sub-1px
      // upward movement (elastic bounce settling at the bottom) is ignored.
      shouldAutoScroll.current = false;
    } else if (!scrolledUp) {
      // Re-engage when scrolled back to the bottom. < 2 rather than < 1:
      // at fractional zoom levels the at-bottom residual can reach 1px,
      // which would otherwise leave autoscroll permanently disengaged.
      shouldAutoScroll.current = distance < 2;
    }
  };

  const isEmpty = messages.length === 0 && !isCurrentChatStreaming;

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;

  return (
    <div className="flex flex-col h-full">
      {/* Workspace toolbar */}
      <div className={`jarvis-chat-toolbar shrink-0 ${sidebarOpen ? '' : 'with-sidebar-toggle'}`}>
        <div className="jarvis-chat-toolbar-title">
          <span className="jarvis-toolbar-overline">YOUR WORKSPACE</span>
          <span className="jarvis-toolbar-name">Chat <span className="jarvis-toolbar-separator">/</span> <span>Gideon</span></span>
        </div>
        <div className="jarvis-toolbar-actions">
          <button className="jarvis-local-chip" onClick={() => setCommandPaletteOpen(true)} title="Choose a model">
            <span className="jarvis-live-dot" /><Cpu size={13} /> <span className="jarvis-local-label">{selectedModel.startsWith('chatgpt/') ? 'Using ChatGPT plan' : selectedModel || 'Local model'}</span>
          </button>
          <button onClick={startNewChat} className="jarvis-toolbar-icon" title="New conversation" aria-label="New conversation"><Plus size={18} /></button>
        <button
          onClick={toggleSystemPanel}
          className="jarvis-toolbar-icon"
          aria-label={systemPanelOpen ? 'Hide system panel' : 'Show system panel'}
          title={`${systemPanelOpen ? 'Hide' : 'Show'} system panel (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I)`}
        >
          <PanelIcon size={18} />
        </button>
        </div>
      </div>
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <div className="jarvis-welcome-wrap">
            <div className="jarvis-welcome-content">
              <div className="jarvis-hero-orb" aria-hidden="true"><Sparkles size={28} strokeWidth={1.6} /></div>
              <div className="jarvis-eyebrow"><span className="jarvis-live-dot" /> {getGreeting().toUpperCase()} · LOCAL AI DESK</div>
              <h1 className="jarvis-hero-title">A better place<br /><em>to think.</em></h1>
              <p className="jarvis-hero-subtitle">Write, explore, and figure things out with an AI that runs right here on your Mac.</p>
              <div className="jarvis-section-heading"><span>GET STARTED</span><span>Choose a direction ↓</span></div>
              <div className="jarvis-prompt-grid">
                <button className="jarvis-prompt-card" onClick={() => suggestPrompt('Help me brainstorm three fresh ideas for a project I could build this month.')}>
                  <span className="jarvis-prompt-icon purple"><Lightbulb size={19} /></span><span className="jarvis-prompt-copy"><strong>Brainstorm ideas</strong><small>Find a new angle</small></span><ArrowUpRight size={16} />
                </button>
                <button className="jarvis-prompt-card" onClick={() => suggestPrompt('Explain a complex topic to me in simple terms, with a concrete example. Ask me which topic first.')}>
                  <span className="jarvis-prompt-icon orange"><Sparkles size={19} /></span><span className="jarvis-prompt-copy"><strong>Learn something</strong><small>Make it click</small></span><ArrowUpRight size={16} />
                </button>
                <button className="jarvis-prompt-card" onClick={() => suggestPrompt('Help me draft a clear and friendly message. Ask me who it is for and what I want to say.')}>
                  <span className="jarvis-prompt-icon green"><PenLine size={19} /></span><span className="jarvis-prompt-copy"><strong>Draft a message</strong><small>Get the words right</small></span><ArrowUpRight size={16} />
                </button>
                <button className="jarvis-prompt-card" onClick={() => suggestPrompt('Help me plan a small coding project. Ask what I want to build and what tools I know.')}>
                  <span className="jarvis-prompt-icon blue"><Code2 size={19} /></span><span className="jarvis-prompt-copy"><strong>Build a project</strong><small>Start with a plan</small></span><ArrowUpRight size={16} />
                </button>
              </div>
              <div className="jarvis-welcome-footer">
                <button onClick={() => navigate('/data-sources')}><Database size={15} /> Connect your data <ArrowUpRight size={14} /></button>
                <div className="jarvis-welcome-external">
                  <button onClick={() => navigate('/settings')} title="Connect your ChatGPT plan in Settings">Use ChatGPT Plus <ArrowUpRight size={14} /></button>
                  <a href="https://muse.ai/" target="_blank" rel="noopener noreferrer" title="Opens Muse in a separate tab; this does not connect it to Gideon">Open Muse <ArrowUpRight size={14} /></a>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-6">
            {messages.map((msg, i) => {
              const isLastAssistant =
                i === messages.length - 1 && msg.role === 'assistant';
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLive={isLastAssistant && isCurrentChatStreaming}
                />
              );
            })}
            {(() => {
              if (!isCurrentChatStreaming || streamState.content !== '') return null;
              // For research messages the ResearchTimeline handles its own
              // pre-content loading state — suppress the generic dots.
              const last = messages[messages.length - 1];
              if (last?.role === 'assistant' && last.isResearch) return null;
              return (
                <div className="flex justify-start mb-4">
                  <StreamingDots phase={streamState.phase} />
                </div>
              );
            })()}
          </div>
        )}
      </div>
      <InputArea />
    </div>
  );
}

import { useState, useEffect, useRef, useCallback } from "react";
import { AnsiText } from "@/components/AnsiText";
import { Button } from "@/components/ui/button";
import { Plus, X, Terminal as TerminalIcon, Maximize2, Minimize2, Settings, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface OutputLine {
  id: string;
  type: 'command' | 'output' | 'error' | 'info' | 'welcome';
  content: string;
  timestamp: Date;
}

interface Tab {
  id: string;
  title: string;
  cwd: string;
  history: string[];
  historyIndex: number;
  output: OutputLine[];
  isConnected: boolean;
  ws: WebSocket | null;
}

let tabCounter = 1;

function createTab(): Tab {
  return {
    id: `tab-${Date.now()}-${tabCounter++}`,
    title: `Shell ${tabCounter - 1}`,
    cwd: '~',
    history: [],
    historyIndex: -1,
    output: [],
    isConnected: false,
    ws: null,
  };
}

const WELCOME_ART = `\x1b[32m
  ███████╗██╗  ██╗███████╗██╗     ██╗     
  ██╔════╝██║  ██║██╔════╝██║     ██║     
  ███████╗███████║█████╗  ██║     ██║     
  ╚════██║██╔══██║██╔══╝  ██║     ██║     
  ███████║██║  ██║███████╗███████╗███████╗
  ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
\x1b[0m\x1b[2mReplit Web Terminal — Type \x1b[0m\x1b[33mhelp\x1b[0m\x1b[2m for available commands\x1b[0m`;

export default function TerminalPage() {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string>('');
  const [isMaximized, setIsMaximized] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [fontSize, setFontSize] = useState(14);

  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const tabsRef = useRef<Map<string, Tab>>(new Map());

  const getActiveTab = useCallback(() => {
    return tabs.find(t => t.id === activeTabId) || null;
  }, [tabs, activeTabId]);

  const updateTab = useCallback((id: string, updates: Partial<Tab>) => {
    setTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t));
    const existing = tabsRef.current.get(id);
    if (existing) {
      tabsRef.current.set(id, { ...existing, ...updates });
    }
  }, []);

  const appendOutput = useCallback((tabId: string, line: Omit<OutputLine, 'id' | 'timestamp'>) => {
    const newLine: OutputLine = {
      ...line,
      id: `line-${Date.now()}-${Math.random()}`,
      timestamp: new Date(),
    };
    setTabs(prev => prev.map(t => {
      if (t.id !== tabId) return t;
      const tab = tabsRef.current.get(tabId);
      const updated = { ...t, output: [...t.output, newLine] };
      if (tab) tabsRef.current.set(tabId, { ...tab, output: updated.output });
      return updated;
    }));
  }, []);

  const connectWebSocket = useCallback((tabId: string) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/shell`);

    ws.onopen = () => {
      updateTab(tabId, { isConnected: true, ws });
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'output') {
          appendOutput(tabId, { type: 'output', content: msg.data });
        } else if (msg.type === 'error') {
          appendOutput(tabId, { type: 'error', content: msg.data });
        } else if (msg.type === 'clear') {
          setTabs(prev => prev.map(t => t.id === tabId ? { ...t, output: [] } : t));
          const tab = tabsRef.current.get(tabId);
          if (tab) tabsRef.current.set(tabId, { ...tab, output: [] });
        } else if (msg.type === 'cwd') {
          updateTab(tabId, { cwd: msg.data });
          setTabs(prev => prev.map(t => {
            if (t.id !== tabId) return t;
            const parts = msg.data.split('/');
            const dirName = parts[parts.length - 1] || '/';
            return { ...t, title: dirName || 'Shell' };
          }));
        }
      } catch {
        appendOutput(tabId, { type: 'output', content: event.data });
      }
    };

    ws.onclose = () => {
      updateTab(tabId, { isConnected: false, ws: null });
      appendOutput(tabId, { type: 'info', content: '\x1b[33mConnection closed. Reconnecting...\x1b[0m' });
      setTimeout(() => connectWebSocket(tabId), 2000);
    };

    ws.onerror = () => {
      appendOutput(tabId, { type: 'error', content: '\x1b[31mConnection error\x1b[0m' });
    };
  }, [updateTab, appendOutput]);

  const addTab = useCallback(() => {
    const tab = createTab();
    tab.output = [{
      id: `welcome-${Date.now()}`,
      type: 'welcome',
      content: WELCOME_ART,
      timestamp: new Date(),
    }];
    tabsRef.current.set(tab.id, tab);
    setTabs(prev => [...prev, tab]);
    setActiveTabId(tab.id);
    connectWebSocket(tab.id);
    return tab.id;
  }, [connectWebSocket]);

  const removeTab = useCallback((tabId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const tab = tabsRef.current.get(tabId);
    if (tab?.ws) {
      tab.ws.close();
    }
    tabsRef.current.delete(tabId);
    setTabs(prev => {
      const filtered = prev.filter(t => t.id !== tabId);
      if (activeTabId === tabId && filtered.length > 0) {
        setActiveTabId(filtered[filtered.length - 1].id);
      }
      return filtered;
    });
  }, [activeTabId]);

  useEffect(() => {
    addTab();
  }, []);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [tabs]);

  useEffect(() => {
    if (activeTabId) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [activeTabId]);

  const sendCommand = useCallback((command: string) => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return;

    appendOutput(activeTabId, {
      type: 'command',
      content: command,
    });

    if (command.trim()) {
      const newHistory = [command, ...activeTab.history.slice(0, 99)];
      updateTab(activeTabId, {
        history: newHistory,
        historyIndex: -1,
      });
    }

    if (activeTab.ws && activeTab.ws.readyState === WebSocket.OPEN) {
      activeTab.ws.send(JSON.stringify({ type: 'command', data: command }));
    } else {
      appendOutput(activeTabId, {
        type: 'error',
        content: '\x1b[31mNot connected. Please wait...\x1b[0m',
      });
    }
  }, [tabs, activeTabId, appendOutput, updateTab]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return;

    if (e.key === 'Enter') {
      const cmd = inputValue;
      setInputValue('');
      sendCommand(cmd);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const nextIndex = Math.min(activeTab.historyIndex + 1, activeTab.history.length - 1);
      if (activeTab.history[nextIndex] !== undefined) {
        setInputValue(activeTab.history[nextIndex]);
        updateTab(activeTabId, { historyIndex: nextIndex });
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const nextIndex = activeTab.historyIndex - 1;
      if (nextIndex < 0) {
        setInputValue('');
        updateTab(activeTabId, { historyIndex: -1 });
      } else {
        setInputValue(activeTab.history[nextIndex] || '');
        updateTab(activeTabId, { historyIndex: nextIndex });
      }
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      setTabs(prev => prev.map(t => t.id === activeTabId ? { ...t, output: [] } : t));
      const existing = tabsRef.current.get(activeTabId);
      if (existing) tabsRef.current.set(activeTabId, { ...existing, output: [] });
    } else if (e.key === 'c' && e.ctrlKey) {
      e.preventDefault();
      appendOutput(activeTabId, { type: 'output', content: '^C' });
      setInputValue('');
      if (activeTab.ws && activeTab.ws.readyState === WebSocket.OPEN) {
        activeTab.ws.send(JSON.stringify({ type: 'interrupt' }));
      }
    } else if (e.key === 't' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      addTab();
    }
  }, [tabs, activeTabId, inputValue, sendCommand, updateTab, appendOutput, addTab]);

  const activeTab = getActiveTab();

  return (
    <div
      className={cn(
        "flex flex-col h-screen bg-background select-none",
        isMaximized && "fixed inset-0 z-50"
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {/* Top bar */}
      <div className="flex items-center h-10 bg-[hsl(220,15%,6%)] border-b border-border flex-shrink-0 select-none">
        {/* Traffic lights */}
        <div className="flex items-center gap-1.5 px-3 flex-shrink-0">
          <div className="w-3 h-3 rounded-full bg-[#ff5f57] border border-[#e0443e]" />
          <div className="w-3 h-3 rounded-full bg-[#febc2e] border border-[#d89d19]" />
          <div className="w-3 h-3 rounded-full bg-[#28c840] border border-[#1aab29]" />
        </div>

        {/* Tabs */}
        <div className="flex-1 flex items-end overflow-x-auto tab-scroll min-w-0 h-full">
          <div className="flex items-end gap-0.5 px-1 h-full">
            {tabs.map(tab => (
              <button
                key={tab.id}
                data-testid={`tab-${tab.id}`}
                onClick={(e) => { e.stopPropagation(); setActiveTabId(tab.id); }}
                className={cn(
                  "group flex items-center gap-2 px-3 h-8 text-xs font-mono rounded-t transition-colors flex-shrink-0",
                  tab.id === activeTabId
                    ? "bg-[hsl(220,13%,12%)] text-foreground border-t border-x border-border"
                    : "text-muted-foreground hover:text-foreground hover:bg-[hsl(220,13%,9%)]"
                )}
              >
                <TerminalIcon className="w-3 h-3 flex-shrink-0 text-primary" />
                <span className="max-w-[120px] truncate">{tab.title}</span>
                <div
                  className={cn(
                    "w-1.5 h-1.5 rounded-full flex-shrink-0 ml-0.5",
                    tab.isConnected ? "bg-primary" : "bg-muted-foreground"
                  )}
                />
                {tabs.length > 1 && (
                  <button
                    data-testid={`close-tab-${tab.id}`}
                    onClick={(e) => removeTab(tab.id, e)}
                    className="invisible group-hover:visible text-muted-foreground hover:text-foreground ml-0.5 -mr-1"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 px-2 flex-shrink-0">
          <Button
            size="icon"
            variant="ghost"
            data-testid="button-new-tab"
            onClick={(e) => { e.stopPropagation(); addTab(); }}
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            title="New Tab (Ctrl+T)"
          >
            <Plus className="w-3.5 h-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            data-testid="button-settings"
            onClick={(e) => { e.stopPropagation(); setShowSettings(s => !s); }}
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
          >
            <Settings className="w-3.5 h-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            data-testid="button-maximize"
            onClick={(e) => { e.stopPropagation(); setIsMaximized(m => !m); }}
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
          >
            {isMaximized ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div
          className="absolute top-10 right-2 z-50 bg-card border border-card-border rounded-md shadow-lg p-4 w-64"
          onClick={e => e.stopPropagation()}
        >
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Settings</p>
          <div className="flex items-center justify-between">
            <span className="text-sm text-foreground">Font Size</span>
            <div className="flex items-center gap-2">
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6"
                onClick={() => setFontSize(s => Math.max(10, s - 1))}
                data-testid="button-font-decrease"
              >
                <span className="text-xs">-</span>
              </Button>
              <span className="text-sm font-mono w-6 text-center" data-testid="text-font-size">{fontSize}</span>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6"
                onClick={() => setFontSize(s => Math.min(24, s + 1))}
                data-testid="button-font-increase"
              >
                <span className="text-xs">+</span>
              </Button>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-border">
            <p className="text-xs text-muted-foreground">Keyboard Shortcuts</p>
            <div className="mt-2 space-y-1">
              {[
                ['Ctrl+T', 'New tab'],
                ['Ctrl+L', 'Clear screen'],
                ['Ctrl+C', 'Interrupt'],
                ['↑ / ↓', 'History'],
              ].map(([key, desc]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">{desc}</span>
                  <kbd className="text-xs font-mono bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded">{key}</kbd>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Terminal body */}
      <div className="flex-1 flex flex-col min-h-0 bg-[hsl(220,13%,10%)]">
        {/* Output area */}
        <div
          ref={outputRef}
          className="flex-1 overflow-y-auto terminal-scroll p-4 min-h-0"
          style={{ fontSize: `${fontSize}px`, lineHeight: '1.6' }}
        >
          {activeTab?.output.map(line => (
            <div key={line.id} className="terminal-output">
              {line.type === 'command' ? (
                <div className="flex items-start gap-2">
                  <span className="text-primary flex-shrink-0 select-none">
                    {activeTab.cwd}
                    <span className="text-muted-foreground"> ❯ </span>
                  </span>
                  <span className="text-foreground break-all">{line.content}</span>
                </div>
              ) : line.type === 'welcome' ? (
                <div className="mb-2">
                  <AnsiText text={line.content} />
                </div>
              ) : (
                <div className={cn(
                  "break-all",
                  line.type === 'info' && "text-muted-foreground"
                )}>
                  <AnsiText text={line.content} />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Input area */}
        <div
          className="flex items-center gap-2 px-4 py-3 border-t border-border bg-[hsl(220,15%,8%)] flex-shrink-0"
          style={{ fontSize: `${fontSize}px` }}
        >
          <div className="flex items-center gap-1 flex-shrink-0 font-mono">
            <span className="text-primary font-semibold">{activeTab?.cwd || '~'}</span>
            <ChevronRight className="text-muted-foreground" style={{ width: fontSize, height: fontSize }} />
          </div>
          <input
            ref={inputRef}
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            data-testid="input-command"
            className="flex-1 bg-transparent outline-none text-foreground font-mono caret-primary placeholder:text-muted-foreground"
            style={{ fontSize: `${fontSize}px` }}
            placeholder={activeTab?.isConnected ? '' : 'Connecting...'}
            disabled={!activeTab?.isConnected}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
          />
          {activeTab?.isConnected ? (
            <span className="w-2 h-4 bg-primary cursor-blink flex-shrink-0" />
          ) : (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              <span className="text-xs text-muted-foreground font-mono">connecting</span>
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className="flex items-center justify-between px-4 py-1 bg-primary text-primary-foreground text-xs font-mono flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <TerminalIcon className="w-3 h-3" />
            <span>bash</span>
          </span>
          <span className="opacity-70">|</span>
          <span data-testid="status-cwd">{activeTab?.cwd || '~'}</span>
        </div>
        <div className="flex items-center gap-3 opacity-70">
          <span>{tabs.length} tab{tabs.length !== 1 ? 's' : ''}</span>
          <span>•</span>
          <span>UTF-8</span>
        </div>
      </div>
    </div>
  );
}

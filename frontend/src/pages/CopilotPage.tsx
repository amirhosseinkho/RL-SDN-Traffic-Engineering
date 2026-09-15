import { useState, useRef, useEffect } from 'react';
import { copilotApi } from '../services/api';
import { MessageSquare, Send, Bot, User, Loader } from 'lucide-react';
import type { CopilotResponse } from '../types';

const SUGGESTIONS = [
  'Why is latency increasing on this network?',
  'Which links are congested right now?',
  'Why did the RL agent reroute traffic?',
  'Explain the current network state.',
  'How does DQN compare to PPO for routing?',
  'What causes packet loss in SDN?',
];

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  latency_ms?: number;
  model?: string;
}

export function CopilotPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content:
        "Hi! I'm the AI Network Copilot. I can answer questions about your SDN network state, explain RL agent decisions, and help diagnose performance issues. What would you like to know?",
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async (query: string) => {
    if (!query.trim() || loading) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const resp = await copilotApi.query(query);
      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: resp.response,
        latency_ms: resp.latency_ms,
        model: resp.model_used,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Sorry, I encountered an error: ${e.message}`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full max-h-[calc(100vh-120px)]">
      <div className="flex items-center gap-2 mb-4">
        <Bot size={20} className="text-emerald-400" />
        <h1 className="text-xl font-bold text-white">AI Network Copilot</h1>
        <span className="text-xs text-slate-500 ml-1">Powered by Ollama / local LLM</span>
      </div>

      {/* Chat */}
      <div className="flex-1 overflow-y-auto bg-slate-900 border border-slate-700 rounded-xl p-4 space-y-4 mb-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 animate-fade-in ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-emerald-600 flex items-center justify-center shrink-0 mt-0.5">
                <Bot size={14} className="text-white" />
              </div>
            )}
            <div
              className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 border border-slate-700 text-slate-100'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
              {msg.latency_ms && (
                <p className="text-xs text-slate-500 mt-1.5">
                  {msg.model} · {msg.latency_ms.toFixed(0)}ms
                </p>
              )}
            </div>
            {msg.role === 'user' && (
              <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                <User size={14} className="text-white" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-emerald-600 flex items-center justify-center shrink-0">
              <Bot size={14} className="text-white" />
            </div>
            <div className="bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5">
              <div className="flex gap-1 items-center h-5">
                <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="flex flex-wrap gap-2 mb-3">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => sendMessage(s)}
            className="text-xs px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-full text-slate-300 hover:border-slate-500 hover:text-white transition-colors"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-3">
        <input
          className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
          placeholder="Ask about network state, RL decisions, congestion..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage(input)}
        />
        <button
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
          className="px-4 py-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 rounded-xl text-white transition-colors"
        >
          {loading ? <Loader size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  );
}

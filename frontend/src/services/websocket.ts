import type { WSMessage, TrainingUpdate } from '../types';

type WSCallback<T> = (data: T) => void;

export class MetricsWebSocket {
  private ws: WebSocket | null = null;
  private callbacks: Map<string, WSCallback<unknown>[]> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private url: string;

  constructor(url = `ws://${window.location.host}/ws/metrics`) {
    this.url = url;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.info('[WS] Connected to metrics stream');
      this.reconnectDelay = 1000;
      this.emit('connected', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        this.emit(message.event, message.data);
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    this.ws.onclose = () => {
      console.warn('[WS] Disconnected, reconnecting...');
      this.emit('disconnected', {});
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }

  on<T>(event: string, cb: WSCallback<T>): () => void {
    const list = this.callbacks.get(event) ?? [];
    list.push(cb as WSCallback<unknown>);
    this.callbacks.set(event, list);
    return () => {
      this.callbacks.set(
        event,
        (this.callbacks.get(event) ?? []).filter((fn) => fn !== cb)
      );
    };
  }

  private emit(event: string, data: unknown): void {
    (this.callbacks.get(event) ?? []).forEach((cb) => cb(data));
    (this.callbacks.get('*') ?? []).forEach((cb) => cb({ event, data }));
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export class TrainingWebSocket {
  private ws: WebSocket | null = null;
  private onUpdate: ((data: TrainingUpdate) => void) | null = null;
  private onDone: (() => void) | null = null;

  constructor(private sessionId: string) {}

  connect(
    onUpdate: (data: TrainingUpdate) => void,
    onDone?: () => void
  ): void {
    this.onUpdate = onUpdate;
    this.onDone = onDone ?? null;

    const url = `ws://${window.location.host}/ws/training/${this.sessionId}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage<TrainingUpdate> = JSON.parse(event.data);
        if (msg.event === 'training_update' && this.onUpdate) {
          this.onUpdate(msg.data);
          if (['completed', 'failed', 'paused'].includes(msg.data.status)) {
            this.onDone?.();
          }
        }
      } catch (e) {
        console.error('[TrainingWS] Parse error:', e);
      }
    };

    this.ws.onerror = (err) => console.error('[TrainingWS] Error:', err);
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }
}

// Singleton metrics WS instance
export const metricsWS = new MetricsWebSocket();

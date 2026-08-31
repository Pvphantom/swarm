// WebSocket state-stream handler with auto-reconnect.
export class StateSocket {
  constructor(onState, onStatus) {
    this.onState = onState;
    this.onStatus = onStatus || (() => {});
    this.ws = null;
    this._stop = false;
  }

  connect() {
    this._stop = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/simulation`;
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => this.onStatus("connected");
    ws.onmessage = (ev) => {
      try {
        const state = JSON.parse(ev.data);
        this.onState(state);
      } catch (e) { /* ignore malformed frame */ }
    };
    ws.onclose = () => {
      this.onStatus("disconnected");
      if (!this._stop) setTimeout(() => this.connect(), 1000);
    };
    ws.onerror = () => ws.close();
  }

  close() {
    this._stop = true;
    if (this.ws) this.ws.close();
  }
}

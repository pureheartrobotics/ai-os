// Hands-free voice conversation for DeepSeek Harness: press F8 (or the whale button), speak, and the transcript is
// sent automatically; the final reply is read aloud, then the microphone reopens for a follow-up.
// Recognition goes through the official Voice Input plugin's speech Remote, so no extra API key is needed.
window.__ModuleLoader__.load({id: `dsh-ai-os`, factory: require => {
var module = {exports: {}};
var exports = module.exports;
Object.defineProperty(exports, Symbol.toStringTag, {value: `Module`});
const React = require("react");
const ui = require("@deepseek-ai/dsh-client-ui-primitives");
const h = React.createElement;

const BUNDLE = "dsh-ai-os";
const HOTKEY = "F8";
const TARGET_RATE = 16000;
const FRAME = 1024;
const START_FRAMES = 4;
const CALIBRATION_FRAMES = 8;
const NOISE_RATIO = 3.5;
const MIN_SPEECH_MS = 400;
// The level after the browser's echo cancellation and Windows' microphone processing is often low.
const MIN_THRESHOLD = 0.004;
const END_SILENCE_MS = 900;
const MAX_SECONDS = 30;
const FIRST_WAIT_MS = 8000;
const FOLLOW_UP_WAIT_MS = 8000;
const MAX_SPOKEN_CHARS = 240;
const NEED_VOICE_INPUT = "请先在“插件”中启用官方的“语音输入”，并完成模型准备";
const BLUE = "#4D6BFE";

const PHASES = {
  idle: { title: "语音对话", color: BLUE },
  listening: { title: "我在听", color: "#22c55e" },
  transcribing: { title: "识别中", color: "#f59e0b" },
  waiting: { title: "执行中", color: "#a78bfa" },
  speaking: { title: "回复中", color: "#38bdf8" },
  error: { title: "需要处理", color: "#f87171" },
};
const ERROR_VISIBLE_MS = 6000;
const HANDOFF_MS = 5000;

const WHALE_PATHS = `
  <path d="M59 41.5c0 5.2-4.3 8.5-10.5 8.5H27c-8.6 0-15.4-4.6-18.3-11.6-1.4-3.4-4.3-6.3-6.2-9.6-.9-1.6.6-3.3 2.3-2.5 3.4 1.7 6 4.7 8.4 7.6 2 2.4 4.4 3.6 7.8 3.6h1.5C24.6 28.6 32.8 23 43 23c9.5 0 16 7.5 16 18.5Z" fill="BODY"/>
  <path d="M4.2 26.4c-.6-4.3.8-8.1 4.1-10.6.3 3.6 1.6 6.2 4.4 8.2-3.6.3-6.2.9-8.5 2.4Z" fill="BODY"/>
  <path d="M25 45.5h25" stroke="EYE" stroke-opacity=".45" stroke-width="2" stroke-linecap="round"/>
  <circle cx="49" cy="35.5" r="2.3" fill="EYE"/>`;
const WHALE_WAVES = `
  <path class="aios-wave aios-wave-1" d="M38.5 16.5a6.5 6.5 0 0 1 9 0" stroke="WAVE" stroke-width="2.8" stroke-linecap="round"/>
  <path class="aios-wave aios-wave-2" d="M34.5 11a12.5 12.5 0 0 1 17 0" stroke="WAVE" stroke-width="2.8" stroke-linecap="round" stroke-opacity=".6"/>`;

/** Whale glyph: `mono` follows currentColor for toolbar use; otherwise the brand gradient. */
function whaleSvg(size, mono) {
  const body = mono ? "currentColor" : "url(#aios-g-body)";
  const defs = mono ? "" : `<defs>
    <linearGradient id="aios-g-body" x1="4" y1="18" x2="56" y2="52" gradientUnits="userSpaceOnUse"><stop stop-color="#7B96FF"/><stop offset="1" stop-color="#3554E8"/></linearGradient>
    <linearGradient id="aios-g-wave" x1="34" y1="9" x2="52" y2="18" gradientUnits="userSpaceOnUse"><stop stop-color="#67C7FE"/><stop offset="1" stop-color="${BLUE}"/></linearGradient></defs>`;
  const paths = (WHALE_PATHS + WHALE_WAVES)
    .replaceAll("BODY", body).replaceAll("EYE", mono ? "var(--aios-eye, #fff)" : "#fff")
    .replaceAll("WAVE", mono ? "currentColor" : "url(#aios-g-wave)");
  return `<svg width="${size}" height="${size}" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${paths}${defs}</svg>`;
}

const STYLE = `
.aios-panel{position:fixed;top:18px;left:50%;transform:translate(-50%,-8px);opacity:0;z-index:2147483000;
  display:flex;align-items:center;gap:16px;min-width:360px;max-width:min(560px,calc(100vw - 32px));padding:14px 20px 14px 16px;
  border-radius:20px;background:rgba(15,23,42,.94);color:#e2e8f0;box-shadow:0 18px 50px rgba(15,23,42,.35),0 0 0 1px rgba(255,255,255,.06) inset;
  font:14px/1.45 system-ui,-apple-system,"Microsoft YaHei UI",sans-serif;pointer-events:none;transition:opacity .2s ease,transform .2s ease}
.aios-panel.aios-show{opacity:1;transform:translate(-50%,0)}
.aios-whale{position:relative;flex:none;width:56px;height:56px;border-radius:16px;display:grid;place-items:center;
  background:radial-gradient(circle at 30% 25%,rgba(103,199,254,.28),rgba(77,107,254,.12) 60%,transparent 70%)}
.aios-whale::after{content:"";position:absolute;inset:-3px;border-radius:19px;border:2px solid var(--aios-accent);opacity:.0}
.aios-panel[data-phase=listening] .aios-whale::after{animation:aios-ring 1.6s ease-out infinite}
.aios-panel[data-phase=listening] .aios-whale svg,.aios-panel[data-phase=speaking] .aios-whale svg{animation:aios-bob 2.4s ease-in-out infinite}
.aios-panel[data-phase=speaking] .aios-wave,.aios-panel[data-phase=listening] .aios-wave{animation:aios-spout 1.2s ease-in-out infinite}
.aios-panel .aios-wave-2{animation-delay:.25s!important}
.aios-panel[data-phase=transcribing] .aios-whale svg,.aios-panel[data-phase=waiting] .aios-whale svg{animation:aios-think 1.4s ease-in-out infinite}
.aios-body{min-width:0;flex:1}
.aios-head{display:flex;align-items:center;gap:8px;font-weight:600;font-size:15px;color:#fff}
.aios-dot{width:8px;height:8px;border-radius:50%;background:var(--aios-accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--aios-accent) 25%,transparent)}
.aios-meter{display:flex;align-items:flex-end;gap:3px;height:16px;margin-left:auto}
.aios-meter i{width:3px;border-radius:2px;background:var(--aios-accent);height:3px;transition:height .08s linear}
.aios-text{margin-top:2px;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.aios-hint{margin-top:4px;font-size:12px;color:#64748b}
@keyframes aios-ring{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(1.25)}}
@keyframes aios-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}
@keyframes aios-spout{0%,100%{opacity:.35}50%{opacity:1}}
@keyframes aios-think{0%,100%{opacity:1}50%{opacity:.55}}
.aios-trigger{color:${BLUE}}
.aios-trigger[data-phase=listening]{color:#16a34a}.aios-trigger[data-phase=transcribing],.aios-trigger[data-phase=waiting]{color:#d97706}
.aios-trigger[data-phase=speaking]{color:#0284c7}
.aios-trigger svg{--aios-eye:var(--aios-eye-bg,#fff)}
@media (prefers-reduced-motion:reduce){.aios-panel *,.aios-panel *::after{animation:none!important}}
`;

// ---------- audio ----------

/** Microphone chosen in the official Voice Input settings; empty follows the system input. */
function preferredMicrophone() {
  try {
    const saved = JSON.parse(localStorage.getItem("dsh.voice-input.microphone") || "null");
    const value = saved && typeof saved === "object" && "state" in saved ? saved.state : saved;
    return value && typeof value.id === "string" ? value.id : "";
  } catch { return ""; }
}

async function openMicrophone() {
  const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
  const id = preferredMicrophone();
  if (id) {
    try { return await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: id } }, video: false }); }
    catch (error) { if (error?.name !== "OverconstrainedError" && error?.name !== "NotFoundError") throw error; }
  }
  return navigator.mediaDevices.getUserMedia({ audio: base, video: false });
}

function describeError(error) {
  switch (error?.name) {
    case "NotAllowedError": return "麦克风权限被拒绝：请在 Windows 设置 › 隐私和安全性 › 麦克风 中允许桌面应用访问";
    case "NotFoundError": return "没有找到麦克风，请检查设备连接";
    case "NotReadableError": return "麦克风被其他程序占用，请关闭后重试";
    default: return String(error?.message || error);
  }
}

function encodeWave(samples) {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const text = (at, value) => { for (let i = 0; i < value.length; i++) bytes[at + i] = value.charCodeAt(i); };
  text(0, "RIFF"); view.setUint32(4, bytes.length - 8, true); text(8, "WAVE"); text(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
  }
  return bytes;
}

function base64(bytes) {
  let text = "";
  for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(text);
}

async function resample(chunks, rate) {
  const length = chunks.reduce((n, c) => n + c.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.length; }
  const offline = new OfflineAudioContext(1, Math.max(1, Math.round(length * TARGET_RATE / rate)), TARGET_RATE);
  const buffer = offline.createBuffer(1, length, rate);
  buffer.copyToChannel(merged, 0);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  return (await offline.startRendering()).getChannelData(0);
}

/**
 * Record one utterance with energy-based end-of-speech detection.
 * @param options.waitMs - give up when nobody starts speaking in time.
 * @param options.fixedMs - record exactly this long instead (microphone test).
 * @returns 16 kHz PCM16 WAV bytes, or null when nobody spoke or the signal aborted.
 */
async function captureUtterance(signal, { waitMs = FIRST_WAIT_MS, fixedMs = 0, onLevel = () => {}, onSpeech = () => {} } = {}) {
  const stream = await openMicrophone();
  const context = new AudioContext();
  try {
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(FRAME, 1, 1);
    const frameMs = FRAME / context.sampleRate * 1000;
    const chunks = await new Promise(resolve => {
      const preRoll = [];
      let voiced = [];
      let floor = 0, threshold = MIN_THRESHOLD, frames = 0, loud = 0, speaking = false;
      let waited = 0, silence = 0, total = 0, active = 0;
      const finish = value => { processor.onaudioprocess = null; resolve(value); };
      signal.addEventListener("abort", () => finish(null), { once: true });
      processor.onaudioprocess = event => {
        const frame = new Float32Array(event.inputBuffer.getChannelData(0));
        let sum = 0;
        for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
        const rms = Math.sqrt(sum / frame.length);
        onLevel(rms);
        if (fixedMs) {
          voiced.push(frame);
          total += frameMs;
          if (total >= fixedMs) finish(voiced);
          return;
        }
        if (!speaking) {
          waited += frameMs;
          preRoll.push(frame);
          if (preRoll.length > 8) preRoll.shift();
          // Automatic gain makes room noise loud; learn it before listening for speech.
          if (++frames <= CALIBRATION_FRAMES) { floor = frames === 1 ? rms : 0.7 * floor + 0.3 * rms; return; }
          threshold = Math.max(MIN_THRESHOLD, floor * NOISE_RATIO);
          loud = rms > threshold ? loud + 1 : 0;
          if (loud >= START_FRAMES) {
            speaking = true;
            voiced = [...preRoll];
            total = active = silence = 0;
            onSpeech();
          } else {
            if (loud === 0) floor = 0.95 * floor + 0.05 * rms;
            if (waited >= waitMs) finish(null);
          }
          return;
        }
        voiced.push(frame);
        total += frameMs;
        if (rms >= threshold) { active += frameMs; silence = 0; } else silence += frameMs;
        if (silence >= END_SILENCE_MS && active < MIN_SPEECH_MS) { speaking = false; loud = 0; return; }
        if (silence >= END_SILENCE_MS || total >= MAX_SECONDS * 1000) finish(voiced);
      };
      source.connect(processor);
      processor.connect(context.destination);
    });
    if (!chunks) return null;
    return encodeWave(await resample(chunks, context.sampleRate));
  } finally {
    stream.getTracks().forEach(track => track.stop());
    if (context.state !== "closed") await context.close();
  }
}

// ---------- speech output ----------

function toSpeech(markdown) {
  let text = markdown
    .replace(/```[\s\S]*?```/g, "（代码略）")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/^\s*\|?\s*:?-{3,}.*$/gm, "")
    .replace(/[*_~|#]/g, "")
    .replace(/\n{2,}/g, "。")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length > MAX_SPOKEN_CHARS) text = text.slice(0, MAX_SPOKEN_CHARS) + "……详细内容请看屏幕。";
  return text;
}

function chineseVoice() {
  const voices = typeof speechSynthesis === "undefined" ? [] : speechSynthesis.getVoices();
  const zh = voices.filter(v => (v.lang || "").toLowerCase().startsWith("zh"));
  return zh.find(v => /xiaoxiao|yunxi|natural/i.test(v.name)) || zh.find(v => /cn/i.test(v.lang)) || zh[0];
}

// Chromium drops `end` for utterances that are garbage-collected, cancelled-then-spoken, or longer than ~15 s,
// so speech goes out sentence by sentence, each held here and bounded by a timeout.
let currentUtterance = null;

function speakSentence(text, signal) {
  return new Promise(resolve => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    const voice = chineseVoice();
    if (voice) utterance.voice = voice;
    utterance.rate = 1.1;
    currentUtterance = utterance;
    const timer = setTimeout(done, 2000 + text.length * 350);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", stop);
      if (currentUtterance === utterance) currentUtterance = null;
      resolve();
    }
    function stop() { speechSynthesis.cancel(); done(); }
    utterance.onend = utterance.onerror = done;
    signal.addEventListener("abort", stop, { once: true });
    speechSynthesis.speak(utterance);
  });
}

async function speak(text, signal) {
  if (!text || typeof speechSynthesis === "undefined") return;
  if (speechSynthesis.speaking || speechSynthesis.pending) speechSynthesis.cancel();
  const sentences = text.match(/[^。！？!?；;\n]+[。！？!?；;]?/g) || [text];
  for (const sentence of sentences) {
    if (signal.aborted) return;
    if (sentence.trim()) await speakSentence(sentence.trim(), signal);
  }
}

function replyText(entries, turn) {
  for (let i = entries.length - 1; i >= 0; i--) {
    const event = entries[i].event;
    if (!event || event.type !== "assistant/message" || event.data.turn !== turn) continue;
    const content = event.data.message && event.data.message.content || [];
    const text = content.filter(block => block.type === "text").map(block => block.text).join("\n").trim();
    if (text) return text;
  }
  return "";
}

// ---------- status panel ----------

/** Floating whale card on document.body; plain DOM so it escapes the composer's stacking context. */
class Panel {
  constructor() {
    this.root = document.createElement("div");
    this.root.className = "aios-panel";
    this.root.setAttribute("role", "status");
    this.root.innerHTML = `<div class="aios-whale">${whaleSvg(40)}</div>
      <div class="aios-body"><div class="aios-head"><span class="aios-dot"></span><span class="aios-title"></span>
      <span class="aios-meter">${"<i></i>".repeat(7)}</span></div>
      <div class="aios-text"></div><div class="aios-hint"></div></div>`;
    this.title = this.root.querySelector(".aios-title");
    this.text = this.root.querySelector(".aios-text");
    this.hint = this.root.querySelector(".aios-hint");
    this.bars = [...this.root.querySelectorAll(".aios-meter i")];
    this.meter = this.root.querySelector(".aios-meter");
    this.levels = new Array(this.bars.length).fill(0);
  }

  render(state) {
    const visible = state.phase !== "idle";
    if (visible && !this.root.isConnected) {
      document.body.append(this.root);
      requestAnimationFrame(() => this.root.classList.add("aios-show"));
    } else if (!visible && this.root.isConnected) {
      this.root.classList.remove("aios-show");
      clearTimeout(this.hideTimer);
      this.hideTimer = setTimeout(() => { if (!this.root.classList.contains("aios-show")) this.root.remove(); }, 220);
    }
    if (!visible) return;
    const phase = PHASES[state.phase];
    this.root.dataset.phase = state.phase;
    this.root.style.setProperty("--aios-accent", phase.color);
    this.title.textContent = phase.title;
    this.text.textContent = state.text;
    this.hint.textContent = state.hint;
    this.meter.style.visibility = state.phase === "listening" ? "visible" : "hidden";
  }

  level(rms) {
    this.levels.shift();
    this.levels.push(Math.min(1, Math.sqrt(rms) * 5));
    this.bars.forEach((bar, i) => { bar.style.height = `${3 + this.levels[i] * 13}px`; });
  }

  dispose() { clearTimeout(this.hideTimer); this.root.remove(); }
}

// ---------- controller ----------

/** One voice loop per page, bound to whichever Session composer mounted last. */
class VoiceController {
  constructor(speech) {
    this.speech = speech;
    this.state = { phase: "idle", text: "", hint: "", notice: "" };
    this.listeners = new Set();
    this.target = null;
    this.abort = null;
    this.awaitingReply = false;
    this.detachedAt = 0;
    this.unwatch = () => {};
    this.panel = new Panel();
  }

  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  getSnapshot() { return this.state; }

  set(patch) {
    this.state = { ...this.state, ...patch };
    this.panel.render(this.state);
    for (const listener of this.listeners) listener();
  }

  attach(target) {
    const same = this.target && this.target.sessionId === target.sessionId;
    // Sending from a draft remounts the composer under the new Session; the pending reply follows it.
    if (!same && this.state.phase === "waiting" && Date.now() - this.detachedAt > HANDOFF_MS) this.cancel();
    this.target = target;
    if (!same) this.watch(target);
  }

  detach(target) {
    if (this.target !== target) return;
    this.unwatch();
    this.target = null;
    this.detachedAt = Date.now();
    if (this.state.phase !== "waiting") this.cancel();
  }

  watch(target) {
    this.unwatch();
    let timer, unsubscribe = () => {};
    const attach = () => {
      const binding = target.binding(target.sessionId);
      if (!binding) { timer = setTimeout(attach, 1000); return; }
      const source = binding.eventSource;
      unsubscribe = source.subscribe(() => {
        const snapshot = source.getSnapshot();
        if (snapshot.change.kind !== "append") return;
        for (const entry of snapshot.change.entries) {
          const event = entry.event;
          if (!event || event.type !== "turn/end" || !this.awaitingReply) continue;
          this.awaitingReply = false;
          const completed = event.data.reason?.kind === "completed";
          const reply = completed ? replyText(snapshot.entries, event.data.turn) : "任务没有完成，请看屏幕上的提示。";
          void this.respond(reply || "完成了。");
        }
      });
    };
    attach();
    this.unwatch = () => { clearTimeout(timer); unsubscribe(); };
  }

  begin() {
    this.abort?.abort();
    this.abort = new AbortController();
    return this.abort.signal;
  }

  cancel() {
    this.abort?.abort();
    this.abort = null;
    this.awaitingReply = false;
    this.set({ phase: "idle", text: "", hint: "" });
  }

  toggle() {
    const { phase } = this.state;
    if (phase === "idle" || phase === "speaking" || phase === "error") void this.listen(FIRST_WAIT_MS);
    else this.cancel();
  }

  fail(message) {
    this.set({ phase: "error", text: message, hint: `按 ${HOTKEY} 重试`, notice: message });
    clearTimeout(this.errorTimer);
    this.errorTimer = setTimeout(() => { if (this.state.phase === "error") this.set({ phase: "idle" }); }, ERROR_VISIBLE_MS);
  }

  async listen(waitMs) {
    if (!this.target) return;
    const signal = this.begin();
    this.set({ phase: "listening", text: waitMs === FIRST_WAIT_MS ? "请说出你的指令" : "还有什么需要？可以直接说",
      hint: `${HOTKEY} 停止 · Esc 取消`, notice: "" });
    try {
      const wav = await captureUtterance(signal, { waitMs, onLevel: rms => this.panel.level(rms),
        onSpeech: () => this.set({ text: "正在听…" }) });
      if (signal.aborted) return;
      if (!wav) {
        if (waitMs === FIRST_WAIT_MS) this.fail("没有听到声音：可以在“插件 › AI OS”页面做一次麦克风测试");
        else this.set({ phase: "idle" });
        return;
      }
      this.set({ phase: "transcribing", text: "正在把语音转成文字…", hint: "Esc 取消" });
      const speech = this.speech();
      if (!speech) throw new Error(NEED_VOICE_INPUT);
      const result = await speech.transcribe({ audioBase64: base64(wav) }, signal);
      if (signal.aborted) return;
      if (!result.ok) throw new Error(result.error?.message || NEED_VOICE_INPUT);
      const text = result.value.text.trim();
      if (!text) { this.fail("没有听清，请再说一次"); return; }
      this.target.inputActions.setDraft(text);
      this.target.inputActions.submit();
      this.awaitingReply = true;
      this.set({ phase: "waiting", text: `“${text}”`, hint: "正在操作电脑，完成后会语音回复 · Esc 不再朗读" });
    } catch (error) {
      if (!signal.aborted) this.fail(describeError(error));
    }
  }

  async respond(reply) {
    const signal = this.begin();
    const spoken = toSpeech(reply);
    this.set({ phase: "speaking", text: spoken, hint: `${HOTKEY} 打断并接着说 · Esc 结束` });
    await speak(spoken, signal);
    if (!signal.aborted) void this.listen(FOLLOW_UP_WAIT_MS);
  }

  onKey(event) {
    if (event.key === HOTKEY && !event.repeat && this.target) { event.preventDefault(); this.toggle(); }
    else if (event.key === "Escape" && this.state.phase !== "idle") this.cancel();
  }

  dispose() { clearTimeout(this.errorTimer); this.abort?.abort(); this.unwatch(); this.panel.dispose(); }
}

// ---------- React views ----------

function useController(controller) {
  return React.useSyncExternalStore(listener => controller.subscribe(listener), () => controller.getSnapshot());
}

function WhaleIcon({ size, mono }) {
  return h("span", { style: { display: "inline-flex", lineHeight: 0 }, dangerouslySetInnerHTML: { __html: whaleSvg(size, mono) } });
}

/** Composer button bound to its Session. */
function VoiceButton({ sessionId, inputActions, controller, binding }) {
  const state = useController(controller);
  const target = React.useRef(null);
  React.useEffect(() => {
    target.current = { sessionId, inputActions, binding };
    controller.attach(target.current);
    const current = target.current;
    return () => controller.detach(current);
  }, [sessionId]);
  if (target.current) target.current.inputActions = inputActions;
  const label = state.notice || (state.phase === "idle" ? `${PHASES.idle.title}（${HOTKEY}，全局 Ctrl+Alt+Space）` : PHASES[state.phase].title);
  return h(ui.Tooltip, { label, side: "top", portal: true },
    h("span", { style: { display: "inline-flex" } },
      h(ui.Button, {
        size: "sm", className: "aios-trigger", "data-phase": state.phase, "aria-label": label,
        "aria-pressed": state.phase !== "idle",
        onMouseDown: event => event.preventDefault(),
        onClick: () => controller.toggle(),
      }, h(WhaleIcon, { size: 22, mono: true }))));
}

const card = { border: "1px solid rgba(127,127,127,.22)", borderRadius: 14, padding: "14px 16px" };

function Check({ ok, title, detail, action }) {
  return h("div", { style: { display: "flex", gap: 10, alignItems: "flex-start", padding: "6px 0" } },
    h("span", { style: { flex: "none", width: 18, height: 18, marginTop: 1, borderRadius: 9, display: "grid", placeItems: "center",
      fontSize: 12, color: "#fff", background: ok === null ? "#94a3b8" : ok ? "#16a34a" : "#dc2626" } }, ok === null ? "…" : ok ? "✓" : "!"),
    h("div", { style: { flex: 1 } }, h("div", { style: { fontWeight: 600 } }, title), h("div", { style: { opacity: .7, fontSize: 13 } }, detail)),
    action || null);
}

const DESKTOP_SERVER = "ai-os";
/** The manager keys the entry by the patch row id (`mcp-ai-os`) on some versions and by the server name on others. */
const DESKTOP_MATCH = name => typeof name === "string" && (name === DESKTOP_SERVER || name.endsWith(DESKTOP_SERVER));

/** True when a row belongs to this plugin: the `mcp-ai-os` client row or the `ai-os-voice` row. */
function isAiOsRow(row) {
  const text = `${row.entryId || ""} ${row.moduleName || ""}`;
  return /ai[-_]os/i.test(text);
}

/** True for the row that starts the Python desktop server (as opposed to the browser-side voice UI). */
function isDesktopServerRow(row) {
  const text = `${row.entryId || ""} ${row.moduleName || ""}`;
  return isAiOsRow(row) && /mcp/i.test(text);
}

/** Reads the plugin inventory, which owns the rows a bundle patch inserts (the MCP server among them). */
async function readInventory(inventory) {
  try {
    const result = await inventory.list();
    const snapshot = result && typeof result === "object" && "ok" in result
      ? (result.ok ? result.value : null)
      : result;
    if (!snapshot || typeof snapshot !== "object") return null;
    const rows = Array.isArray(snapshot.entries) ? snapshot.entries.slice() : [];
    for (const preset of snapshot.agentPresets || []) {
      if (Array.isArray(preset.rows)) rows.push(...preset.rows);
    }
    return rows;
  } catch { return null; }
}

/** Combines both sources into the row shown on the plugin page. */
async function probeDesktop(mcp, inventory) {
  const manager = await readDesktop(mcp);
  if (manager) return manager;
  if (!inventory || typeof inventory.list !== "function") {
    return { ok: false, detail: "无法读取桌面工具状态：请启用 dsh-mcp-manager 与 dsh-host-plugin-inventory" };
  }
  const entries = await readInventory(inventory);
  if (!entries) return { ok: null, detail: "读取桌面工具状态失败，稍后重试" };
  const desktop = entries.filter(isDesktopServerRow);
  if (!desktop.length) return { ok: false,
    detail: "桌面工具服务没有加载：请确认已安装 dsh-ai-os 并重启 DeepSeek Harness" };
  const failed = desktop.find(row => row.fiberPhase === "failed");
  if (failed) return { ok: false,
    detail: `${failed.entryId} 启动失败：${failed.diagnostic || "没有诊断信息"}；请先运行 pip install ai-os-desktop` };
  const off = desktop.find(row => row.enabled === false || row.enabled === "conditional");
  if (off) return { ok: false, detail: `${off.entryId} 已停用，请重启 DeepSeek Harness` };
  const pending = desktop.find(row => row.fiberPhase !== "active");
  if (pending) return { ok: null, detail: `${pending.entryId} 正在加载（${pending.fiberPhase}）…` };
  return { ok: true, detail: "桌面工具已就绪（点击、输入、开应用、截图）" };
}

/** Reads the desktop server's state from the MCP manager; null means the manager can't tell. */
async function readDesktop(mcp) {
  const timeout = ms => new Promise(r => setTimeout(() => r(null), ms));
  const streamValue = async () => {
    const controller = new AbortController();
    try {
      const stream = await Promise.race([mcp.watch(controller.signal), timeout(4000)]);
      if (!stream) return null;
      for await (const servers of stream) return Array.isArray(servers) ? servers : [];
      return [];
    } catch { return null; }
    finally { controller.abort(); }
  };
  const fromManager = async () => {
    if (!mcp || typeof mcp.watch !== "function") return null;
    const list = await streamValue();
    if (list === null) return null;
    const entry = list.find(item => DESKTOP_MATCH(item.name));
    if (!entry) return null;
    if (!entry.configured) return { ok: false,
      detail: `「${entry.name}」已被移除${entry.status?.result?.cleanupError ? `：${entry.status.result.cleanupError}` : "，重启 DeepSeek Harness 可清理"}` };
    const status = entry.status || {};
    const state = status.state;
    if (state === "connected") return { ok: true, detail: `已连接 ${status.toolCount ?? "?"} 个桌面工具（点击、输入、开应用、截图）` };
    if (state === "connecting" || state === "reconnecting") return { ok: null,
      detail: state === "connecting" ? `正在连接本机 Python 端（第 ${(status.attempt ?? 0) + 1} 次）…` : "连接中断，正在重连…" };
    if (state === "waiting-credentials") return { ok: false, detail: status.lastError };
    if (state === "disabled") return { ok: false, detail: "桌面工具服务已被停用，请重启 DeepSeek Harness" };
    if (state === "failed") return { ok: false, detail:
      `${status.lastError || status.result?.cleanupError || `连接失败（${status.reason || "unknown"}）`}；请先运行 pip install ai-os-desktop` };
    if (state === "closed") return { ok: false,
      detail: status.result?.cleanupError || "桌面工具服务已关闭，请重启 DeepSeek Harness" };
    return { ok: null, detail: `状态：${state || "未知"}` };
  };
  return (await fromManager()) || null;
}

/** Plugin page panel: brand header, readiness checks and a microphone test. */
function SetupPanel({ speech, mcp, inventory }) {
  const [catalog, setCatalog] = React.useState(undefined);
  const [reason, setReason] = React.useState("");
  const [desktop, setDesktop] = React.useState({ ok: null, detail: "检查中…" });
  const [test, setTest] = React.useState({ phase: "idle", level: 0, peak: 0, text: "" });
  React.useEffect(() => {
    let alive = true, timer;
    const check = async () => {
      const value = await probeDesktop(mcp(), inventory());
      if (!alive) return;
      setDesktop(value);
      if (value.ok === null) timer = setTimeout(check, 2500);
    };
    void check();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  React.useEffect(() => {
    let alive = true, timer;
    const check = async () => {
      const remote = speech();
      let value = null, why = "";
      if (!remote) why = speech.lastError() || "语音服务尚未连接";
      else {
        try {
          const result = await remote.catalog();
          if (result && result.ok) value = result.value; else why = result?.error?.message || "读取失败";
        } catch (error) { why = String(error?.message || error); }
      }
      if (!alive) return;
      setCatalog(value);
      setReason(why);
      if (!value) timer = setTimeout(check, 2000);
    };
    void check();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const provider = catalog && catalog.providers.find(p => p.id === catalog.selection.providerId);
  const phase = provider && provider.preparation.phase;
  const speechReady = catalog === undefined ? null : !!provider && ["ready", "standby", "waking"].includes(phase);
  const speechDetail = speechReady === null ? "检查中…" : speechReady ? `已就绪：${provider.name}`
    : provider ? `${provider.name}：模型未就绪（${phase}），请在“语音输入”插件页完成准备` : `${NEED_VOICE_INPUT}（${reason}）`;

  const runTest = async () => {
    const controller = new AbortController();
    let peak = 0;
    setTest({ phase: "recording", level: 0, peak: 0, text: "" });
    try {
      const wav = await captureUtterance(controller.signal, { fixedMs: 4000,
        onLevel: rms => { peak = Math.max(peak, rms); setTest(t => ({ ...t, level: rms, peak })); } });
      setTest(t => ({ ...t, phase: "transcribing" }));
      const remote = speech();
      if (!remote) throw new Error(NEED_VOICE_INPUT);
      const result = await remote.transcribe({ audioBase64: base64(wav) }, controller.signal);
      if (!result.ok) throw new Error(result.error?.message);
      setTest(t => ({ ...t, phase: "done", text: result.value.text || "（没有识别到文字）" }));
    } catch (error) {
      setTest(t => ({ ...t, phase: "done", text: `出错：${describeError(error)}` }));
    }
  };

  const [previewing, setPreviewing] = React.useState(false);
  const preview = async () => {
    setPreviewing(true);
    try { await speak("你好，我是 AI OS。按 F8 对我说出你想做的事。", new AbortController().signal); }
    finally { setPreviewing(false); }
  };
  const quiet = test.phase === "done" && test.peak < MIN_THRESHOLD * 2;
  return h("div", { style: { display: "grid", gap: 14, margin: "8px 0 16px" } },
    h("div", { style: card },
      h("div", { style: { fontWeight: 700, marginBottom: 4 } }, "运行检查"),
      h(Check, { ok: speechReady, title: "语音识别", detail: speechDetail }),
      h(Check, { ok: typeof speechSynthesis !== "undefined", title: "语音回复",
        detail: chineseVoice() ? `使用系统语音：${chineseVoice().name}` : "使用系统默认语音",
        action: h(ui.Button, { size: "sm", disabled: previewing, onClick: () => void preview() }, previewing ? "朗读中…" : "试听") }),
      h(Check, { ok: desktop.ok, title: "桌面操作",
        detail: desktop.detail })),
    h("div", { style: card },
      h("div", { style: { display: "flex", alignItems: "center", gap: 12 } },
        h("div", { style: { fontWeight: 700 } }, "麦克风测试"),
        h(ui.Button, { size: "sm", disabled: test.phase === "recording" || test.phase === "transcribing", onClick: () => void runTest() },
          test.phase === "recording" ? "正在录音（4 秒）…" : test.phase === "transcribing" ? "识别中…" : "开始测试")),
      h("div", { style: { marginTop: 10, height: 8, borderRadius: 4, background: "rgba(127,127,127,.18)", overflow: "hidden" } },
        h("div", { style: { height: "100%", width: `${Math.min(100, Math.sqrt(test.level) * 500)}%`, background: BLUE, transition: "width .08s" } })),
      h("div", { style: { marginTop: 8, fontSize: 13, opacity: .8 } },
        test.phase === "idle" ? "点击后说一句话，确认音量条在动、识别结果正确。"
          : test.phase === "done" ? (quiet ? `几乎没有收到声音（峰值 ${test.peak.toFixed(4)}）：请在 Windows 声音设置里确认默认输入设备并调高音量。识别结果：${test.text}` : `识别结果：${test.text}`)
          : "请说话…")));
}

const inject = ["remote", "slots", "sessions"];

function apply(ctx) {
  let speech = null;
  ctx.inject(["remote.speech"], scope => {
    const remote = scope.remote.speech;
    speech = remote;
    scope.effect(() => () => { if (speech === remote) speech = null; });
  });
  let lastError = "";
  const getSpeech = () => {
    if (speech) return speech;
    try { return ctx.remote.speech || null; }
    catch (error) { lastError = String(error?.message || error); return null; }
  };
  getSpeech.lastError = () => lastError;

  let mcp = null;
  ctx.inject(["remote.mcpManager"], scope => {
    const remote = scope.remote.mcpManager;
    mcp = remote;
    scope.effect(() => () => { if (mcp === remote) mcp = null; });
  });
  const getMcp = () => {
    if (mcp) return mcp;
    try { return ctx.remote.mcpManager || null; }
    catch { return null; }
  };

  let inventory = null;
  ctx.inject(["remote.pluginInventory"], scope => {
    const remote = scope.remote.pluginInventory;
    inventory = remote;
    scope.effect(() => () => { if (inventory === remote) inventory = null; });
  });
  const getInventory = () => {
    if (inventory) return inventory;
    try { return ctx.remote.pluginInventory || null; }
    catch { return null; }
  };

  const style = document.createElement("style");
  style.id = "aios-voice-style";
  style.textContent = STYLE;
  document.head.append(style);
  const controller = new VoiceController(getSpeech);
  const onKey = event => controller.onKey(event);
  document.addEventListener("keydown", onKey, true);
  ctx.effect(() => () => {
    document.removeEventListener("keydown", onKey, true);
    controller.dispose();
    style.remove();
  });

  const deps = { controller, binding: id => ctx.sessions.binding(id) };
  ctx.slots.inject("conversation.input.right", () => ctx.slots.register({
    name: "conversation.input.right", id: "ai-os-voice", order: 50, label: "语音对话", inject: () => deps,
  }, VoiceButton));
  ctx.slots.inject("plugins.bundle.config", () => ctx.slots.register({
    name: "plugins.bundle.config", key: BUNDLE, inject: () => ({ speech: getSpeech, mcp: getMcp, inventory: getInventory }),
  }, SetupPanel));
}

exports.apply = apply;
exports.inject = inject;
return module.exports;
}});

"use strict";
// fugu-chat フロントエンド(素の JS・ビルドなし)。
// 会話は localStorage に保持(更新しても UI 履歴が消えない)。文脈は毎リクエスト全送。
// 集計・コスト・グラフは持たない(dashboard/ の担当)。表示するのは 1 レコード分の実測値のみ。

const LS_KEY = "fugu-chat.conversation.v1";
const els = {
  log: document.getElementById("log"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  form: document.getElementById("composer"),
  provider: document.getElementById("provider"),
  model: document.getElementById("model"),
  preset: document.getElementById("preset"),
  clear: document.getElementById("clear"),
  withtool: document.getElementById("withtool"),
  status: document.getElementById("status"),
};

let CONFIG = null;
let conversation = load(); // [{role, content}]
let conversationId = null;
let busy = false;

function load() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || []; }
  catch { return []; }
}
function save() { localStorage.setItem(LS_KEY, JSON.stringify(conversation)); }

function setStatus(text, cls) {
  els.status.textContent = text;
  els.status.className = "statusbar" + (cls ? " " + cls : "");
}

// ---- 初期化 ----
async function init() {
  try {
    CONFIG = await (await fetch("/api/config")).json();
  } catch (e) {
    setStatus("設定の取得に失敗: " + e, "err");
    return;
  }
  // provider
  for (const name of Object.keys(CONFIG.providers)) {
    const o = document.createElement("option");
    o.value = name; o.textContent = name;
    els.provider.appendChild(o);
  }
  els.provider.value = CONFIG.default_provider;
  els.provider.addEventListener("change", fillModels);
  fillModels();
  // presets
  const presets = CONFIG.system_prompt_presets || {};
  const none = document.createElement("option");
  none.value = ""; none.textContent = "(なし)";
  els.preset.appendChild(none);
  for (const key of Object.keys(presets)) {
    const o = document.createElement("option");
    o.value = key; o.textContent = key;
    els.preset.appendChild(o);
  }
  if (presets.default !== undefined) els.preset.value = "default";

  renderAll();
  setStatus("準備完了");
}

function fillModels() {
  const pc = CONFIG.providers[els.provider.value] || {};
  els.model.innerHTML = "";
  for (const m of pc.models || []) {
    const o = document.createElement("option");
    o.value = m; o.textContent = m;
    els.model.appendChild(o);
  }
  if (pc.default_model) els.model.value = pc.default_model;
}

// ---- 描画 ----
function renderAll() {
  els.log.innerHTML = "";
  for (const m of conversation) addBubble(m.role, m.content, m.meta);
  scroll();
}

function addBubble(role, content, meta) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const r = document.createElement("div");
  r.className = "role"; r.textContent = role === "user" ? "You" : "Fugu";
  const b = document.createElement("div");
  b.className = "bubble"; b.textContent = content || "";
  wrap.appendChild(r); wrap.appendChild(b);
  if (meta) {
    if (meta.measuredHtml) {
      const mm = document.createElement("div");
      mm.className = "measured" + (meta.error ? " err" : "");
      mm.innerHTML = meta.measuredHtml;
      wrap.appendChild(mm);
    }
    if (meta.toolHtml) {
      const t = document.createElement("div");
      t.className = "tools"; t.innerHTML = meta.toolHtml;
      wrap.appendChild(t);
    }
  }
  els.log.appendChild(wrap);
  return { wrap, bubble: b };
}

function scroll() { els.log.scrollTop = els.log.scrollHeight; }

// ---- 実測値 1 行 ----
function fmtMeasured(m) {
  if (!m) return "";
  const s = (x) => (x == null ? "—" : x.toFixed(1) + "s");
  const tok = m.total_tokens == null ? "? tok" : m.total_tokens.toLocaleString() + " tok";
  let ura;
  if (m.orchestration_ratio == null) ura = "裏 不明"; // null と 0 を区別
  else ura = "裏 " + Math.round(m.orchestration_ratio * 100) + "%";
  const ttft = m.ttft_s == null ? "初動 —" : "初動 " + m.ttft_s.toFixed(1) + "s";
  return `<span class="hi">${s(m.elapsed_s)}</span> (${ttft}) / <span class="hi">${tok}</span> — <span class="hi">${ura}</span>`;
}

function fmtToolCalls(calls) {
  if (!calls || !calls.length) return "";
  let html = "<h4>tool_calls(観測のみ・実行しない)</h4>";
  for (const c of calls) {
    const badge = c.arguments_valid
      ? '<span class="args-ok">args OK</span>'
      : '<span class="args-bad">args 壊れ: ' + escapeHtml(c.arguments_error || "") + "</span>";
    const shown = c.arguments_valid
      ? JSON.stringify(c.arguments, null, 2)
      : c.arguments_raw; // 壊れていても生を見せる(握り潰さない)
    html += `<div class="toolcall"><code>${escapeHtml(c.name || "?")}</code> ${badge}`
          + `<pre>${escapeHtml(shown)}</pre></div>`;
  }
  return html;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- 送信 ----
async function send(text) {
  if (busy || !text.trim()) return;
  busy = true; els.send.disabled = true;
  setStatus("送信中…", "busy");

  conversation.push({ role: "user", content: text });
  save();
  addBubble("user", text);

  // messages 組み立て: system プリセット + 会話全体(毎回全送)
  const messages = [];
  const presetKey = els.preset.value;
  if (presetKey && CONFIG.system_prompt_presets[presetKey]) {
    messages.push({ role: "system", content: CONFIG.system_prompt_presets[presetKey] });
  }
  for (const m of conversation) messages.push({ role: m.role, content: m.content });

  const params = {};
  if (els.withtool.checked) {
    params.tools = [{
      type: "function",
      function: {
        name: "get_weather",
        description: "Get current weather for a city",
        parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
      },
    }];
    params.tool_choice = "auto";
  }

  const body = {
    messages,
    provider: els.provider.value,
    model: els.model.value,
    conversation_id: conversationId,
    params,
  };

  // アシスタントの吹き出しを 1 つ作り、delta で伸ばす
  const view = addBubble("assistant", "");
  let acc = "";
  let toolCalls = [];
  let measured = null;
  let hadError = null;

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      // SSE: イベントは空行区切り。data: 行を拾う。
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
        for (const line of raw.split("\n")) {
          const t = line.trim();
          if (!t.startsWith("data:")) continue;
          const ev = JSON.parse(t.slice(5).trim());
          handleEvent(ev);
        }
      }
    }
  } catch (e) {
    hadError = String(e);
    setStatus("エラー: " + hadError, "err");
  }

  function handleEvent(ev) {
    if (ev.type === "delta") {
      acc += ev.content;
      view.bubble.textContent = acc;
      scroll();
    } else if (ev.type === "tool_partial") {
      toolCalls = ev.tool_calls || [];
    } else if (ev.type === "warning") {
      setStatus("警告: " + ev.message, "err");
    } else if (ev.type === "error") {
      hadError = ev.error;
      setStatus("エラー: " + ev.error, "err");
    } else if (ev.type === "done") {
      if (ev.conversation_id) conversationId = ev.conversation_id;
      if (ev.content) { acc = ev.content; view.bubble.textContent = acc; }
      toolCalls = ev.tool_calls || toolCalls;
      measured = ev.measured;
    }
  }

  // 確定: 実測値と tool_calls を吹き出しに焼き付け、会話に保存
  const measuredHtml = hadError && !measured
    ? '<span class="measured err">失敗: ' + escapeHtml(hadError) + " — レコードは記録済み</span>"
    : fmtMeasured(measured);
  const toolHtml = fmtToolCalls(toolCalls);
  view.wrap.remove();
  const finalMeta = { measuredHtml, toolHtml, error: !!hadError };
  addBubble("assistant", acc || (hadError ? "(応答なし)" : ""), finalMeta);
  conversation.push({ role: "assistant", content: acc, meta: finalMeta });
  save();
  scroll();

  busy = false; els.send.disabled = false;
  if (!hadError) setStatus(measured ? statusLine(measured) : "完了");
}

function statusLine(m) {
  const parts = [];
  if (m.elapsed_s != null) parts.push(m.elapsed_s.toFixed(1) + "s");
  if (m.total_tokens != null) parts.push(m.total_tokens.toLocaleString() + " tok");
  if (m.orchestration_ratio != null) parts.push("裏 " + Math.round(m.orchestration_ratio * 100) + "%");
  return "完了 — " + parts.join(" / ");
}

// ---- イベント ----
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value;
  els.input.value = "";
  send(text);
});
els.input.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    els.form.requestSubmit();
  }
});
els.clear.addEventListener("click", () => {
  if (!confirm("この会話の表示を消します(測定ログ JSONL は残ります)。よろしいですか?")) return;
  conversation = []; conversationId = null; save(); renderAll();
  setStatus("会話をクリアしました(測定ログは保持)");
});

init();

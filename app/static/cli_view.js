/**
 * CLIタブの項目の内容
 *
 * リポジトリのフォルダで実行するClaudeと、開発PCで対話式に実行している時のように会話する。
 * 応答はサーバー側で別途実行し、発言一覧をポーリングして表示する。
 * 画面構成はMR内容と揃え、添付・指示の入力欄・送信ボタン・状態表示・発言一覧の順に並べる。
 * 添付は選択・貼り付けの時点で保存し、送信時にIDで発言に付ける。
 */

// 応答中の発言一覧の取得間隔
const CLI_VIEW_POLL_MS = 1500;

// 発言の種類（core/cli_session.pyのCliMessageRoleと合わせる）
const CLI_MESSAGE_ROLES = {
  user: "user",
  assistant: "assistant",
  tool: "tool",
  toolResult: "tool_result",
  toolError: "tool_error",
  error: "error",
};
// ツールの実行結果で、この行数を超えるものは折りたたんで表示する
const CLI_TOOL_RESULT_FOLD_LINES = 3;
// 対話の状態（core/cli_session.pyのCliSessionStatusと合わせる）
const CLI_SESSION_STATUS = { idle: "idle", running: "running" };

const CLI_VIEW_MESSAGES = {
  running: "Claudeが応答中...",
  rowRunning: "応答中",
  empty: "Claudeへの指示を入力して送信してください。",
  closed: "Closeの項目には送信できません（ReOpenすると送信できます）。",
  placeholder: "Claudeへの指示（Ctrl+Enterで送信）",
  send: "送信",
  sendFailed: "送信に失敗しました",
  interrupt: "中断",
  interruptTitle: "応答中のClaudeを止める（開発PCのEscキー相当）",
  interrupting: "中断しています...",
  interruptFailed: "中断に失敗しました",
  attach: "ファイル添付",
  attachHint: "画像は入力欄に貼り付けても添付できます（S1、S2などのIDで指示から指定できます）",
  uploading: "アップロード中",
  uploadFailed: "添付に失敗しました",
  removeAttachment: "添付を取り消す",
};

// 貼り付けた画像にファイル名が無い場合の名前
const CLI_PASTED_IMAGE_NAME = "pasted-image.png";

// 表示中の対話（item・表示済みの最終発言ID・状態・送信前の添付）
let cliViewState = null;
let cliViewPollTimer = null;

/**
 * CLI一覧の行の状態表示
 */
function cliItemMeta(item) {
  return item.status === CLI_SESSION_STATUS.running ? CLI_VIEW_MESSAGES.rowRunning : "";
}

/**
 * CLIの項目の内容を表示する
 *
 * Closeの項目は送信できないようにする。
 */
function showCliItem(item, container) {
  stopCliViewPolling();
  cliViewState = { item, lastMessageId: 0, status: item.status, pendingAttachments: [] };
  container.innerHTML = `
    <form id="cli-view-form" class="instruction-form cli-view-form">
      <div class="attachment-area">
        <button type="button" id="cli-view-attach" class="subtask-action-button attach-button">${CLI_VIEW_MESSAGES.attach}</button>
        <input type="file" id="cli-view-attach-input" multiple hidden />
        <span id="cli-view-attach-status" class="empty">${CLI_VIEW_MESSAGES.attachHint}</span>
      </div>
      <div id="cli-view-attachments" class="cli-attachments"></div>
      <textarea id="cli-view-input" aria-label="Claudeへの指示" placeholder="${CLI_VIEW_MESSAGES.placeholder}"></textarea>
      <div class="subtask-actions">
        <button type="submit" id="cli-view-send" class="subtask-action-button primary">${CLI_VIEW_MESSAGES.send}</button>
        <button type="button" id="cli-view-interrupt" class="subtask-action-button" title="${CLI_VIEW_MESSAGES.interruptTitle}" hidden>${CLI_VIEW_MESSAGES.interrupt}</button>
      </div>
    </form>
    <p id="cli-view-status" class="title-status repo-item-action-status empty" role="status"></p>
    <div id="cli-view-log" class="cli-log" aria-live="polite"></div>
  `;
  document.getElementById("cli-view-form").addEventListener("submit", onSubmitCliView);
  document.getElementById("cli-view-interrupt").addEventListener("click", onClickCliViewInterrupt);
  document.getElementById("cli-view-input").addEventListener("keydown", onCliViewInputKeydown);
  document.getElementById("cli-view-input").addEventListener("paste", onCliViewInputPaste);
  bindFileChooser("cli-view-attach", "cli-view-attach-input", (files) => uploadCliAttachments(cliViewState, files));
  resetCliViewLog();
  refreshCliView();
}

function hideCliItem() {
  stopCliViewPolling();
  cliViewState = null;
}

function isCliItemOpen(state) {
  return state.item.state === REPO_ITEM_STATES.open;
}

function resetCliViewLog() {
  const log = document.getElementById("cli-view-log");
  log.innerHTML = `<p class="empty cli-log-empty">${CLI_VIEW_MESSAGES.empty}</p>`;
  setCliViewStatus(cliViewState.status);
}

/**
 * 入力欄の内容を送信する
 *
 * 応答中・Closeの項目では送信できない。
 * 送信前の添付は発言と一緒に送り、送信後に添付欄を空にする。
 * 送信後は応答が終わるまで発言一覧を取得し続ける。
 */
async function onSubmitCliView(event) {
  event.preventDefault();
  const state = cliViewState;
  const input = document.getElementById("cli-view-input");
  const text = input.value.trim();
  if (!state || !text || !isCliItemOpen(state) || state.status === CLI_SESSION_STATUS.running) return;
  setCliViewStatus(CLI_SESSION_STATUS.running);
  try {
    await postCliMessage(state.item.id, text, state.pendingAttachments.map((a) => a.id));
    input.value = "";
    state.pendingAttachments = [];
    renderCliPendingAttachments(state);
  } catch (error) {
    setCliViewStatus(CLI_SESSION_STATUS.idle, error.message);
    return;
  }
  await refreshCliView();
}

async function postCliMessage(sessionId, text, attachmentIds) {
  const response = await fetch(`/api/cli-sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, attachment_ids: attachmentIds }),
  });
  if (response.ok) return;
  const body = await response.json().catch(() => ({}));
  throw new Error(`${CLI_VIEW_MESSAGES.sendFailed}: ${body.detail || response.statusText}`);
}

/**
 * 応答中のClaudeを中断する
 *
 * 中断の完了（発言待ちへの戻し）は発言一覧の取得で反映する。
 * 二重に要求しないよう、要求中は中断ボタンを押せなくする。
 */
async function onClickCliViewInterrupt() {
  const state = cliViewState;
  if (!state || state.status !== CLI_SESSION_STATUS.running || state.interrupting) return;
  state.interrupting = true;
  setCliViewStatus(state.status);
  try {
    await postCliInterrupt(state.item.id);
  } catch (error) {
    state.interrupting = false;
    if (state === cliViewState) setCliViewStatus(state.status, error.message);
    return;
  }
  await refreshCliView();
}

async function postCliInterrupt(sessionId) {
  const response = await fetch(`/api/cli-sessions/${sessionId}/interrupt`, { method: "POST" });
  if (response.ok) return;
  const body = await response.json().catch(() => ({}));
  throw new Error(`${CLI_VIEW_MESSAGES.interruptFailed}: ${body.detail || response.statusText}`);
}

/**
 * 未表示の発言を取得して表示する
 *
 * 応答中は一定間隔で取得し直す。
 * 取得に失敗した場合（サーバー再起動中など）も取得し直す。
 */
async function refreshCliView() {
  stopCliViewPolling();
  const state = cliViewState;
  if (!state) return;
  const data = await fetch(`/api/cli-sessions/${state.item.id}?after=${state.lastMessageId}`)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  if (state !== cliViewState) return;
  if (data) applyCliSession(state, data);
  if (!data || data.status === CLI_SESSION_STATUS.running) {
    cliViewPollTimer = setTimeout(refreshCliView, CLI_VIEW_POLL_MS);
  }
}

/**
 * 取得した発言と状態を反映する
 *
 * 一覧の行の状態表示も合わせて更新する。
 */
function applyCliSession(state, data) {
  data.messages.forEach(appendCliMessage);
  if (data.messages.length > 0) state.lastMessageId = data.messages[data.messages.length - 1].id;
  setCliViewStatus(data.status);
  updateRepoItemRow(REPO_ITEM_TABS.cli, { ...state.item, status: data.status });
}

function stopCliViewPolling() {
  clearTimeout(cliViewPollTimer);
  cliViewPollTimer = null;
}

/**
 * 発言を一覧の末尾に追加する
 *
 * Claudeの応答文はMarkdownとして描画し、それ以外はそのままの文字列で表示する。
 */
function appendCliMessage(message) {
  const log = document.getElementById("cli-view-log");
  log.querySelector(".cli-log-empty")?.remove();
  const role = Object.values(CLI_MESSAGE_ROLES).includes(message.role) ? message.role : CLI_MESSAGE_ROLES.assistant;
  const el = isFoldedCliMessage(role, message.content)
    ? createFoldedCliMessage(message.content)
    : document.createElement("div");
  el.className = `cli-message cli-message-${role}`;
  if (role === CLI_MESSAGE_ROLES.assistant) el.appendChild(renderMarkdownFragment(message.content));
  else if (el.tagName !== "DETAILS") el.textContent = message.content;
  const attachments = message.attachments || [];
  if (attachments.length) el.appendChild(renderCliMessageAttachments(cliViewState.item.id, attachments));
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

// 拒否・失敗は目立たせるため折りたたまない
function isFoldedCliMessage(role, content) {
  return role === CLI_MESSAGE_ROLES.toolResult && content.split("\n").length > CLI_TOOL_RESULT_FOLD_LINES;
}

/**
 * 長いツールの実行結果を、先頭行のみ見せて折りたたむ
 *
 * クリックで全体を開く。
 */
function createFoldedCliMessage(content) {
  const [firstLine, ...rest] = content.split("\n");
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = firstLine;
  const body = document.createElement("div");
  body.textContent = rest.join("\n");
  details.append(summary, body);
  return details;
}

/**
 * 発言に添付したファイル名の一覧
 *
 * ファイル名は添付の内容へのリンクとし、別タブで開く。
 */
function renderCliMessageAttachments(sessionId, attachments) {
  const list = document.createElement("div");
  list.className = "cli-attachments";
  list.innerHTML = attachments
    .map((a) => `<a class="cli-attachment" href="${cliAttachmentUrl(sessionId, a.id)}/file" target="_blank" rel="noopener">${renderCliAttachmentLabel(a)}</a>`)
    .join("");
  return list;
}

function renderCliAttachmentLabel(attachment) {
  return `${escapeHtml(attachment.id)}: ${escapeHtml(attachment.filename)}`;
}

function cliAttachmentUrl(sessionId, attachmentId) {
  return `/api/cli-sessions/${sessionId}/attachments/${encodeURIComponent(attachmentId)}`;
}

/**
 * 送信前の添付の一覧を描画する
 *
 * 各添付に取り消しボタンを付ける。
 */
function renderCliPendingAttachments(state) {
  const container = document.getElementById("cli-view-attachments");
  if (!container || state !== cliViewState) return;
  container.innerHTML = state.pendingAttachments
    .map(
      (a) =>
        `<span class="cli-attachment">${renderCliAttachmentLabel(a)}` +
        `<button type="button" class="cli-attachment-remove" data-attachment-id="${escapeHtml(a.id)}"` +
        ` aria-label="${CLI_VIEW_MESSAGES.removeAttachment}" title="${CLI_VIEW_MESSAGES.removeAttachment}">×</button></span>`
    )
    .join("");
  container
    .querySelectorAll(".cli-attachment-remove")
    .forEach((b) => b.addEventListener("click", () => removeCliAttachment(state, b.dataset.attachmentId)));
}

/**
 * 入力欄に貼り付けたファイル（クリップボードの画像など）を添付する
 *
 * ファイルを含まない貼り付けは、通常の文字の貼り付けとする。
 */
function onCliViewInputPaste(event) {
  const files = [...(event.clipboardData?.files || [])];
  if (!files.length || !cliViewState || !isCliItemOpen(cliViewState)) return;
  event.preventDefault();
  const named = files.map((f) => (f.name ? f : new File([f], CLI_PASTED_IMAGE_NAME, { type: f.type })));
  uploadCliAttachments(cliViewState, named);
}

/**
 * ファイルを1件ずつアップロードし、送信前の添付に加える
 *
 * IDの採番順を選択順に揃えるため、並列にせず順に送る。
 * 失敗したファイルは添付欄の横に理由を表示する。
 */
async function uploadCliAttachments(state, files) {
  const statusEl = document.getElementById("cli-view-attach-status");
  const errors = [];
  for (const file of files) {
    statusEl.textContent = `${CLI_VIEW_MESSAGES.uploading}: ${file.name}`;
    try {
      state.pendingAttachments.push(await uploadCliAttachment(state.item.id, file));
    } catch (error) {
      errors.push(`${file.name}: ${error.message}`);
    }
    renderCliPendingAttachments(state);
  }
  if (statusEl.isConnected) {
    statusEl.textContent = errors.length ? `${CLI_VIEW_MESSAGES.uploadFailed}: ${errors.join(" / ")}` : CLI_VIEW_MESSAGES.attachHint;
  }
}

async function uploadCliAttachment(sessionId, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/cli-sessions/${sessionId}/attachments`, { method: "POST", body: form });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || response.statusText);
  return body;
}

/**
 * 送信前の添付を取り消す
 *
 * 保存済みのファイルも削除する。
 */
async function removeCliAttachment(state, attachmentId) {
  await fetch(cliAttachmentUrl(state.item.id, attachmentId), { method: "DELETE" }).catch(() => null);
  state.pendingAttachments = state.pendingAttachments.filter((a) => a.id !== attachmentId);
  renderCliPendingAttachments(state);
}

/**
 * 状態表示と送信・中断の可否を更新する
 *
 * 失敗時は文言を状態表示に出す。
 * Closeの項目は入力欄を読み取り専用にする。
 * 中断ボタンは応答中のみ表示する。
 */
function setCliViewStatus(status, errorText = "") {
  const state = cliViewState;
  if (!state) return;
  state.status = status;
  const open = isCliItemOpen(state);
  const running = status === CLI_SESSION_STATUS.running;
  if (!running) state.interrupting = false;
  const text = errorText || (running ? cliViewRunningText(state) : "") || (open ? "" : CLI_VIEW_MESSAGES.closed);
  document.getElementById("cli-view-status").textContent = text;
  document.getElementById("cli-view-send").disabled = running || !open;
  document.getElementById("cli-view-input").readOnly = !open;
  document.getElementById("cli-view-attach").disabled = !open;
  const interrupt = document.getElementById("cli-view-interrupt");
  interrupt.hidden = !running;
  interrupt.disabled = Boolean(state.interrupting);
}

function cliViewRunningText(state) {
  return state.interrupting ? CLI_VIEW_MESSAGES.interrupting : CLI_VIEW_MESSAGES.running;
}

// Ctrl+Enter（MacはCmd+Enter）で送信し、Enterのみは改行とする
function onCliViewInputKeydown(event) {
  if (event.isComposing || event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  document.getElementById("cli-view-form").requestSubmit();
}

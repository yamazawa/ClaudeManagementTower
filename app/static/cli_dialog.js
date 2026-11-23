/**
 * CLI実行ダイアログ
 *
 * リポジトリのフォルダで実行するClaudeと、開発PCで対話式に実行している時のように会話する。
 * 応答はサーバー側で別途実行し、ダイアログは発言一覧をポーリングして表示する。
 * ダイアログを閉じても会話はリポジトリごとに残し、開き直すと続きから会話できる。
 */

// 応答中の発言一覧の取得間隔
const CLI_DIALOG_POLL_MS = 1500;

// 発言の種類（core/cli_session.pyのCliMessageRoleと合わせる）
const CLI_MESSAGE_ROLES = { user: "user", assistant: "assistant", tool: "tool", error: "error" };
// 対話の状態（core/cli_session.pyのCliSessionStatusと合わせる）
const CLI_SESSION_STATUS = { idle: "idle", running: "running" };

const CLI_DIALOG_MESSAGES = {
  title: (name) => `CLI実行 - ${name}`,
  running: "Claudeが応答中...",
  idle: "",
  empty: "Claudeへの指示を入力して送信してください。",
  createFailed: "会話を開始できませんでした",
  sendFailed: "送信に失敗しました",
};

// リポジトリIDごとの会話ID
const cliSessionIdsByProject = new Map();
// 表示中の会話（projectId・sessionId・表示済みの最終発言ID・状態）
let cliDialogState = null;
let cliDialogPollTimer = null;

/**
 * リポジトリのCLI実行ダイアログを開く
 */
async function openCliDialog(project) {
  cliDialogState = { projectId: project.id, sessionId: null, lastMessageId: 0, status: CLI_SESSION_STATUS.idle };
  document.getElementById("cli-dialog-title").textContent = CLI_DIALOG_MESSAGES.title(project.display_name);
  resetCliDialogLog();
  document.getElementById("cli-dialog").showModal();
  document.getElementById("cli-dialog-input").focus();
  const sessionId = cliSessionIdsByProject.get(project.id);
  if (sessionId === undefined) return;
  cliDialogState.sessionId = sessionId;
  await refreshCliDialog();
}

function resetCliDialogLog() {
  const log = document.getElementById("cli-dialog-log");
  log.innerHTML = "";
  const empty = document.createElement("p");
  empty.className = "empty cli-dialog-empty";
  empty.textContent = CLI_DIALOG_MESSAGES.empty;
  log.appendChild(empty);
  setCliDialogStatus(CLI_SESSION_STATUS.idle);
}

/**
 * 新しい会話を始める
 *
 * 次の送信時に会話を作り直す。
 * 応答中の会話はサーバー側で最後まで実行される。
 */
function startNewCliConversation() {
  if (!cliDialogState) return;
  cliSessionIdsByProject.delete(cliDialogState.projectId);
  cliDialogState = { ...cliDialogState, sessionId: null, lastMessageId: 0 };
  stopCliDialogPolling();
  resetCliDialogLog();
}

function closeCliDialog() {
  stopCliDialogPolling();
  cliDialogState = null;
  document.getElementById("cli-dialog").close();
}

async function ensureCliSession(state) {
  if (state.sessionId !== null) return state.sessionId;
  const response = await fetch("/api/cli-sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId }),
  });
  if (!response.ok) throw new Error(CLI_DIALOG_MESSAGES.createFailed);
  state.sessionId = (await response.json()).id;
  cliSessionIdsByProject.set(state.projectId, state.sessionId);
  return state.sessionId;
}

/**
 * 入力欄の内容を送信する
 *
 * 応答中は送信できない。
 * 送信後は応答が終わるまで発言一覧を取得し続ける。
 */
async function onSubmitCliDialog(event) {
  event.preventDefault();
  const state = cliDialogState;
  const input = document.getElementById("cli-dialog-input");
  const text = input.value.trim();
  if (!state || !text || state.status === CLI_SESSION_STATUS.running) return;
  setCliDialogStatus(CLI_SESSION_STATUS.running);
  try {
    await postCliMessage(await ensureCliSession(state), text);
    input.value = "";
  } catch (error) {
    setCliDialogStatus(CLI_SESSION_STATUS.idle, error.message);
    return;
  }
  await refreshCliDialog();
}

async function postCliMessage(sessionId, text) {
  const response = await fetch(`/api/cli-sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (response.ok) return;
  const body = await response.json().catch(() => ({}));
  throw new Error(`${CLI_DIALOG_MESSAGES.sendFailed}: ${body.detail || response.statusText}`);
}

/**
 * 未表示の発言を取得して表示する
 *
 * 応答中は一定間隔で取得し直す。
 * 取得に失敗した場合（サーバー再起動中など）も取得し直す。
 */
async function refreshCliDialog() {
  stopCliDialogPolling();
  const state = cliDialogState;
  if (!state || state.sessionId === null) return;
  const data = await fetch(`/api/cli-sessions/${state.sessionId}?after=${state.lastMessageId}`)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  if (state !== cliDialogState || state.sessionId === null) return;
  if (data) applyCliSession(state, data);
  if (!data || data.status === CLI_SESSION_STATUS.running) {
    cliDialogPollTimer = setTimeout(refreshCliDialog, CLI_DIALOG_POLL_MS);
  }
}

function applyCliSession(state, data) {
  data.messages.forEach(appendCliMessage);
  if (data.messages.length > 0) state.lastMessageId = data.messages[data.messages.length - 1].id;
  setCliDialogStatus(data.status);
}

function stopCliDialogPolling() {
  clearTimeout(cliDialogPollTimer);
  cliDialogPollTimer = null;
}

function appendCliMessage(message) {
  const log = document.getElementById("cli-dialog-log");
  log.querySelector(".cli-dialog-empty")?.remove();
  const el = document.createElement("div");
  const role = Object.values(CLI_MESSAGE_ROLES).includes(message.role) ? message.role : CLI_MESSAGE_ROLES.assistant;
  el.className = `cli-message cli-message-${role}`;
  el.textContent = message.content;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

/**
 * 状態表示と送信可否を更新する
 *
 * 失敗時は文言を状態表示に出す。
 */
function setCliDialogStatus(status, errorText = "") {
  if (cliDialogState) cliDialogState.status = status;
  const running = status === CLI_SESSION_STATUS.running;
  document.getElementById("cli-dialog-status").textContent = errorText || CLI_DIALOG_MESSAGES[status] || "";
  document.getElementById("cli-dialog-send").disabled = running;
}

// Ctrl+Enter（MacはCmd+Enter）で送信し、Enterのみは改行とする
function onCliDialogInputKeydown(event) {
  if (event.isComposing || event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  document.getElementById("cli-dialog-form").requestSubmit();
}

function setupCliDialog() {
  const dialog = document.getElementById("cli-dialog");
  document.getElementById("cli-dialog-form").addEventListener("submit", onSubmitCliDialog);
  document.getElementById("cli-dialog-input").addEventListener("keydown", onCliDialogInputKeydown);
  document.getElementById("cli-dialog-new").addEventListener("click", startNewCliConversation);
  document.getElementById("cli-dialog-close").addEventListener("click", closeCliDialog);
  // Escキーで閉じた場合も取得を止める
  dialog.addEventListener("close", () => {
    stopCliDialogPolling();
    cliDialogState = null;
  });
}

setupCliDialog();

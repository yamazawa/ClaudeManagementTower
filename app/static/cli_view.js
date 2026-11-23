/**
 * CLIタブの項目の内容
 *
 * リポジトリのフォルダで実行するClaudeと、開発PCで対話式に実行している時のように会話する。
 * 応答はサーバー側で別途実行し、発言一覧をポーリングして表示する。
 * 画面構成はMR内容と揃え、指示の入力欄・送信ボタン・状態表示・発言一覧の順に並べる。
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
};

// 表示中の対話（item・表示済みの最終発言ID・状態）
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
  cliViewState = { item, lastMessageId: 0, status: item.status };
  container.innerHTML = `
    <form id="cli-view-form" class="instruction-form cli-view-form">
      <textarea id="cli-view-input" aria-label="Claudeへの指示" placeholder="${CLI_VIEW_MESSAGES.placeholder}"></textarea>
      <div class="subtask-actions">
        <button type="submit" id="cli-view-send" class="subtask-action-button primary">${CLI_VIEW_MESSAGES.send}</button>
      </div>
    </form>
    <p id="cli-view-status" class="title-status repo-item-action-status empty" role="status"></p>
    <div id="cli-view-log" class="cli-log" aria-live="polite"></div>
  `;
  document.getElementById("cli-view-form").addEventListener("submit", onSubmitCliView);
  document.getElementById("cli-view-input").addEventListener("keydown", onCliViewInputKeydown);
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
    await postCliMessage(state.item.id, text);
    input.value = "";
  } catch (error) {
    setCliViewStatus(CLI_SESSION_STATUS.idle, error.message);
    return;
  }
  await refreshCliView();
}

async function postCliMessage(sessionId, text) {
  const response = await fetch(`/api/cli-sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (response.ok) return;
  const body = await response.json().catch(() => ({}));
  throw new Error(`${CLI_VIEW_MESSAGES.sendFailed}: ${body.detail || response.statusText}`);
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

function appendCliMessage(message) {
  const log = document.getElementById("cli-view-log");
  log.querySelector(".cli-log-empty")?.remove();
  const role = Object.values(CLI_MESSAGE_ROLES).includes(message.role) ? message.role : CLI_MESSAGE_ROLES.assistant;
  const el = isFoldedCliMessage(role, message.content)
    ? createFoldedCliMessage(message.content)
    : document.createElement("div");
  el.className = `cli-message cli-message-${role}`;
  if (el.tagName !== "DETAILS") el.textContent = message.content;
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
 * 状態表示と送信可否を更新する
 *
 * 失敗時は文言を状態表示に出す。
 * Closeの項目は入力欄を読み取り専用にする。
 */
function setCliViewStatus(status, errorText = "") {
  const state = cliViewState;
  if (!state) return;
  state.status = status;
  const open = isCliItemOpen(state);
  const running = status === CLI_SESSION_STATUS.running;
  const text = errorText || (running ? CLI_VIEW_MESSAGES.running : "") || (open ? "" : CLI_VIEW_MESSAGES.closed);
  document.getElementById("cli-view-status").textContent = text;
  document.getElementById("cli-view-send").disabled = running || !open;
  document.getElementById("cli-view-input").readOnly = !open;
}

// Ctrl+Enter（MacはCmd+Enter）で送信し、Enterのみは改行とする
function onCliViewInputKeydown(event) {
  if (event.isComposing || event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  document.getElementById("cli-view-form").requestSubmit();
}

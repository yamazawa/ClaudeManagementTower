/**
 * CLIタブの項目の内容
 *
 * リポジトリのフォルダで実行するClaudeと、開発PCで対話式に実行している時のように会話する。
 * 応答はサーバー側で別途実行し、発言一覧をポーリングして表示する。
 * 画面構成はMR内容と揃え、添付・指示の入力欄・送信ボタン・状態表示・発言一覧の順に並べる。
 * 添付はMR内容と共通の部品を使い、選択・貼り付けの時点で保存する。
 * 送信時は未送信の添付をIDで発言に付ける。
 * 添付の一覧は送信済み・未送信を色分けし、絞り込んで表示する。
 * 範囲外の操作の許可の問い合わせは、状態表示の下に表示して回答を受け付ける。
 * 入力欄の内容は、送信前でも下書きとして項目ごとに保存する。
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
  attachHint: "画像は入力欄に貼り付けても添付できます（S1、S2などのIDで指示から指定できます）",
  attachmentFilter: "表示する添付",
  attachmentUnsent: "未送信",
  attachmentSent: "送信済み",
  attachmentAll: "すべて",
  waitingPermission: "許可の確認待ち（下の内容を確認して許可・拒否してください）",
  permissionTitle: "許可の確認",
  allow: "許可",
  deny: "拒否",
  denyReasonPlaceholder: "拒否する理由（任意・Claudeに伝わります）",
  answerFailed: "回答に失敗しました",
};

// 添付の要素ID
const CLI_ATTACHMENT_IDS = attachmentElementIds("cli-attach");
const CLI_ATTACHMENT_FILTER_ID = "cli-attach-filter";

// 添付の一覧の絞り込み（先頭が既定）
const CLI_ATTACHMENT_FILTERS = [
  { value: "unsent", label: CLI_VIEW_MESSAGES.attachmentUnsent, match: (a) => !a.sent },
  { value: "sent", label: CLI_VIEW_MESSAGES.attachmentSent, match: (a) => a.sent },
  { value: "all", label: CLI_VIEW_MESSAGES.attachmentAll, match: () => true },
];
// 添付の一覧の行の色分けのクラス
const CLI_ATTACHMENT_ROW_CLASSES = { sent: "attachment-row-sent", unsent: "attachment-row-unsent" };

// 表示中の対話（item・表示済みの最終発言ID・状態・添付の部品）
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
  cliViewState = { item, lastMessageId: 0, status: item.status, attachmentForm: null, permissionRequests: [] };
  container.innerHTML = `
    <form id="cli-view-form" class="instruction-form cli-view-form">
      ${renderAttachmentFormHtml(CLI_ATTACHMENT_IDS, { hint: CLI_VIEW_MESSAGES.attachHint, extraHtml: renderCliAttachmentFilter() })}
      <textarea id="cli-view-input" aria-label="Claudeへの指示" placeholder="${CLI_VIEW_MESSAGES.placeholder}"></textarea>
      <div class="subtask-actions">
        <button type="submit" id="cli-view-send" class="subtask-action-button primary">${CLI_VIEW_MESSAGES.send}</button>
        <button type="button" id="cli-view-interrupt" class="subtask-action-button" title="${CLI_VIEW_MESSAGES.interruptTitle}" hidden>${CLI_VIEW_MESSAGES.interrupt}</button>
      </div>
    </form>
    <p id="cli-view-status" class="title-status repo-item-action-status empty" role="status"></p>
    <div id="cli-view-permissions"></div>
    <div id="cli-view-log" class="cli-log" aria-live="polite"></div>
  `;
  document.getElementById("cli-view-form").addEventListener("submit", onSubmitCliView);
  document.getElementById("cli-view-interrupt").addEventListener("click", onClickCliViewInterrupt);
  document.getElementById("cli-view-input").addEventListener("keydown", onCliViewInputKeydown);
  bindDraft(document.getElementById("cli-view-input"), draftKey(DRAFT_KINDS.cli, item.id));
  cliViewState.attachmentForm = setupCliAttachmentForm(item.id);
  resetCliViewLog();
  refreshCliView();
}

/**
 * 添付ボタン・添付ファイル一覧の初期化
 *
 * 一覧は絞り込みの選択に合う添付を表示し、送信済み・未送信で色を分ける。
 * 送信済みの添付は発言から参照されるため削除できない。
 */
function setupCliAttachmentForm(sessionId) {
  const filter = document.getElementById(CLI_ATTACHMENT_FILTER_ID);
  const form = setupAttachmentForm({
    apiUrl: `/api/cli-sessions/${sessionId}/attachments`,
    ids: CLI_ATTACHMENT_IDS,
    hint: CLI_VIEW_MESSAGES.attachHint,
    pasteTarget: document.getElementById("cli-view-input"),
    isShown: (a) => CLI_ATTACHMENT_FILTERS.find((f) => f.value === filter.value).match(a),
    rowClass: (a) => (a.sent ? CLI_ATTACHMENT_ROW_CLASSES.sent : CLI_ATTACHMENT_ROW_CLASSES.unsent),
    canDelete: (a) => !a.sent,
  });
  filter.addEventListener("change", () => form.render());
  return form;
}

function renderCliAttachmentFilter() {
  const options = CLI_ATTACHMENT_FILTERS.map((f) => `<option value="${f.value}">${f.label}</option>`).join("");
  return `<select id="${CLI_ATTACHMENT_FILTER_ID}" class="cli-attachment-filter" aria-label="${CLI_VIEW_MESSAGES.attachmentFilter}">${options}</select>`;
}

function unsentCliAttachmentIds(state) {
  return state.attachmentForm.attachments.filter((a) => !a.sent).map((a) => a.id);
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
 * 未送信の添付は発言と一緒に送り、送信後に添付の一覧を読み直す。
 * 送信できたら入力欄と下書きを空にする。
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
    await postCliMessage(state.item.id, text, unsentCliAttachmentIds(state));
    input.value = "";
    clearDraft(draftKey(DRAFT_KINDS.cli, state.item.id));
    state.attachmentForm.reload();
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
  state.permissionRequests = data.permission_requests || [];
  renderCliPermissionRequests(state);
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
  state.attachmentForm?.setDisabled(!open);
  const interrupt = document.getElementById("cli-view-interrupt");
  interrupt.hidden = !running;
  interrupt.disabled = Boolean(state.interrupting);
}

function cliViewRunningText(state) {
  if (state.interrupting) return CLI_VIEW_MESSAGES.interrupting;
  return state.permissionRequests.length ? CLI_VIEW_MESSAGES.waitingPermission : CLI_VIEW_MESSAGES.running;
}

/**
 * 回答待ちの許可の問い合わせを表示する
 *
 * 入力中の拒否理由を消さないよう、表示済みの問い合わせは描画し直さない。
 * 回答済み・中断済みになった問い合わせは取り除く。
 */
function renderCliPermissionRequests(state) {
  const container = document.getElementById("cli-view-permissions");
  if (!container || state !== cliViewState) return;
  const ids = new Set(state.permissionRequests.map((r) => String(r.id)));
  container.querySelectorAll(".cli-permission").forEach((el) => {
    if (!ids.has(el.dataset.requestId)) el.remove();
  });
  const shown = new Set([...container.children].map((el) => el.dataset.requestId));
  state.permissionRequests
    .filter((r) => !shown.has(String(r.id)))
    .forEach((r) => container.appendChild(createCliPermissionCard(state, r)));
}

/**
 * 1件の問い合わせの内容と、許可・拒否のボタン
 *
 * 拒否時は入力した理由をClaudeに伝える。
 */
function createCliPermissionCard(state, request) {
  const card = document.createElement("div");
  card.className = "cli-permission";
  card.dataset.requestId = String(request.id);
  card.innerHTML = `
    <p class="cli-permission-reason">${CLI_VIEW_MESSAGES.permissionTitle}: ${escapeHtml(request.reason)}</p>
    <pre class="cli-permission-tool">${escapeHtml(request.tool)}</pre>
    <input type="text" class="cli-permission-deny-reason" placeholder="${CLI_VIEW_MESSAGES.denyReasonPlaceholder}" />
    <div class="subtask-actions">
      <button type="button" class="subtask-action-button primary" data-allow="true">${CLI_VIEW_MESSAGES.allow}</button>
      <button type="button" class="subtask-action-button" data-allow="false">${CLI_VIEW_MESSAGES.deny}</button>
    </div>
    <p class="title-status empty" role="status"></p>
  `;
  card.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => answerCliPermission(state, request.id, card, b.dataset.allow === "true"))
  );
  return card;
}

/**
 * 問い合わせに回答する
 *
 * 二重に回答しないよう、回答中はボタンを押せなくする。
 * 回答後は発言一覧を取得し直して、問い合わせの表示を更新する。
 */
async function answerCliPermission(state, requestId, card, allow) {
  const buttons = card.querySelectorAll("button");
  buttons.forEach((b) => (b.disabled = true));
  const reason = card.querySelector(".cli-permission-deny-reason").value;
  try {
    await postCliPermission(state.item.id, requestId, allow, reason);
  } catch (error) {
    buttons.forEach((b) => (b.disabled = false));
    card.querySelector("[role=status]").textContent = error.message;
    return;
  }
  if (state === cliViewState) await refreshCliView();
}

async function postCliPermission(sessionId, requestId, allow, reason) {
  const response = await fetch(`/api/cli-sessions/${sessionId}/permissions/${requestId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allow, reason }),
  });
  if (response.ok) return;
  const body = await response.json().catch(() => ({}));
  throw new Error(`${CLI_VIEW_MESSAGES.answerFailed}: ${body.detail || response.statusText}`);
}

// Ctrl+Enter（MacはCmd+Enter）で送信し、Enterのみは改行とする
function onCliViewInputKeydown(event) {
  if (event.isComposing || event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  document.getElementById("cli-view-form").requestSubmit();
}

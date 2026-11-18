let currentProjectId = null;
let currentProjectName = null;
let currentIssueNumber = null;
let currentIssueState = null;
let currentIssueTitle = null;
let currentSubtasks = [];
let currentSelectedSubtaskId = null;

const LIFECYCLE_LABELS = {
  draft: "Draft",
  in_review: "レビュー中",
  merged: "マージ済",
  closed: "クローズ（未マージ）",
};

// MR一覧フィルタの値ごとに表示対象のlifecycle_stateを定義する（nullは全件表示）
const SUBTASK_FILTER_STATES = {
  unresolved: ["draft", "in_review"],
  draft: ["draft"],
  in_review: ["in_review"],
  merged: ["merged"],
  all: null,
};

// Issue一覧のMR数で解決済とみなす状態と、数えない状態（マージされずクローズ）
const MR_COUNT_RESOLVED_STATE = "merged";
const MR_COUNT_EXCLUDED_STATE = "closed";

// MR状態の自動更新間隔（サーバー側のPR同期間隔と合わせて10秒以内に反映させる）
const SUBTASK_POLL_MS = 3000;

// MR名は「Issue名」+区切り文字+「MR固有名」とする（core/mr_naming.pyと合わせる）
const MR_NAME_SEPARATOR = "ー";
const MR_TITLE_WARNING_CLASS = "mr-title-warning";
const MR_TITLE_WARNING_TEXT = `MR名が命名規則（Issue名${MR_NAME_SEPARATOR}MR名）に沿っていません`;

const WORKER_STATE_LABELS = {
  idle: "待機中",
  busy: "実行中",
};

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

/**
 * タイトル要素をクリックでテキストボックス化する
 *
 * Enterまたはフォーカス外れで確定し、Escで取り消す。
 * onSaveは新タイトルを受け取り、失敗時はエラー文言を返す。
 */
function makeTitleEditable(titleEl, statusEl, onSave) {
  titleEl.classList.add("editable-title");
  updateTitleTooltip(titleEl);
  titleEl.addEventListener("click", () => {
    const original = titleEl.textContent;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "title-input";
    input.value = original;
    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let finished = false;
    const finish = async (save) => {
      if (finished) return;
      finished = true;
      const title = input.value.trim();
      input.replaceWith(titleEl);
      if (!save || !title || title === original) return;

      titleEl.textContent = title;
      updateTitleTooltip(titleEl);
      statusEl.textContent = "更新中...";
      const error = await onSave(title);
      if (error) titleEl.textContent = original;
      updateTitleTooltip(titleEl);
      statusEl.textContent = error ? `失敗しました: ${error}` : "更新しました";
    };
    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (event.key === "Enter") finish(true);
      if (event.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
  });
}

/**
 * タイトルのツールチップ更新
 *
 * 省略表示されても読めるよう、全文と編集方法を表示する。
 */
function updateTitleTooltip(titleEl) {
  const warning = titleEl.classList.contains(MR_TITLE_WARNING_CLASS)
    ? `\n${MR_TITLE_WARNING_TEXT}`
    : "";
  titleEl.title = `${titleEl.textContent}${warning}\n（クリックしてタイトルを編集）`;
}

/**
 * MR名からMR固有名を取り出す
 *
 * 命名規則に沿っていない場合はnullを返す。
 */
function splitMrTitle(mrTitle) {
  const prefix = `${currentIssueTitle}${MR_NAME_SEPARATOR}`;
  if (currentIssueTitle === null || !mrTitle.startsWith(prefix)) return null;
  return mrTitle.slice(prefix.length) || null;
}

/**
 * MR名の表示要素
 *
 * 命名規則に沿う場合はMR固有名のみ、沿わない場合は全体を警告表示する。
 */
function renderMrTitle(s, { id = "", className = "" } = {}) {
  const suffix = splitMrTitle(s.title);
  const warning = suffix === null;
  const classes = [className, warning ? MR_TITLE_WARNING_CLASS : ""].filter(Boolean).join(" ");
  const idAttr = id ? ` id="${id}"` : "";
  const tooltip = warning ? `${s.title}\n${MR_TITLE_WARNING_TEXT}` : s.title;
  return (
    `<span${idAttr} class="${classes}" title="${escapeAttr(tooltip)}">` +
    `${escapeHtml(warning ? s.title : suffix)}</span>`
  );
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;");
}

async function patchTitle(url, title) {
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const body = await response.json().catch(() => ({}));
  if (response.ok) return { error: null, body };
  return { error: body.detail || response.statusText, body };
}

async function pollWorkers() {
  try {
    await renderWorkers();
  } catch (error) {
    // サーバー再起動中などで取得に失敗しても監視を継続する
    document.getElementById("worker-status").textContent = "ワーカー状況を取得できません";
  }
  setTimeout(pollWorkers, 3000);
}

async function renderWorkers() {
  const workers = await fetch("/api/workers").then((r) => r.json());
  const aliveWorkers = workers.filter((w) => !w.is_stale);
  const busyCount = aliveWorkers.filter((w) => w.state === "busy").length;

  const items = workers
    .map((w) => {
      if (w.is_stale) {
        return `<span class="worker-pill worker-offline">オフライン</span>`;
      }
      const label = WORKER_STATE_LABELS[w.state] || w.state;
      const job = w.current_job_id ? `job #${w.current_job_id}` : "";
      return `<span class="worker-pill worker-${w.state}">${label} ${job}</span>`;
    })
    .join("");
  document.getElementById("worker-status").innerHTML =
    `<span class="worker-summary">実行中 ${busyCount} / ${aliveWorkers.length}</span>${items}`;
}

const SYSTEM_BUTTON_IDS = [
  "start-workers-button",
  "cleanup-workers-button",
  "restart-server-button",
  "sync-self-button",
];
const SERVER_RESTART_POLL_MS = 1000;
const SERVER_RESTART_TIMEOUT_MS = 60000;
const SYNC_SELF_POLL_MS = 3000;
const SYNC_SELF_TIMEOUT_MS = 30 * 60 * 1000;

function setSystemStatus(text) {
  document.getElementById("system-status").textContent = text;
}

function setSystemButtonsDisabled(disabled) {
  SYSTEM_BUTTON_IDS.forEach((id) => (document.getElementById(id).disabled = disabled));
}

async function postSystem(path) {
  const response = await fetch(`/api/system/${path}`, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

async function runSystemAction(action) {
  setSystemButtonsDisabled(true);
  try {
    await action();
  } catch (error) {
    setSystemStatus(`失敗しました: ${error.message}`);
  } finally {
    setSystemButtonsDisabled(false);
  }
}

async function onClickStartWorkers() {
  setSystemStatus("ワーカー起動を依頼中...");
  await postSystem("start-workers");
  setSystemStatus("ワーカー起動を依頼しました");
}

async function onClickCleanupWorkers() {
  setSystemStatus("掃除中...");
  const result = await postSystem("cleanup-workers");
  setSystemStatus(
    `掃除しました（ワーカー${result.removed_worker_ids.length}件削除・` +
      `ジョブ${result.recovered_job_ids.length}件を要確認化）`
  );
  await renderWorkers();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchBootId() {
  try {
    const response = await fetch("/health");
    return response.ok ? (await response.json()).boot_id : null;
  } catch (error) {
    return null;
  }
}

async function waitForNewBootId(oldBootId) {
  const deadline = Date.now() + SERVER_RESTART_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(SERVER_RESTART_POLL_MS);
    const bootId = await fetchBootId();
    if (bootId && bootId !== oldBootId) {
      return true;
    }
  }
  return false;
}

async function onClickRestartServer() {
  if (!confirm("サーバーを再起動しますか？")) {
    return;
  }
  setSystemStatus("再起動中...");
  const oldBootId = await fetchBootId();
  await postSystem("restart-server");
  const restarted = await waitForNewBootId(oldBootId);
  setSystemStatus(restarted ? "再起動しました" : "再起動を確認できませんでした");
}

async function fetchSyncSelfResult() {
  try {
    const response = await fetch("/api/system/sync-self");
    return response.ok ? await response.json() : null;
  } catch (error) {
    return null;
  }
}

async function waitForSyncSelfResult() {
  const deadline = Date.now() + SYNC_SELF_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(SYNC_SELF_POLL_MS);
    const result = await fetchSyncSelfResult();
    if (result && result.status !== "running") {
      return result;
    }
  }
  return null;
}

function describeSyncSelfResult(result) {
  const toLabels = (numbers) => numbers.map((n) => `#${n}`).join("、");
  const failedNumbers = result.failed_prs.map((pr) => pr.number);
  if (result.merged_pr_numbers.length === 0 && failedNumbers.length === 0) {
    return "マージ対象のPRはありませんでした。";
  }
  const texts = [];
  if (result.merged_pr_numbers.length > 0) {
    texts.push(`PR ${toLabels(result.merged_pr_numbers)} をマージしました。`);
  }
  if (failedNumbers.length > 0) {
    const reasons = result.failed_prs.map((pr) => `#${pr.number}: ${pr.error}`).join(" / ");
    texts.push(`PR ${toLabels(failedNumbers)} はマージできませんでした（${reasons}）。`);
  }
  return texts.join(" ");
}

async function onClickSyncSelf() {
  if (
    !confirm(
      "Claude管理塔リポジトリで、Draftが外れている全PRをマージし、" +
        "最新化してサーバー・ワーカーを再起動します。" +
        "競合しているPRはClaudeが競合を解消してからマージします。よろしいですか？"
    )
  ) {
    return;
  }
  setSystemStatus("マージ・最新化中...（競合解消を含むため時間がかかる場合があります）");
  const oldBootId = await fetchBootId();
  await postSystem("sync-self");
  const result = await waitForSyncSelfResult();
  if (result === null) {
    setSystemStatus("マージ・最新化の完了を確認できませんでした");
    return;
  }
  if (result.status === "failed") {
    setSystemStatus(`マージ・最新化に失敗しました: ${result.error}`);
    return;
  }
  const mergedText = describeSyncSelfResult(result);
  setSystemStatus(`${mergedText} 再起動中...`);
  const restarted = await waitForNewBootId(oldBootId);
  setSystemStatus(`${mergedText} ${restarted ? "再起動しました" : "再起動を確認できませんでした"}`);
}

function bindSystemControls() {
  const handlers = {
    "start-workers-button": onClickStartWorkers,
    "cleanup-workers-button": onClickCleanupWorkers,
    "restart-server-button": onClickRestartServer,
    "sync-self-button": onClickSyncSelf,
  };
  Object.entries(handlers).forEach(([id, handler]) =>
    document.getElementById(id).addEventListener("click", () => runSystemAction(handler))
  );
}

function renderBreadcrumb() {
  const el = document.getElementById("breadcrumb");
  if (currentProjectId === null) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <a href="#" id="breadcrumb-projects">リポジトリ一覧</a>
    <span class="breadcrumb-sep">&rsaquo;</span>
    <span class="breadcrumb-current">${escapeHtml(currentProjectName)}</span>
  `;
  document
    .getElementById("breadcrumb-projects")
    .addEventListener("click", (event) => {
      event.preventDefault();
      showProjectList();
    });
}

function showProjectList() {
  currentProjectId = null;
  currentProjectName = null;
  currentIssueNumber = null;
  document.getElementById("project-view").hidden = false;
  document.getElementById("issue-view").hidden = true;
  clearIssueDetail();
  renderBreadcrumb();
}

// 別リポジトリへ切り替えた際に前のIssue表示が残らないよう、Issue未選択の表示に戻す
function clearIssueDetail() {
  document.getElementById("issue-heading").textContent = "Issue";
  document.getElementById("subtask-list-body").innerHTML =
    '<p class="empty">左の一覧からIssueを選択してください。</p>';
  document.getElementById("subtask-panel").hidden = true;
  renderSubtaskDetail(null);
}

async function init() {
  const projects = await fetch("/api/projects").then((r) => r.json());
  const listEl = document.getElementById("project-list-items");
  listEl.innerHTML = "";
  if (projects.length === 0) {
    listEl.innerHTML = '<li class="empty">リポジトリが登録されていません。</li>';
  } else {
    for (const project of projects) {
      const li = document.createElement("li");
      li.className = "project-item";
      li.innerHTML = `<span class="project-name">${escapeHtml(project.display_name)}</span><span class="project-branch">${project.default_branch}</span>`;
      li.addEventListener("click", () => selectProject(project));
      listEl.appendChild(li);
    }
  }
  pollWorkers();
  pollSubtaskStates();
}

async function selectProject(project) {
  currentProjectId = project.id;
  currentProjectName = project.display_name;
  document.getElementById("project-view").hidden = true;
  document.getElementById("issue-view").hidden = false;
  renderBreadcrumb();
  renderRepoHeading(project);
  await loadIssues();
}

/**
 * リポジトリ見出しの表示
 *
 * 「Repo #番号 表示名」とし、番号部分はGitHubのリポジトリページへのリンクにする。
 */
function renderRepoHeading(project) {
  const label = project.repo_number ? `Repo #${project.repo_number}` : "Repo";
  document.getElementById("repo-heading").innerHTML =
    `${renderTitleNumber(label, project.repo_url)}<span id="repo-title">${escapeHtml(project.display_name)}</span>`;
}

async function loadIssues() {
  const state = document.getElementById("issue-filter").value;
  const issues = await fetch(
    `/api/projects/${currentProjectId}/issues?state=${encodeURIComponent(state)}`
  ).then((r) => r.json());
  const listEl = document.getElementById("issue-list-items");
  listEl.innerHTML = "";
  if (issues.length === 0) {
    listEl.innerHTML = '<li class="empty">Issueがありません。</li>';
    return;
  }
  issues.forEach((issue) => listEl.appendChild(renderIssueItem(issue)));
}

/**
 * Issue一覧の1行
 *
 * 見出しと同様に番号リンク・1行省略のタイトル・閉じるボタンを並べる。
 * リンクとボタンのクリックではIssueを選択しない。
 */
function renderIssueItem(issue) {
  const li = document.createElement("li");
  li.className = "issue-item";
  li.classList.toggle("active", issue.number === currentIssueNumber);
  li.dataset.number = issue.number;
  li.dataset.state = issue.state;
  li.innerHTML = `
    ${renderTitleNumber(`Issue #${issue.number}`, issue.url)}
    <span class="issue-item-title" title="${escapeAttr(issue.title)}">${escapeHtml(issue.title)}</span>
    <span class="issue-item-meta" title="解決済MR数 / MR総数"></span>
    <button type="button" class="title-action-button issue-item-toggle"></button>
  `;
  updateIssueItemCounts(li, issue.mr_counts);
  li.addEventListener("click", () => selectIssue(issue.number));
  li.querySelector(".title-number").addEventListener("click", (e) => e.stopPropagation());
  const button = li.querySelector(".issue-item-toggle");
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleIssue(issue.number, li.dataset.state === "OPEN", button);
  });
  return li;
}

/**
 * Issue一覧の行のMR数と閉じるボタンを更新する
 */
function updateIssueItemCounts(li, counts) {
  li.querySelector(".issue-item-meta").textContent = `${counts.resolved}/${counts.total}`;
  applyIssueToggleState(li.querySelector(".issue-item-toggle"), li.dataset.state === "OPEN", counts);
}

function filterSubtasks(subtasks) {
  const states = SUBTASK_FILTER_STATES[document.getElementById("subtask-filter").value];
  return states ? subtasks.filter((s) => states.includes(s.lifecycle_state)) : subtasks;
}

function renderSubtaskList() {
  const container = document.getElementById("subtask-list-container");
  if (!container) return;
  const subtasks = filterSubtasks(currentSubtasks);
  container.innerHTML =
    subtasks.length === 0
      ? '<p class="empty">該当するMRはありません。</p>'
      : `<ul id="subtask-list-items">${subtasks.map(renderSubtaskRow).join("")}</ul>`;
  container.querySelectorAll(".subtask-row").forEach((row) => {
    row.addEventListener("click", () => selectSubtask(Number(row.dataset.subtaskId)));
    row.querySelector(".title-number").addEventListener("click", (e) => e.stopPropagation());
  });
  highlightSelectedSubtaskRow();
  updateIssueToggleButton();
}

/**
 * POST操作の実行
 *
 * 成功時は応答本文、失敗時はエラー文言を返す。
 */
async function postAction(url) {
  const response = await fetch(url, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  return response.ok ? { body } : { error: body.detail || response.statusText };
}

/**
 * Issueの閉じる・再開ボタンの表示を切り替える
 *
 * クローズ済の場合は再開ボタンにする。
 * マージ済MRが1個以上で未解決MRが無い場合はプライマリ色にする。
 * 未解決MRが残る場合はクローズできないため無効化する。
 * 見出しと一覧の行で共通に使う。
 */
function applyIssueToggleState(button, isOpen, counts) {
  const hasUnresolved = counts.unresolved > 0;
  button.textContent = isOpen ? "閉じる" : "再開";
  button.classList.toggle("primary", isOpen && counts.resolved > 0 && !hasUnresolved);
  button.disabled = isOpen && hasUnresolved;
  button.title = button.disabled ? "未解決のMRがあるため閉じられません" : "";
}

function updateIssueToggleButton() {
  const button = document.getElementById("issue-toggle-button");
  if (!button) return;
  applyIssueToggleState(button, currentIssueState === "OPEN", countMrs(currentSubtasks));
}

function onClickIssueToggle() {
  const button = document.getElementById("issue-toggle-button");
  toggleIssue(currentIssueNumber, currentIssueState === "OPEN", button);
}

/**
 * Issueを閉じる・再開する
 *
 * 見出し・一覧のどちらのボタンからも呼ぶ。
 * 表示中Issueの場合は見出しに結果を表示し、それ以外は失敗時のみ通知する。
 * 成否に関わらず一覧を再取得してボタンの状態を戻す。
 */
async function toggleIssue(number, isOpen, button) {
  const verb = isOpen ? "閉じ" : "再開し";
  if (!confirm(`Issue #${number} を${verb}ますか？`)) return;
  const isCurrent = number === currentIssueNumber;
  const statusEl = isCurrent ? document.getElementById("issue-close-status") : null;
  button.disabled = true;
  if (statusEl) statusEl.textContent = "更新中...";
  const { body, error } = await postAction(
    `/api/projects/${currentProjectId}/issues/${number}/${isOpen ? "close" : "reopen"}`
  );
  if (!error && number === currentIssueNumber) currentIssueState = body.state;
  updateIssueToggleButton();
  const message = error ? `失敗しました: ${error}` : `Issueを${verb}ました`;
  if (statusEl) statusEl.textContent = message;
  else if (error) alert(message);
  await loadIssues();
}

/**
 * Issue名の保存
 *
 * サーバー側で紐づくMR名も書き換わるため、MR一覧を再取得する。
 * MR名の書き換えに失敗したMRがあれば件数を表示する。
 */
async function saveIssueTitle(number, title) {
  const { error, body } = await patchTitle(
    `/api/projects/${currentProjectId}/issues/${number}`,
    title
  );
  if (error) return error;
  const itemTitle = document.querySelector(
    `.issue-item[data-number="${number}"] .issue-item-title`
  );
  if (itemTitle) {
    itemTitle.textContent = title;
    itemTitle.title = title;
  }
  currentIssueTitle = title;
  const failedCount = (body.failed_subtasks || []).length;
  document.getElementById("issue-rename-status").textContent =
    failedCount > 0 ? `MR名の書き換えに${failedCount}件失敗しました` : "";
  await refreshSubtaskStates().catch(() => {});
  return null;
}

/**
 * MR名の保存
 *
 * 編集対象はMR固有名のみ。保存後は命名規則に沿うため警告表示を外す。
 */
async function saveSubtaskTitle(subtaskId, suffix) {
  const { error } = await patchTitle(`/api/subtasks/${subtaskId}`, suffix);
  if (error) return error;
  document.getElementById("subtask-title")?.classList.remove(MR_TITLE_WARNING_CLASS);
  await refreshSubtaskStates().catch(() => {});
  return null;
}

/**
 * MR一覧の1行
 *
 * Issue一覧と同様に番号リンク・1行省略のタイトル・状態を並べる。
 * リンクのクリックではMRを選択しない。
 */
function renderSubtaskRow(s) {
  return `
    <li class="subtask-row" data-subtask-id="${s.id}">
      ${renderSubtaskNumber(s)}
      ${renderMrTitle(s, { className: "subtask-row-title" })}
      ${renderSubtaskState(s)}
    </li>
  `;
}

/**
 * MRの状態表示
 *
 * 一覧の行と詳細の見出しで共通に使う。
 */
function renderSubtaskState(s) {
  const label = LIFECYCLE_LABELS[s.lifecycle_state] || s.lifecycle_state;
  return `<span class="subtask-state">${label}</span>`;
}

function highlightSelectedSubtaskRow() {
  document
    .querySelectorAll(".subtask-row")
    .forEach((row) =>
      row.classList.toggle("active", Number(row.dataset.subtaskId) === currentSelectedSubtaskId)
    );
}

async function selectIssue(number) {
  currentIssueNumber = number;
  currentSelectedSubtaskId = null;
  document
    .querySelectorAll(".issue-item")
    .forEach((el) => el.classList.toggle("active", Number(el.dataset.number) === number));

  await refreshIssueDetail();
  renderSubtaskDetail(null);
}

/**
 * 見出しの番号表示
 *
 * URLがある場合はGitHubを開くリンクにする。
 */
function renderTitleNumber(label, url) {
  if (!url) return `<span class="title-number">${label}</span>`;
  return `<a class="title-number" href="${url}" target="_blank" rel="noopener" title="GitHubで開く">${label}</a>`;
}

async function refreshIssueDetail() {
  const issue = await fetch(
    `/api/projects/${currentProjectId}/issues/${currentIssueNumber}`
  ).then((r) => r.json());
  currentSubtasks = issue.subtasks;
  currentIssueTitle = issue.title;
  updateIssueMrCounts(issue.number, issue.subtasks);

  document.getElementById("issue-heading").innerHTML =
    `${renderTitleNumber(`Issue #${issue.number}`, issue.url)}<span id="issue-title">${escapeHtml(issue.title)}</span>` +
    `<button type="button" id="issue-toggle-button" class="title-action-button"></button>`;
  document.getElementById("subtask-list-body").innerHTML = `
    <p id="issue-title-status" class="title-status empty"></p>
    <p id="issue-rename-status" class="title-status empty"></p>
    <p id="issue-close-status" class="title-status empty"></p>
  `;
  currentIssueState = issue.state;
  document.getElementById("issue-toggle-button").addEventListener("click", onClickIssueToggle);
  resetSubtaskForm();
  document.getElementById("subtask-panel").hidden = false;

  makeTitleEditable(
    document.getElementById("issue-title"),
    document.getElementById("issue-title-status"),
    (title) => saveIssueTitle(issue.number, title)
  );
  renderSubtaskList();
}

/* MR作成フォームの初期化

フォームはIssue切り替え後も使い回すため、入力値と状態表示を初期状態に戻す。
*/
function resetSubtaskForm() {
  const form = document.getElementById("subtask-form");
  form.reset();
  form.querySelector("button").disabled = false;
  document.getElementById("subtask-form-status").textContent = "";
}

function selectSubtask(subtaskId) {
  currentSelectedSubtaskId = subtaskId;
  highlightSelectedSubtaskRow();
  const subtask = currentSubtasks.find((s) => s.id === subtaskId) || null;
  renderSubtaskDetail(subtask);
}

/**
 * MR見出しの番号表示
 *
 * PR作成前は番号が無いため「MR」のみ表示する。
 */
function renderSubtaskNumber(s) {
  const label = s.github_pr_number ? `MR #${s.github_pr_number}` : "MR";
  return renderTitleNumber(label, s.pr_url);
}

function renderSubtaskDetail(s) {
  const el = document.getElementById("subtask-detail-body");
  const heading = document.getElementById("subtask-heading");
  if (!s) {
    heading.textContent = "MR";
    el.innerHTML = '<p class="empty">左の一覧からMRを選択してください。</p>';
    return;
  }

  heading.innerHTML =
    `${renderSubtaskNumber(s)}${renderMrTitle(s, { id: "subtask-title" })}${renderSubtaskState(s)}` +
    `<button type="button" id="subtask-toggle-button" class="title-action-button"></button>`;
  el.innerHTML = `
    <p id="subtask-title-status" class="title-status empty"></p>
    <p id="subtask-close-status" class="title-status empty"></p>
    <form class="instruction-form" data-subtask-id="${s.id}">
      <textarea id="instruction-${s.id}" name="instruction" aria-label="指示内容" placeholder="Claudeへの指示内容を入力してください">${escapeHtml(s.instruction)}</textarea>
      <button type="submit">実行する</button>
    </form>
    <p class="job-status empty" data-subtask-id="${s.id}"></p>
    <iframe class="report-frame" sandbox="" data-subtask-id="${s.id}" hidden></iframe>
  `;

  document.querySelector(".instruction-form").addEventListener("submit", onSubmitInstructionForm);
  document
    .getElementById("subtask-toggle-button")
    .addEventListener("click", () => onClickSubtaskToggle(s.id));
  updateSubtaskToggleButton(s);
  makeTitleEditable(
    document.getElementById("subtask-title"),
    document.getElementById("subtask-title-status"),
    (title) => saveSubtaskTitle(s.id, title)
  );

  restoreJobState(s);
}

function restoreJobState(s) {
  const job = s.latest_job;
  if (!job) {
    return;
  }

  const statusEl = document.querySelector(`.job-status[data-subtask-id="${s.id}"]`);
  statusEl.textContent = `状態: ${job.status}`;

  if (job.status === "queued" || job.status === "running") {
    const button = document.querySelector(`.instruction-form[data-subtask-id="${s.id}"] button`);
    button.disabled = true;
    pollJob(job.id, s.id, button);
    return;
  }

  if (job.status === "succeeded" && job.has_report) {
    showReport(job.id, s.id);
  }
}

async function pollSubtaskStates() {
  try {
    if (!document.hidden) await refreshSubtaskStates();
  } catch (error) {
    // サーバー再起動中などで取得に失敗しても自動更新を継続する
  }
  setTimeout(pollSubtaskStates, SUBTASK_POLL_MS);
}

/**
 * 表示中IssueのMR一覧の状態を再取得して反映する
 *
 * 変化があった場合のみ、一覧と詳細ペインの状態表示を更新する。
 * 入力中の指示内容などを消さないよう、詳細ペイン全体は再描画しない。
 */
async function refreshSubtaskStates() {
  const projectId = currentProjectId;
  const issueNumber = currentIssueNumber;
  if (projectId === null || issueNumber === null) return;
  const subtasks = await fetch(
    `/api/projects/${projectId}/issues/${issueNumber}/subtasks`
  ).then((r) => r.json());
  if (projectId !== currentProjectId || issueNumber !== currentIssueNumber) return;
  if (JSON.stringify(subtasks) === JSON.stringify(currentSubtasks)) return;

  currentSubtasks = subtasks;
  renderSubtaskList();
  updateIssueMrCounts(issueNumber, subtasks);
  refreshSelectedSubtaskState();
}

/**
 * 選択中MRの状態表示を更新する
 *
 * 見出しの番号・状態と閉じる/再開ボタンのみ差し替える。
 */
function refreshSelectedSubtaskState() {
  const selected = currentSubtasks.find((s) => s.id === currentSelectedSubtaskId);
  if (!selected) return;
  const stateEl = document.querySelector("#subtask-heading .subtask-state");
  if (stateEl) stateEl.outerHTML = renderSubtaskState(selected);
  const numberEl = document.querySelector("#subtask-heading .title-number");
  if (numberEl) numberEl.outerHTML = renderSubtaskNumber(selected);
  updateSubtaskToggleButton(selected);
}

/**
 * MRの閉じる・再開ボタンの表示を切り替える
 *
 * クローズ済の場合は再開ボタンにする。
 * マージ済のMRは閉じる・再開できないため非表示にする。
 */
function updateSubtaskToggleButton(s) {
  const button = document.getElementById("subtask-toggle-button");
  if (!button) return;
  button.hidden = s.lifecycle_state === "merged";
  button.disabled = false;
  button.textContent = s.lifecycle_state === "closed" ? "再開" : "閉じる";
}

async function onClickSubtaskToggle(subtaskId) {
  const subtask = currentSubtasks.find((s) => s.id === subtaskId);
  if (!subtask) return;
  const isClosed = subtask.lifecycle_state === "closed";
  const verb = isClosed ? "再開し" : "閉じ";
  if (!confirm(`MR「${subtask.title}」を${verb}ますか？`)) return;
  const button = document.getElementById("subtask-toggle-button");
  const statusEl = document.getElementById("subtask-close-status");
  button.disabled = true;
  statusEl.textContent = "更新中...";
  const { body, error } = await postAction(
    `/api/subtasks/${subtaskId}/${isClosed ? "reopen" : "close"}`
  );
  if (!error) subtask.lifecycle_state = body.lifecycle_state;
  updateIssueMrCounts(currentIssueNumber, currentSubtasks);
  renderSubtaskList();
  if (currentSelectedSubtaskId === subtaskId) refreshSelectedSubtaskState();
  if (statusEl.isConnected) {
    statusEl.textContent = error ? `失敗しました: ${error}` : `MRを${verb}ました`;
  }
}

/**
 * Issue一覧のMR数を更新する
 *
 * Issue一覧をGitHubから再取得せず、表示中IssueのMR状態から数え直す。
 * 集計方法はIssue一覧APIと合わせる。
 */
function updateIssueMrCounts(issueNumber, subtasks) {
  const li = document.querySelector(`.issue-item[data-number="${issueNumber}"]`);
  if (li) updateIssueItemCounts(li, countMrs(subtasks));
}

/**
 * 解決済MR数・未解決MR数・MR総数を数える
 *
 * 集計方法はIssue一覧APIのmr_countsと合わせる。
 */
function countMrs(subtasks) {
  const counted = subtasks.filter((s) => s.lifecycle_state !== MR_COUNT_EXCLUDED_STATE);
  const countIn = (states) => counted.filter((s) => states.includes(s.lifecycle_state)).length;
  return {
    resolved: countIn([MR_COUNT_RESOLVED_STATE]),
    unresolved: countIn(SUBTASK_FILTER_STATES.unresolved),
    total: counted.length,
  };
}

async function onSubmitIssueForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("issue-create-status");
  const title = form.title.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const response = await fetch(`/api/projects/${currentProjectId}/issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });

  form.querySelector("button").disabled = false;

  if (!response.ok) {
    const error = await response.json();
    statusEl.textContent = `失敗しました: ${error.detail}`;
    return;
  }

  form.reset();
  statusEl.textContent = "作成しました";
  await loadIssues();
}

async function onSubmitSubtaskForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("subtask-form-status");
  const title = form.title.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const response = await fetch("/api/subtasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: currentProjectId,
      github_issue_number: currentIssueNumber,
      title,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    statusEl.textContent = `失敗しました: ${error.detail}`;
    form.querySelector("button").disabled = false;
    return;
  }

  await selectIssue(currentIssueNumber);
}

async function startExecution(subtaskId, instruction, button) {
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  button.disabled = true;
  statusEl.textContent = "実行待ち...";

  const body = instruction ? JSON.stringify({ instruction }) : undefined;
  const { job_id: jobId } = await fetch(`/api/subtasks/${subtaskId}/execute`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body,
  }).then((r) => r.json());

  pollJob(jobId, subtaskId, button);
}

async function onSubmitInstructionForm(event) {
  event.preventDefault();
  const form = event.target;
  const subtaskId = form.dataset.subtaskId;
  const instruction = form.instruction.value;
  if (!instruction) {
    return;
  }
  const button = form.querySelector("button");
  await startExecution(subtaskId, instruction, button);
}

async function pollJob(jobId, subtaskId, button) {
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  const job = await fetch(`/api/jobs/${jobId}`).then((r) => r.json());
  statusEl.textContent = `状態: ${job.status}`;

  if (job.status === "queued" || job.status === "running") {
    setTimeout(() => pollJob(jobId, subtaskId, button), 3000);
    return;
  }

  if (job.status === "succeeded") {
    // refreshIssueDetailが詳細ペインの選択状態を消すため、再描画してから選択し直す
    await refreshIssueDetail();
    selectSubtask(Number(subtaskId));
    await showReport(jobId, subtaskId);
  } else {
    button.disabled = false;
  }
}

async function showReport(jobId, subtaskId) {
  const frame = document.querySelector(`.report-frame[data-subtask-id="${subtaskId}"]`);
  const response = await fetch(`/api/jobs/${jobId}/report`);
  if (!response.ok) {
    return;
  }
  // iframeにURLを直接読み込ませる（レポート応答のCSPヘッダーを効かせるため）
  frame.src = `/api/jobs/${jobId}/report`;
  frame.hidden = false;
}

document.getElementById("issue-create-form").addEventListener("submit", onSubmitIssueForm);
document.getElementById("issue-filter").addEventListener("change", loadIssues);
document.getElementById("subtask-filter").addEventListener("change", renderSubtaskList);
document.getElementById("subtask-form").addEventListener("submit", onSubmitSubtaskForm);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshSubtaskStates().catch(() => {});
});
bindSystemControls();

init();

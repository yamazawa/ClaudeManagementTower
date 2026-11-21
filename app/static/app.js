let currentProjectId = null;
let currentIssueNumber = null;
let currentIssueState = null;
let currentIssueTitle = null;
let currentSubtasks = [];
let currentSelectedSubtaskId = null;
// Issue作成に続くMR自動作成の対象Issue番号（実行中はそのIssueにMRを追加作成させない）
let autoMrCreatingIssueNumber = null;

// MRのlifecycle_state（core/lifecycle.pyと合わせる）
const LIFECYCLE = {
  draft: "draft",
  resolved: "resolved",
  merged: "merged",
  deployed: "deployed",
  canceled: "canceled",
};

// MRの表示ステータス（core/mr_status.pyと合わせる）
// Resolving・Merging・Deployingは保存せず、lifecycle_stateと実行中の処理から導出する
const MR_STATUS = {
  draft: "draft",
  resolving: "resolving",
  resolved: "resolved",
  merging: "merging",
  merged: "merged",
  deploying: "deploying",
  deployed: "deployed",
  canceled: "canceled",
};

const MR_STATUS_LABELS = {
  [MR_STATUS.draft]: "Draft",
  [MR_STATUS.resolving]: "Resolving",
  [MR_STATUS.resolved]: "Resolved",
  [MR_STATUS.merging]: "Merging",
  [MR_STATUS.merged]: "Merged",
  [MR_STATUS.deploying]: "Deploying",
  [MR_STATUS.deployed]: "Deployed",
  [MR_STATUS.canceled]: "Canceled",
};

// ステータス表示のツールチップ
const MR_STATUS_TOOLTIPS = {
  [MR_STATUS.resolving]: "実装中",
  [MR_STATUS.merging]: "マージ中",
  [MR_STATUS.deploying]: "デプロイ中",
};

// ヘッダーのMRステータスフィルタのボタン（表示順）
// 遷移中のステータスは矢印で表し、showCountがfalseのボタンは件数を表示しない
const MR_STATUS_FILTER_BUTTONS = [
  { status: MR_STATUS.draft, label: "Draft" },
  { status: MR_STATUS.resolving, label: "→" },
  { status: MR_STATUS.resolved, label: "Resolved" },
  { status: MR_STATUS.merging, label: "→" },
  { status: MR_STATUS.merged, label: "Merged" },
  { status: MR_STATUS.deploying, label: "→" },
  { status: MR_STATUS.deployed, label: "Deployed", showCount: false },
];
const MR_STATUS_FILTER_CLEAR_LABEL = "クリア";
const MR_STATUS_FILTER_TOOLTIP = "のMRで絞り込み（数字は全リポジトリのMR数）";
const MR_STATUS_FILTER_CLEAR_TOOLTIP = "ステータスでの絞り込みを解除";
const MR_STATUS_POLL_MS = 3000;

// MR一覧フィルタの値ごとに表示対象のlifecycle_stateを定義する
// 未解決はDraft〜Merging、解決済はMerged〜Deployedを表示する
const SUBTASK_FILTER_STATES = {
  unresolved: [LIFECYCLE.draft, LIFECYCLE.resolved],
  solved: [LIFECYCLE.merged, LIFECYCLE.deployed],
};

// MRの状態ごとの操作ボタン（primaryはプライマリ色で表示する）
const SUBTASK_ACTIONS = {
  [LIFECYCLE.draft]: [
    { action: "execute", label: "実装", primary: true },
    { action: "cancel", label: "Cancel" },
  ],
  [LIFECYCLE.resolved]: [
    { action: "merge", label: "Merge", primary: true },
    { action: "execute", label: "再実装" },
    { action: "cancel", label: "Cancel" },
  ],
  [LIFECYCLE.merged]: [],
  [LIFECYCLE.deployed]: [],
  [LIFECYCLE.canceled]: [{ action: "reopen", label: "ReOpen" }],
};

// 状態を変える操作ごとのAPIパスと表示文言
const SUBTASK_STATE_ACTIONS = {
  cancel: {
    path: "close",
    confirm: "をCancel（マージせずクローズ）しますか？",
    progress: "Cancel中...",
    done: "MRをCancelしました",
  },
  reopen: {
    path: "reopen",
    confirm: "をReOpenしますか？",
    progress: "ReOpen中...",
    done: "MRをReOpenしました",
  },
  merge: {
    path: "merge",
    confirm: "をマージしますか？マージは1件ずつ順に行い、競合している場合はClaudeが競合を解消してからマージします。",
    progress: "マージ待ちに登録中...",
    done: "マージ待ちに登録しました（進捗はヘッダーで確認できます）",
  },
};

// マージ待ち行列の状態（core/merge_queue.pyと合わせる）
const MERGE_STATUS = {
  queued: "queued",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
};
const MERGE_STATUS_LABELS = {
  [MERGE_STATUS.queued]: "マージ待ち",
  [MERGE_STATUS.running]: "マージ中",
  [MERGE_STATUS.succeeded]: "マージ済",
  [MERGE_STATUS.failed]: "マージ失敗",
};
const MERGE_POLL_MS = 3000;

function isMergeActive(merge) {
  return !!merge && [MERGE_STATUS.queued, MERGE_STATUS.running].includes(merge.status);
}

// 実行中とみなすジョブの状態（実行中はMRの操作ボタンを無効化する）
const ACTIVE_JOB_STATUSES = ["queued", "running"];

// 操作中（API応答待ち・実装の実行中）のMRのID
const busySubtaskIds = new Set();
// 監視中のジョブID
const pollingJobIds = new Set();
const JOB_POLL_MS = 3000;

// Issue一覧のMR数で解決済とみなす状態と、数えない状態（マージされずクローズ）
const MR_COUNT_RESOLVED_STATES = [LIFECYCLE.merged, LIFECYCLE.deployed];
const MR_COUNT_EXCLUDED_STATE = LIFECYCLE.canceled;
// 作成直後のIssue（Open）が表示対象となるIssue一覧のフィルタの値
const ISSUE_FILTERS_SHOWING_NEW_ISSUE = ["open"];
// Issue一覧APIで指定できるIssueの状態（app/routes/projects.pyと合わせる）
const ISSUE_STATES = ["open", "closed"];

// MR状態の自動更新間隔（サーバー側のPR同期間隔と合わせて10秒以内に反映させる）
const SUBTASK_POLL_MS = 3000;

// MR名は「Issue名」+区切り文字+「MR固有名」とする（core/mr_naming.pyと合わせる）
const MR_NAME_SEPARATOR = "ー";
const MR_TITLE_WARNING_CLASS = "mr-title-warning";
const MR_TITLE_WARNING_TEXT = `MR名が命名規則（Issue名${MR_NAME_SEPARATOR}MR名）に沿っていません`;

// 縦長表示（ペインを縦1列に並べる画面幅）の判定（style.cssのメディアクエリと合わせる）
const PORTRAIT_MEDIA_QUERY = "(max-width: 680px)";

// 開閉するペインのID
const SECTION_IDS = {
  projects: "project-list",
  repo: "issue-list",
  issue: "subtask-list",
  mr: "subtask-detail",
};

const WORKER_STATE_LABELS = {
  idle: "待機中",
  busy: "実行中",
};

/**
 * ペインの開閉状態を切り替える
 *
 * 閉じたペインは見出し行のみ表示する。
 */
function setSectionExpanded(sectionId, expanded) {
  const section = document.getElementById(sectionId);
  section.classList.toggle("collapsed", !expanded);
  section.querySelector(".expander").setAttribute("aria-expanded", String(expanded));
}

/**
 * 縦長表示の場合のみ、ペインを自動で開閉する
 *
 * 横長表示では全ペインが並ぶため、利用者の開閉操作のみに従う。
 */
function autoSetSectionExpanded(sectionId, expanded) {
  if (isPortrait()) setSectionExpanded(sectionId, expanded);
}

function isPortrait() {
  return window.matchMedia(PORTRAIT_MEDIA_QUERY).matches;
}

function isSectionExpanded(sectionId) {
  return !document.getElementById(sectionId).classList.contains("collapsed");
}

/**
 * 表示中のIssueがMR自動作成中か
 *
 * 意図せずMRを2個作らないよう、該当IssueではMR作成ボタンを無効化する。
 */
function isCurrentIssueAutoMrCreating() {
  return currentIssueNumber !== null && currentIssueNumber === autoMrCreatingIssueNumber;
}

/**
 * MR自動作成の対象Issueの切り替え
 *
 * 表示中のIssueが対象の場合は、MR作成ボタンの有効状態も更新する。
 */
function setAutoMrCreatingIssue(issueNumber) {
  autoMrCreatingIssueNumber = issueNumber;
  document.querySelector("#subtask-form button").disabled = isCurrentIssueAutoMrCreating();
}

/**
 * エキスパンダの初期化
 *
 * 縦長表示では、親項目が未選択で表示内容が無いペインを閉じておく。
 */
function setupExpanders() {
  document.querySelectorAll("section .expander").forEach((button) => {
    const section = button.closest("section");
    button.addEventListener("click", () => setSectionExpanded(section.id, !isSectionExpanded(section.id)));
  });
  [SECTION_IDS.repo, SECTION_IDS.issue, SECTION_IDS.mr].forEach((id) => autoSetSectionExpanded(id, false));
}

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

async function pollMerges() {
  try {
    await renderMerges();
  } catch (error) {
    // サーバー再起動中などで取得に失敗しても監視を継続する
    document.getElementById("merge-status").textContent = "マージ状況を取得できません";
  }
  setTimeout(pollMerges, MERGE_POLL_MS);
}

/**
 * ヘッダーのマージ状況を描画する
 *
 * マージ中のMRと、マージ待ちのMRを処理順に表示する。
 */
async function renderMerges() {
  const merges = await fetch("/api/merges").then((r) => r.json());
  const runningCount = merges.filter((m) => m.status === MERGE_STATUS.running).length;
  const queuedCount = merges.length - runningCount;
  const items = merges.map(renderMergePill).join("");
  document.getElementById("merge-status").innerHTML =
    `<span class="worker-summary">マージ中 ${runningCount} / 待ち ${queuedCount}</span>${items}`;
}

function renderMergePill(m) {
  const label = MERGE_STATUS_LABELS[m.status] || m.status;
  const pr = m.github_pr_number ? `MR #${m.github_pr_number}` : "MR";
  const statusClass = m.status === MERGE_STATUS.running ? "merge-running" : "";
  const text = `${label} ${pr} ${m.title}`;
  return `<span class="worker-pill merge-pill ${statusClass}" title="${escapeAttr(text)}">${escapeHtml(text)}</span>`;
}

// ヘッダーのMRステータスフィルタで選択中の表示ステータス
const selectedMrStatuses = new Set();
// 全リポジトリのMRステータス集計（/api/mr-statusesの応答）
// projectsはリポジトリID→Issue番号→ステータス別MR数とする
let mrStatusSummary = { counts: {}, projects: {} };
// Issue一覧に表示中の絞り込み結果（変化した場合のみIssue一覧を再取得する）
let lastMatchedIssueKey = "";

/**
 * ヘッダーのMRステータスフィルタの初期化
 *
 * ボタンは1度だけ作り、件数と選択状態はupdateMrStatusFilterButtonsで更新する。
 */
function setupMrStatusFilter() {
  const container = document.getElementById("mr-status-filter");
  container.innerHTML =
    MR_STATUS_FILTER_BUTTONS.map(renderMrStatusFilterButton).join("") +
    `<button type="button" id="mr-status-filter-clear" class="mr-status-filter-button"` +
    ` title="${MR_STATUS_FILTER_CLEAR_TOOLTIP}">${MR_STATUS_FILTER_CLEAR_LABEL}</button>`;
  container
    .querySelectorAll("[data-status]")
    .forEach((b) => b.addEventListener("click", () => toggleMrStatusFilter(b.dataset.status)));
  document.getElementById("mr-status-filter-clear").addEventListener("click", clearMrStatusFilter);
  updateMrStatusFilterButtons();
}

function renderMrStatusFilterButton(def) {
  const tooltip = `${MR_STATUS_LABELS[def.status]}${MR_STATUS_FILTER_TOOLTIP}`;
  return (
    `<button type="button" class="mr-status-filter-button" data-status="${def.status}"` +
    ` aria-pressed="false" title="${escapeAttr(tooltip)}">${def.label}` +
    `<span class="mr-status-filter-count"></span></button>`
  );
}

/**
 * MRステータスフィルタのボタンの件数・選択状態を更新する
 *
 * 未選択の場合はクリアボタンを無効化する。
 */
function updateMrStatusFilterButtons() {
  MR_STATUS_FILTER_BUTTONS.forEach((def) => {
    const button = document.querySelector(`#mr-status-filter [data-status="${def.status}"]`);
    button.setAttribute("aria-pressed", String(selectedMrStatuses.has(def.status)));
    const count = mrStatusSummary.counts[def.status] ?? 0;
    button.querySelector(".mr-status-filter-count").textContent = def.showCount === false ? "" : ` ${count}`;
  });
  document.getElementById("mr-status-filter-clear").disabled = selectedMrStatuses.size === 0;
}

function toggleMrStatusFilter(status) {
  if (selectedMrStatuses.has(status)) selectedMrStatuses.delete(status);
  else selectedMrStatuses.add(status);
  onMrStatusFilterChanged();
}

function clearMrStatusFilter() {
  selectedMrStatuses.clear();
  onMrStatusFilterChanged();
}

function isMrStatusFilterActive() {
  return selectedMrStatuses.size > 0;
}

/**
 * MRステータスフィルタの選択変更をIssue一覧・MR一覧に反映する
 *
 * 選択中はIssue一覧・MR一覧の既存フィルタを隠す。
 */
function onMrStatusFilterChanged() {
  updateMrStatusFilterButtons();
  const active = isMrStatusFilterActive();
  document.getElementById("issue-filter").hidden = active;
  document.getElementById("subtask-filter").hidden = active;
  if (currentProjectId !== null) loadIssues().catch(() => {});
  renderSubtaskList();
}

/**
 * 表示中リポジトリで、選択中のステータスのMRを持つIssue番号
 */
function matchedIssueNumbers() {
  const byIssue = mrStatusSummary.projects[currentProjectId] || {};
  return Object.entries(byIssue)
    .filter(([, statusCounts]) => Object.keys(statusCounts).some((status) => selectedMrStatuses.has(status)))
    .map(([number]) => Number(number));
}

function matchedIssueKey() {
  if (!isMrStatusFilterActive() || currentProjectId === null) return "";
  return `${currentProjectId}:${matchedIssueNumbers().sort((a, b) => a - b).join(",")}`;
}

/**
 * 集計の更新で絞り込み結果が変わった場合に、Issue一覧を再取得する
 */
function refreshMatchedIssues() {
  if (matchedIssueKey() === lastMatchedIssueKey) return;
  if (isMrStatusFilterActive() && currentProjectId !== null) loadIssues().catch(() => {});
}

async function pollMrStatuses() {
  try {
    if (!document.hidden) await refreshMrStatuses();
  } catch (error) {
    // サーバー再起動中などで取得に失敗しても監視を継続する
  }
  setTimeout(pollMrStatuses, MR_STATUS_POLL_MS);
}

async function refreshMrStatuses() {
  mrStatusSummary = await fetch("/api/mr-statuses").then((r) => r.json());
  updateMrStatusFilterButtons();
  refreshMatchedIssues();
}

// ヘッダーに表示するClaudeのレート制限枠（core/rate_limits.pyと合わせる）
const RATE_LIMIT_WINDOWS = [
  { type: "five_hour", label: "5h" },
  { type: "seven_day", label: "1w" },
];
// 使用率を強調表示する状態（SDKのRateLimitStatusと合わせる）
const RATE_LIMIT_STATUS_CLASSES = {
  allowed_warning: "token-usage-warning",
  rejected: "token-usage-rejected",
};
const RATE_LIMIT_POLL_MS = 10000;
const RATE_LIMIT_UNKNOWN_TEXT = "--";
const RATE_LIMIT_TOOLTIP = "Claudeサブスクリプションの使用率とリセット時刻（取得できない場合は--）";

async function pollRateLimits() {
  try {
    await renderRateLimits();
  } catch (error) {
    // サーバー再起動中などで取得に失敗しても監視を継続する
  }
  setTimeout(pollRateLimits, RATE_LIMIT_POLL_MS);
}

async function renderRateLimits() {
  const limits = await fetch("/api/system/rate-limits").then((r) => r.json());
  const container = document.getElementById("token-usage");
  container.title = RATE_LIMIT_TOOLTIP;
  container.innerHTML = RATE_LIMIT_WINDOWS.map((w) => formatRateLimit(w.label, limits[w.type])).join("");
}

/**
 * レート制限枠1つ分の表示HTMLを作る
 *
 * 使用率が未受信の場合は--と表示する。
 * リセット時刻を受信している場合は併記する。
 */
function formatRateLimit(label, limit) {
  const hasUtilization = limit && limit.utilization != null;
  const percent = hasUtilization ? `${Math.round(limit.utilization * 100)}%` : RATE_LIMIT_UNKNOWN_TEXT;
  const statusClass = (limit && RATE_LIMIT_STATUS_CLASSES[limit.status]) || "";
  const reset = limit && limit.resets_at ? `<span class="token-usage-reset">${formatResetTime(limit.resets_at)}</span>` : "";
  return `<span class="token-usage-item ${statusClass}"><span class="token-usage-label">${label}</span>${percent}${reset}</span>`;
}

function formatResetTime(unixSeconds) {
  const date = new Date(unixSeconds * 1000);
  const hhmm = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? hhmm : `${date.getMonth() + 1}/${date.getDate()} ${hhmm}`;
}

const SERVER_RESTART_POLL_MS = 1000;
const SERVER_RESTART_TIMEOUT_MS = 60000;
const DEPLOY_POLL_MS = 2000;
const DEPLOY_TIMEOUT_MS = 30 * 60 * 1000;
// サーバー再起動を表すデプロイ結果のrestartsの値（core/supervisor_control.pyと合わせる）
const DEPLOY_RESTART_SERVER = "restart_server";
const DEPLOY_DEFINED_TOOLTIP = "リポジトリに定義したデプロイ手順を実行します（デプロイすると動作確認できます）";
const DEPLOY_UNDEFINED_TOOLTIP = "デプロイが定義されていません（.claude-tower/deploy.json）";
// リポジトリ見出しのDeployボタン名
const DEPLOY_BUTTON_LABEL = "Deploy";

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

// 別リポジトリへ切り替えた際に前のIssue表示が残らないよう、Issue未選択の表示に戻す
function clearIssueDetail() {
  document.getElementById("issue-heading").textContent = "Issue";
  document.getElementById("subtask-list-body").innerHTML =
    '<p class="empty">左の一覧からIssueを選択してください。</p>';
  document.getElementById("subtask-panel").hidden = true;
  autoSetSectionExpanded(SECTION_IDS.issue, false);
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
      li.dataset.projectId = project.id;
      li.innerHTML = `<span class="project-name">${escapeHtml(project.display_name)}</span><span class="project-branch">${project.default_branch}</span>`;
      li.addEventListener("click", () => selectProject(project));
      listEl.appendChild(li);
    }
  }
  pollWorkers();
  pollMerges();
  pollRateLimits();
  pollMrStatuses();
  pollSubtaskStates();
}

/**
 * リポジトリの選択
 *
 * 別リポジトリへ切り替えた場合は、前のIssue・MRの表示を消す。
 * 縦長表示ではリポジトリ一覧を閉じ、Issue一覧を開く。
 * Issue一覧に表示中の先頭Issueを自動選択する。
 */
async function selectProject(project) {
  if (project.id !== currentProjectId) {
    currentIssueNumber = null;
    clearIssueDetail();
  }
  currentProjectId = project.id;
  highlightSelectedProject();
  autoSetSectionExpanded(SECTION_IDS.projects, false);
  autoSetSectionExpanded(SECTION_IDS.repo, true);
  document.getElementById("issue-list-placeholder").hidden = true;
  document.getElementById("issue-panel").hidden = false;
  renderRepoHeading(project);
  await selectFirstIssue(await loadIssues());
}

/**
 * Issue一覧に表示中の先頭Issueを選択する
 *
 * 選択中のIssueが一覧に表示中の場合は選択し直さない。
 * 表示中のIssueが無い場合は未選択のままとする。
 * 縦長表示では、Issue一覧の表示が1件のみの場合は閉じる。
 */
async function selectFirstIssue(issues) {
  if (issues.some((issue) => issue.number === currentIssueNumber)) return;
  const [first] = issues;
  if (!first) return;
  await selectIssue(first.number);
  if (issues.length === 1) autoSetSectionExpanded(SECTION_IDS.repo, false);
}

function highlightSelectedProject() {
  document
    .querySelectorAll(".project-item")
    .forEach((li) => li.classList.toggle("active", Number(li.dataset.projectId) === currentProjectId));
}

/**
 * リポジトリ見出しの表示
 *
 * 「Repo #番号 表示名」とし、番号部分はGitHubのリポジトリページへのリンクにする。
 * 右端にDeployボタンを置く。
 * デプロイ未定義のリポジトリではDeployボタンを無効化する。
 */
function renderRepoHeading(project) {
  const label = project.repo_number ? `Repo #${project.repo_number}` : "Repo";
  document.getElementById("repo-heading").innerHTML =
    `${renderTitleNumber(label, project.repo_url)}<span id="repo-title">${escapeHtml(project.display_name)}</span>` +
    `<button type="button" id="deploy-button" class="title-action-button">${DEPLOY_BUTTON_LABEL}</button>`;
  document.getElementById("deploy-status").textContent = "";
  const button = document.getElementById("deploy-button");
  button.disabled = !project.deploy_defined;
  button.title = project.deploy_defined ? DEPLOY_DEFINED_TOOLTIP : DEPLOY_UNDEFINED_TOOLTIP;
  button.addEventListener("click", () => onClickDeploy(project, button));
  if (project.deploy_defined) refreshDeployPending(project.id, button);
}

/**
 * Deployボタンの色の更新
 *
 * デプロイ先のソースに未取り込みの対応がある場合はプライマリ色にする。
 * 取得に失敗した場合は通常の色のままとする。
 */
async function refreshDeployPending(projectId, button) {
  let pending = false;
  try {
    const response = await fetch(`/api/projects/${projectId}/deploy/pending`);
    pending = response.ok && (await response.json()).pending === true;
  } catch (error) {
    pending = false;
  }
  if (button.isConnected) button.classList.toggle("primary", pending);
}

// 表示中のDeployボタンの色を取得中か（git fetchを伴うため多重に取得しない）
let deployPendingRefreshing = false;

/**
 * 表示中のDeployボタンの色の定期更新
 *
 * 定期ステータス更新のタイミングで呼び出す。
 * デプロイ未定義・デプロイ実行中（ボタン無効）の場合は更新しない。
 */
async function refreshCurrentDeployPending() {
  const button = document.getElementById("deploy-button");
  if (deployPendingRefreshing || currentProjectId === null || !button || button.disabled) return;
  deployPendingRefreshing = true;
  try {
    await refreshDeployPending(currentProjectId, button);
  } finally {
    deployPendingRefreshing = false;
  }
}

/**
 * デプロイの実行
 *
 * 結果が出るまでポーリングし、サーバー再起動を含む場合は再起動完了まで待つ。
 * 実行中にリポジトリを切り替えた場合も、結果は実行したリポジトリの見出しにのみ表示する。
 */
async function onClickDeploy(project, button) {
  if (!confirm(`${project.display_name} をデプロイしますか？`)) return;
  const setStatus = (text) => {
    if (currentProjectId === project.id) document.getElementById("deploy-status").textContent = text;
  };
  button.disabled = true;
  setStatus("デプロイ中...");
  try {
    setStatus(await runDeploy(project.id, setStatus));
  } catch (error) {
    setStatus(`デプロイに失敗しました: ${error.message}`);
  } finally {
    button.disabled = false;
    refreshDeployPending(project.id, button);
  }
}

async function runDeploy(projectId, setStatus) {
  const oldBootId = await fetchBootId();
  const response = await fetch(`/api/projects/${projectId}/deploy`, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);

  const result = await waitForDeployResult(projectId);
  if (result === null) return "デプロイの完了を確認できませんでした";
  if (result.status === "failed") return `デプロイに失敗しました: ${result.error}`;
  if (!result.restarts.includes(DEPLOY_RESTART_SERVER)) return "デプロイしました";
  setStatus("デプロイしました。サーバー再起動中...");
  const restarted = await waitForNewBootId(oldBootId);
  return restarted ? "デプロイしました（サーバーを再起動しました）" : "デプロイしました（再起動を確認できませんでした）";
}

async function fetchDeployResult(projectId) {
  try {
    const response = await fetch(`/api/projects/${projectId}/deploy`);
    return response.ok ? await response.json() : null;
  } catch (error) {
    return null;
  }
}

async function waitForDeployResult(projectId) {
  const deadline = Date.now() + DEPLOY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(DEPLOY_POLL_MS);
    const result = await fetchDeployResult(projectId);
    if (result && result.status !== "running") return result;
  }
  return null;
}

/**
 * Issue一覧の読み込み
 *
 * フィルタに該当するIssueを表示し、表示したIssueを返す。
 * MRステータスフィルタの選択中は、Open・Closeを問わず該当Issueを表示する。
 */
async function loadIssues() {
  lastMatchedIssueKey = matchedIssueKey();
  const issues = isMrStatusFilterActive()
    ? await fetchIssuesByMrStatus()
    : await fetchIssues(document.getElementById("issue-filter").value);
  const listEl = document.getElementById("issue-list-items");
  listEl.innerHTML = "";
  if (issues.length === 0) listEl.innerHTML = '<li class="empty">Issueがありません。</li>';
  else issues.forEach((issue) => listEl.appendChild(renderIssueItem(issue)));
  return issues;
}

async function fetchIssues(state) {
  return fetch(
    `/api/projects/${currentProjectId}/issues?state=${encodeURIComponent(state)}`
  ).then((r) => r.json());
}

/**
 * 選択中のステータスのMRを持つIssueを、Open・Closeの両方から取得する
 *
 * 並び順はIssue番号の降順とする。
 */
async function fetchIssuesByMrStatus() {
  const numbers = new Set(matchedIssueNumbers());
  if (numbers.size === 0) return [];
  const lists = await Promise.all(ISSUE_STATES.map(fetchIssues));
  return lists
    .flat()
    .filter((issue) => numbers.has(issue.number))
    .sort((a, b) => b.number - a.number);
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

/**
 * MR一覧の表示対象
 *
 * MRステータスフィルタの選択中は、選択中のいずれかのステータスのMRを表示する。
 */
function filterSubtasks(subtasks) {
  if (isMrStatusFilterActive()) return subtasks.filter((s) => selectedMrStatuses.has(mrStatus(s)));
  const states = SUBTASK_FILTER_STATES[document.getElementById("subtask-filter").value];
  return subtasks.filter((s) => states.includes(s.lifecycle_state));
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
 * MRの表示ステータス
 *
 * 未解決のMRで実装ジョブが実行中の場合はResolvingとする。
 * ResolvedのMRがマージ待ち・マージ中の場合はMergingとする。
 * MergedのMRのリポジトリでデプロイ実行中の場合はDeployingとする。
 */
function mrStatus(s) {
  const isOpen = SUBTASK_FILTER_STATES.unresolved.includes(s.lifecycle_state);
  if (isOpen && isJobActive(s.latest_job)) return MR_STATUS.resolving;
  if (s.lifecycle_state === LIFECYCLE.resolved && isMergeActive(s.latest_merge)) return MR_STATUS.merging;
  if (s.lifecycle_state === LIFECYCLE.merged && s.deploying) return MR_STATUS.deploying;
  return s.lifecycle_state;
}

/**
 * MRの状態表示
 *
 * 一覧の行と詳細の見出しで共通に使う。
 * Resolving・Mergingはツールチップに意味（マージ待ちの場合はマージ待ち）を出す。
 * マージ失敗はResolvedのままの場合のみ併記し、ツールチップに理由を出す。
 */
function renderSubtaskState(s) {
  const status = mrStatus(s);
  const label = MR_STATUS_LABELS[status] || status;
  const merge = s.latest_merge;
  const showFailure = status === MR_STATUS.resolved && merge && merge.status === MERGE_STATUS.failed;
  const suffix = showFailure ? `（${MERGE_STATUS_LABELS[merge.status]}）` : "";
  const tooltipText = showFailure ? merge.error_message : mrStatusTooltip(status, merge);
  const tooltip = tooltipText ? ` title="${escapeAttr(tooltipText)}"` : "";
  return `<span class="subtask-state"${tooltip}>${label}${suffix}</span>`;
}

function mrStatusTooltip(status, merge) {
  if (status === MR_STATUS.merging) return MERGE_STATUS_LABELS[merge.status];
  return MR_STATUS_TOOLTIPS[status] || "";
}

function highlightSelectedSubtaskRow() {
  document
    .querySelectorAll(".subtask-row")
    .forEach((row) =>
      row.classList.toggle("active", Number(row.dataset.subtaskId) === currentSelectedSubtaskId)
    );
}

/**
 * Issueの選択
 *
 * MR一覧に表示中の先頭MRを自動選択する。
 * 表示中のMRが無い場合は未選択とし、縦長表示ではMR内容を閉じる。
 * 縦長表示ではIssue内容を開き、MR一覧の表示が1件のみの場合は閉じる。
 * 表示が複数件の場合は、MRを選択し直せるよう開いたままにする。
 */
async function selectIssue(number) {
  currentIssueNumber = number;
  currentSelectedSubtaskId = null;
  autoSetSectionExpanded(SECTION_IDS.issue, true);
  document
    .querySelectorAll(".issue-item")
    .forEach((el) => el.classList.toggle("active", Number(el.dataset.number) === number));

  await refreshIssueDetail();
  selectFirstSubtask();
  if (filterSubtasks(currentSubtasks).length === 1) autoSetSectionExpanded(SECTION_IDS.issue, false);
}

/**
 * MR一覧に表示中の先頭MRを選択する
 *
 * 表示中のMRが無い場合はMR未選択の表示にする。
 */
function selectFirstSubtask() {
  const [first] = filterSubtasks(currentSubtasks);
  if (first) selectSubtask(first.id);
  else renderSubtaskDetail(null);
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
MR自動作成中は作成ボタンを無効のままにする。
*/
function resetSubtaskForm() {
  const form = document.getElementById("subtask-form");
  form.reset();
  form.querySelector("button").disabled = isCurrentIssueAutoMrCreating();
  document.getElementById("subtask-form-status").textContent = "";
}

function selectSubtask(subtaskId) {
  currentSelectedSubtaskId = subtaskId;
  highlightSelectedSubtaskRow();
  autoSetSectionExpanded(SECTION_IDS.mr, true);
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
    autoSetSectionExpanded(SECTION_IDS.mr, false);
    return;
  }

  heading.innerHTML =
    `${renderSubtaskNumber(s)}${renderMrTitle(s, { id: "subtask-title" })}${renderSubtaskState(s)}`;
  el.innerHTML = `
    <p id="subtask-title-status" class="title-status empty"></p>
    <div class="instruction-form">
      <div id="subtask-actions" class="subtask-actions" data-subtask-id="${s.id}"></div>
      <textarea id="instruction-${s.id}" name="instruction" aria-label="指示内容" placeholder="Claudeへの指示内容を入力してください（添付ファイルはS1、S2などのIDで指定できます）">${escapeHtml(s.instruction)}</textarea>
      <div class="attachment-area">
        <button type="button" id="attach-file-button" class="subtask-action-button attach-button">ファイル添付</button>
        <button type="button" id="attach-image-button" class="subtask-action-button attach-button">画像添付</button>
        <input type="file" id="attach-file-input" multiple hidden />
        <input type="file" id="attach-image-input" accept="image/*" hidden />
        <span id="attachment-status" class="empty"></span>
      </div>
      <div id="attachment-list" data-subtask-id="${s.id}"></div>
    </div>
    <p id="subtask-action-status" class="title-status empty"></p>
    <p class="job-status empty" data-subtask-id="${s.id}"></p>
    <iframe class="report-frame" sandbox="" data-subtask-id="${s.id}" hidden></iframe>
  `;

  renderSubtaskActions(s);
  makeTitleEditable(
    document.getElementById("subtask-title"),
    document.getElementById("subtask-title-status"),
    (title) => saveSubtaskTitle(s.id, title)
  );
  setupAttachmentForm(s.id);

  restoreJobState(s);
}

/**
 * 添付ボタン・添付ファイル一覧の初期化
 *
 * ファイル添付は選択したファイルをそのまま順にアップロードする。
 * 画像添付は選択した画像をお絵かきダイアログで加工してからアップロードする。
 */
function setupAttachmentForm(subtaskId) {
  bindFileChooser("attach-file-button", "attach-file-input", (files) => uploadAttachments(subtaskId, files));
  bindFileChooser("attach-image-button", "attach-image-input", async ([file]) => {
    const edited = await openImageEditor(file);
    if (edited) await uploadAttachments(subtaskId, [edited]);
  });
  loadAttachments(subtaskId);
}

/**
 * ボタンで規定のファイル選択を開き、選択結果を渡す
 *
 * 同じファイルを続けて選べるよう、選択後に入力値をクリアする。
 */
function bindFileChooser(buttonId, inputId, onSelect) {
  const button = document.getElementById(buttonId);
  const input = document.getElementById(inputId);
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    if (files.length) await onSelect(files);
  });
}

async function loadAttachments(subtaskId) {
  const attachments = await fetch(`/api/subtasks/${subtaskId}/attachments`)
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  renderAttachmentList(subtaskId, attachments);
}

/**
 * 添付ファイルの表（ID・ファイル）を描画する
 *
 * 画像はファイル名の代わりにサムネイルを表示する。
 * 削除ボタンは添付ボタンと同じ条件で無効化する。
 * 添付ファイルが無い場合は表を表示しない。
 */
function renderAttachmentList(subtaskId, attachments) {
  const container = document.getElementById("attachment-list");
  if (!container || Number(container.dataset.subtaskId) !== subtaskId) return;
  if (!attachments.length) {
    container.innerHTML = "";
    return;
  }
  const disabled = document.getElementById("attach-file-button")?.disabled ? " disabled" : "";
  const rows = attachments.map((a) => renderAttachmentRow(subtaskId, a, disabled)).join("");
  container.innerHTML =
    `<table class="attachment-table"><thead><tr><th>ID</th><th>ファイル</th><th></th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
  container
    .querySelectorAll(".attachment-delete-button")
    .forEach((b) => b.addEventListener("click", () => removeAttachment(subtaskId, b.dataset.attachmentId)));
}

function renderAttachmentRow(subtaskId, attachment, disabled) {
  const id = escapeHtml(attachment.id);
  const deleteButton =
    `<button type="button" class="subtask-action-button attach-button attachment-delete-button"` +
    ` data-attachment-id="${id}"${disabled}>削除</button>`;
  return `<tr><td>${id}</td><td>${renderAttachmentCell(subtaskId, attachment)}</td><td>${deleteButton}</td></tr>`;
}

function renderAttachmentCell(subtaskId, attachment) {
  if (!attachment.is_image) return escapeHtml(attachment.filename);
  const url = `/api/subtasks/${subtaskId}/attachments/${encodeURIComponent(attachment.id)}/file`;
  const name = escapeHtml(attachment.filename);
  return `<a href="${url}" target="_blank" rel="noopener"><img class="attachment-thumbnail" src="${url}" alt="${name}" title="${name}" loading="lazy" /></a>`;
}

/**
 * 選択したファイルを1件ずつアップロードする
 *
 * IDの採番順を選択順に揃えるため、並列にせず順に送る。
 */
async function uploadAttachments(subtaskId, files) {
  const statusEl = document.getElementById("attachment-status");
  const errors = [];
  for (const file of files) {
    statusEl.textContent = `アップロード中: ${file.name}`;
    const error = await uploadAttachment(subtaskId, file);
    if (error) errors.push(`${file.name}: ${error}`);
  }
  if (statusEl.isConnected) statusEl.textContent = errors.length ? `失敗しました: ${errors.join(" / ")}` : "";
  await loadAttachments(subtaskId);
}

/**
 * 確認のうえ添付ファイルを削除し、一覧を読み直す
 *
 * 失敗した場合は添付ボタン横の状態欄に理由を表示する。
 */
async function removeAttachment(subtaskId, attachmentId) {
  if (!confirm(`添付ファイル ${attachmentId} を削除しますか？`)) return;
  const response = await fetch(
    `/api/subtasks/${subtaskId}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" }
  ).catch(() => null);
  const statusEl = document.getElementById("attachment-status");
  if (statusEl) statusEl.textContent = response?.ok ? "" : `削除に失敗しました: ${attachmentId}`;
  await loadAttachments(subtaskId);
}

async function uploadAttachment(subtaskId, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/subtasks/${subtaskId}/attachments`, { method: "POST", body: form })
    .catch(() => null);
  if (!response) return "通信に失敗しました";
  if (response.ok) return null;
  const body = await response.json().catch(() => ({}));
  return body.detail || response.statusText;
}

function restoreJobState(s) {
  const job = s.latest_job;
  if (!job) {
    return;
  }

  const statusEl = document.querySelector(`.job-status[data-subtask-id="${s.id}"]`);
  statusEl.textContent = `状態: ${job.status}`;

  if (isJobActive(job)) {
    pollJob(job.id, s.id);
    return;
  }

  if (job.status === "succeeded" && job.has_report) {
    showReport(job.id, s.id);
  }
}

async function pollSubtaskStates() {
  try {
    if (!document.hidden) {
      // git fetchで時間がかかる場合があるため、MR一覧の更新は待たせない
      refreshCurrentDeployPending();
      await Promise.all([refreshSubtaskStates(), refreshIssueListMrCounts()]);
    }
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
 * 見出しの番号・状態と操作ボタンのみ差し替える。
 */
function refreshSelectedSubtaskState() {
  const selected = currentSubtasks.find((s) => s.id === currentSelectedSubtaskId);
  if (!selected) return;
  const stateEl = document.querySelector("#subtask-heading .subtask-state");
  if (stateEl) stateEl.outerHTML = renderSubtaskState(selected);
  const numberEl = document.querySelector("#subtask-heading .title-number");
  if (numberEl) numberEl.outerHTML = renderSubtaskNumber(selected);
  renderSubtaskActions(selected);
}

function isJobActive(job) {
  return !!job && ACTIVE_JOB_STATUSES.includes(job.status);
}

/**
 * MRの操作ボタンを状態に応じて描画する
 *
 * 操作中・実装の実行中は全ボタンを無効化する。
 * 実装できない状態では指示内容を読み取り専用にする。
 */
function renderSubtaskActions(s) {
  const container = document.getElementById("subtask-actions");
  if (!container || Number(container.dataset.subtaskId) !== s.id) return;
  const actions = SUBTASK_ACTIONS[s.lifecycle_state] || [];
  const busy = busySubtaskIds.has(s.id) || isJobActive(s.latest_job) || isMergeActive(s.latest_merge);
  container.innerHTML = actions.map((a) => renderSubtaskActionButton(a, busy)).join("");
  container
    .querySelectorAll("button")
    .forEach((b) => b.addEventListener("click", () => onClickSubtaskAction(s.id, b.dataset.action)));
  const editable = actions.some((a) => a.action === "execute");
  const textarea = document.getElementById(`instruction-${s.id}`);
  if (textarea) textarea.readOnly = !editable;
  document.querySelectorAll(".attach-button").forEach((b) => (b.disabled = !editable || busy));
}

function renderSubtaskActionButton(action, disabled) {
  const classes = ["subtask-action-button", action.primary ? "primary" : ""].filter(Boolean).join(" ");
  return (
    `<button type="button" class="${classes}" data-action="${action.action}"` +
    `${disabled ? " disabled" : ""}>${action.label}</button>`
  );
}

function setSubtaskBusy(subtaskId, busy) {
  if (busy) busySubtaskIds.add(subtaskId);
  else busySubtaskIds.delete(subtaskId);
  refreshSelectedSubtaskState();
}

async function onClickSubtaskAction(subtaskId, action) {
  const subtask = currentSubtasks.find((s) => s.id === subtaskId);
  if (!subtask) return;
  if (action === "execute") {
    await executeSubtask(subtask);
    return;
  }
  await runSubtaskStateAction(subtask, SUBTASK_STATE_ACTIONS[action]);
}

/**
 * Cancel・ReOpen・Mergeの実行
 *
 * 成功時はサーバーが返した状態を反映し、一覧とIssueのMR数も更新する。
 */
async function runSubtaskStateAction(subtask, def) {
  if (!confirm(`MR「${subtask.title}」${def.confirm}`)) return;
  const statusEl = document.getElementById("subtask-action-status");
  setSubtaskBusy(subtask.id, true);
  statusEl.textContent = def.progress;
  const { body, error } = await postAction(`/api/subtasks/${subtask.id}/${def.path}`);
  const latest = currentSubtasks.find((s) => s.id === subtask.id);
  if (!error && latest) latest.lifecycle_state = body.lifecycle_state;
  if (!error && latest && body.latest_merge) latest.latest_merge = body.latest_merge;
  if (!error && body.latest_merge) renderMerges().catch(() => {});
  busySubtaskIds.delete(subtask.id);
  updateIssueMrCounts(currentIssueNumber, currentSubtasks);
  renderSubtaskList();
  refreshSelectedSubtaskState();
  if (statusEl.isConnected) statusEl.textContent = error ? `失敗しました: ${error}` : def.done;
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
 * Issue一覧の全行のMR数を再取得して反映する
 *
 * 自動同期で表示中以外のIssueのMR状態が変わっても追従させる。
 * Issue一覧はGitHubから再取得せず、DB上のMR数のみ取得する。
 */
async function refreshIssueListMrCounts() {
  const projectId = currentProjectId;
  if (projectId === null) return;
  const response = await fetch(`/api/projects/${projectId}/mr-counts`);
  if (!response.ok) return;
  const counts = await response.json();
  if (projectId !== currentProjectId) return;
  document
    .querySelectorAll(".issue-item")
    .forEach((li) => updateIssueItemCounts(li, counts[li.dataset.number] || countMrs([])));
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
    resolved: countIn(MR_COUNT_RESOLVED_STATES),
    unresolved: countIn(SUBTASK_FILTER_STATES.unresolved),
    total: counted.length,
  };
}

async function onSubmitIssueForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("issue-create-status");
  const title = form.title.value;

  const projectId = currentProjectId;

  // MR自動作成が終わるまでは次のIssueを作成させない
  statusEl.textContent = "IssueとMRを作成中...";
  form.querySelector("button").disabled = true;
  try {
    const created = await createIssueWithSubtask(projectId, title, statusEl);
    if (!created) return;
    if (form.title.value === title) form.reset();
    if (projectId === currentProjectId) await openCreatedIssueAndSubtask(created.issue, created.subtaskId);
  } finally {
    form.querySelector("button").disabled = false;
  }
}

/**
 * IssueとMRの作成
 *
 * 高速化のため、Issue作成とMR作成を並行して行い、MRへのIssue紐付けは後から行う。
 * 作成中は画面を更新せず、利用者の操作を妨げない。
 * Issue作成に失敗した場合はnull、MR作成のみ失敗した場合はsubtaskIdをnullで返す。
 */
async function createIssueWithSubtask(projectId, title, statusEl) {
  const pendingPromise = postJson("/api/subtasks/pending", { project_id: projectId, issue_title: title });
  const { body: issue, error } = await postJson(`/api/projects/${projectId}/issues`, { title });
  if (error) {
    statusEl.textContent = `失敗しました: ${error}`;
    await discardPendingSubtask(projectId, pendingPromise);
    return null;
  }

  setAutoMrCreatingIssue(issue.number);
  const result = await linkPendingSubtask(projectId, issue.number, pendingPromise);
  setAutoMrCreatingIssue(null);
  statusEl.textContent = result.error
    ? `Issueを作成しましたが、MRの作成に失敗しました: ${result.error}`
    : "IssueとMRを作成しました";
  return { issue, subtaskId: result.body?.id ?? null };
}

/**
 * JSONをPOSTする
 *
 * 成功時は応答本文、失敗時はエラー文言を返す。
 */
async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => null);
  if (!response) return { error: "サーバーに接続できませんでした" };
  const body = await response.json().catch(() => ({}));
  return response.ok ? { body } : { error: body.detail || response.statusText };
}

/**
 * Issue作成に失敗した場合に、並行して作成したMRをクローズする
 *
 * MR作成も失敗していた場合は何もしない。
 */
async function discardPendingSubtask(projectId, pendingPromise) {
  const { body } = await pendingPromise;
  if (!body) return;
  await postJson("/api/subtasks/pending/discard", {
    project_id: projectId,
    github_pr_number: body.github_pr_number,
  });
}

/**
 * 並行して作成したMRをIssueに紐付ける
 *
 * MR作成に失敗していた場合は、そのエラーを返す。
 */
async function linkPendingSubtask(projectId, issueNumber, pendingPromise) {
  const { body, error } = await pendingPromise;
  if (error) return { error };
  return postJson("/api/subtasks/pending/link", {
    project_id: projectId,
    github_issue_number: issueNumber,
    ...body,
  });
}

/**
 * 作成したIssueとMRを開く
 *
 * IssueとMRの作成完了後にまとめて画面へ反映する。
 * 高速化のため、Issue一覧の再取得とIssueの選択を並行して行う。
 * 縦長表示ではIssue一覧とIssue内容を閉じ、MRの指示内容の入力欄を見せる。
 * MR作成に失敗した場合はIssueのみ開く。
 */
async function openCreatedIssueAndSubtask(issue, subtaskId) {
  await Promise.all([loadIssues(), selectIssue(issue.number)]).catch(() => {});
  supplementCreatedIssue(issue);
  autoSetSectionExpanded(SECTION_IDS.repo, false);
  if (subtaskId === null || issue.number !== currentIssueNumber) return;
  autoSetSectionExpanded(SECTION_IDS.issue, false);
  selectSubtask(subtaskId);
  focusWithScroll(document.getElementById(`instruction-${subtaskId}`));
}

/**
 * 作成したIssueを一覧に補ってスクロールする
 *
 * GitHubの一覧反映が遅れた場合は、作成したIssueを一覧の先頭に補う。
 */
function supplementCreatedIssue(issue) {
  const listEl = document.getElementById("issue-list-items");
  const isListed = listEl.querySelector(`.issue-item[data-number="${issue.number}"]`);
  // MRステータスフィルタの選択中は、集計の更新を待って一覧に反映させる
  const showsOpen =
    !isMrStatusFilterActive() &&
    ISSUE_FILTERS_SHOWING_NEW_ISSUE.includes(document.getElementById("issue-filter").value);
  if (!isListed && showsOpen) {
    listEl.querySelector(".empty")?.remove();
    const subtasks = issue.number === currentIssueNumber ? currentSubtasks : [];
    const item = { ...issue, state: "OPEN", mr_counts: countMrs(subtasks) };
    listEl.prepend(renderIssueItem(item));
  }
  listEl
    .querySelector(`.issue-item[data-number="${issue.number}"]`)
    ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function onSubmitSubtaskForm(event) {
  event.preventDefault();
  if (isCurrentIssueAutoMrCreating()) return;
  const form = event.target;
  const statusEl = document.getElementById("subtask-form-status");
  const title = form.title.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const issueNumber = currentIssueNumber;
  const { body, error } = await createSubtask(issueNumber, title);
  if (error) {
    statusEl.textContent = `失敗しました: ${error}`;
    form.querySelector("button").disabled = false;
    return;
  }

  await openCreatedSubtask(issueNumber, body.id);
}

/**
 * MRの作成
 *
 * MR固有名が空欄の場合はサーバー側で連番を割り当てる。
 * Issue名が既知の場合は渡し、サーバー側のGitHub問い合わせを省略させる。
 * 成功時は応答本文、失敗時はエラー文言を返す。
 */
async function createSubtask(issueNumber, title, issueTitle = "") {
  return postJson("/api/subtasks", {
    project_id: currentProjectId,
    github_issue_number: issueNumber,
    title,
    issue_title: issueTitle,
  });
}

/**
 * 作成したMRを開いて指示内容の入力欄にフォーカスする
 *
 * MR一覧を再取得してから、作成したMRを選択する。
 * 表示中のIssueの場合は、GitHubへ問い合わせないDB上のMR一覧のみ再取得する。
 * 縦長表示では指示内容の入力欄を見せるため、Issue内容を閉じる。
 */
async function openCreatedSubtask(issueNumber, subtaskId) {
  if (issueNumber === currentIssueNumber) {
    await refreshSubtaskStates();
    resetSubtaskForm();
  } else {
    await selectIssue(issueNumber);
  }
  autoSetSectionExpanded(SECTION_IDS.issue, false);
  selectSubtask(subtaskId);
  focusWithScroll(document.getElementById(`instruction-${subtaskId}`));
}

/**
 * 入力欄にフォーカスし、その位置まで画面をスクロールする
 *
 * ブラウザ既定のスクロールは最小限で欄が見切れるため、欄を画面中央に寄せる。
 */
function focusWithScroll(el) {
  if (!el) return;
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: "center", behavior: "smooth" });
}

/**
 * 実装・再実装の実行
 *
 * 入力中の指示内容で実行し、終了までMRの操作ボタンを無効化する。
 */
async function executeSubtask(subtask) {
  const instruction = document.getElementById(`instruction-${subtask.id}`)?.value;
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtask.id}"]`);
  if (!instruction) {
    statusEl.textContent = "指示内容を入力してください";
    return;
  }
  setSubtaskBusy(subtask.id, true);
  statusEl.textContent = "実行待ち...";

  const response = await fetch(`/api/subtasks/${subtask.id}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  }).catch(() => null);
  if (!response || !response.ok) {
    statusEl.textContent = "実行を開始できませんでした";
    setSubtaskBusy(subtask.id, false);
    return;
  }
  pollJob((await response.json()).job_id, subtask.id);
}

/**
 * ジョブの終了まで状態を監視する
 *
 * MR詳細の再描画のたびに呼ばれるため、同じジョブは重複して監視しない。
 */
function pollJob(jobId, subtaskId) {
  if (pollingJobIds.has(jobId)) return;
  pollingJobIds.add(jobId);
  busySubtaskIds.add(subtaskId);
  pollJobLoop(jobId, subtaskId);
}

async function pollJobLoop(jobId, subtaskId) {
  const job = await fetch(`/api/jobs/${jobId}`)
    .then((r) => r.json())
    .catch(() => null);
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  if (statusEl && job) statusEl.textContent = `状態: ${job.status}`;

  // 取得失敗時（サーバー再起動中など）も監視を継続する
  if (!job || isJobActive(job)) {
    setTimeout(() => pollJobLoop(jobId, subtaskId), JOB_POLL_MS);
    return;
  }
  pollingJobIds.delete(jobId);
  busySubtaskIds.delete(subtaskId);
  await onJobFinished(job, jobId, subtaskId);
}

async function onJobFinished(job, jobId, subtaskId) {
  if (job.status !== "succeeded") {
    // 失敗時はジョブ状態を取り直してボタンを戻す
    await refreshSubtaskStates().catch(() => {});
    refreshSelectedSubtaskState();
    return;
  }
  if (currentSelectedSubtaskId !== subtaskId) return;
  // refreshIssueDetailが詳細ペインの選択状態を消すため、再描画してから選択し直す
  await refreshIssueDetail();
  selectSubtask(subtaskId);
  await showReport(jobId, subtaskId);
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

setupExpanders();
setupMrStatusFilter();
document.getElementById("issue-create-form").addEventListener("submit", onSubmitIssueForm);
document.getElementById("issue-filter").addEventListener("change", loadIssues);
document.getElementById("subtask-filter").addEventListener("change", renderSubtaskList);
document.getElementById("subtask-form").addEventListener("submit", onSubmitSubtaskForm);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  refreshSubtaskStates().catch(() => {});
  refreshCurrentDeployPending();
});

init();

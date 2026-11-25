/**
 * 画面全体で共有する状態・定義と共通処理
 *
 * 選択中のリポジトリ・Issue・MRの状態、MR・ジョブの状態定義を持つ。
 * 選択・操作中の画面ブロック、タイトル編集等の共通処理を持つ。
 */

let currentProjectId = null;
let currentIssueNumber = null;
let currentIssueState = null;
let currentIssueTitle = null;
let currentIssueUrl = null;
let currentSubtasks = [];
// Issue一覧に表示中のIssue（番号→番号・タイトル・状態・URL）
const listedIssues = new Map();
let currentSelectedSubtaskId = null;

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
// 遷移中のステータスは矢印で表す
const MR_STATUS_FILTER_BUTTONS = [
  { status: MR_STATUS.draft, label: "Draft" },
  { status: MR_STATUS.resolving, label: "→" },
  { status: MR_STATUS.resolved, label: "Resolved" },
  { status: MR_STATUS.merging, label: "→" },
  { status: MR_STATUS.merged, label: "Merged" },
];
const MR_STATUS_FILTER_TOOLTIP = "のMRで絞り込み（全リポジトリでMRが無い場合は選択不可）";
const MR_STATUS_POLL_MS = 3000;
// MRステータスフィルタの選択中に隠す既存フィルタ
const MR_STATUS_FILTER_HIDDEN_IDS = ["issue-filter", "subtask-filter"];
// MRステータスフィルタの選択時に閉じる作成欄
const MR_STATUS_FILTER_COLLAPSED_IDS = ["issue-create-block", "subtask-create-block"];

// MR一覧フィルタの値ごとに表示対象のlifecycle_stateを定義する
// 未完了はDraft〜Merging、完了はMerged〜Deployed、全てはCanceledも含め全状態を表示する
const SUBTASK_FILTER_STATES = {
  all: Object.values(LIFECYCLE),
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
    done: "マージ待ちに登録しました（進捗はMRのステータスで確認できます）",
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

function isMergeActive(merge) {
  return !!merge && [MERGE_STATUS.queued, MERGE_STATUS.running].includes(merge.status);
}

// 実装ジョブの状態（core/job_queue.py・worker/main.pyと合わせる）
const JOB_STATUS = {
  queued: "queued",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
  needsAttention: "needs_attention",
  rateLimited: "rate_limited",
};
const JOB_STATUS_LABELS = {
  [JOB_STATUS.queued]: "実行待ち",
  [JOB_STATUS.running]: "実行中",
  [JOB_STATUS.succeeded]: "完了",
  [JOB_STATUS.failed]: "失敗",
  [JOB_STATUS.needsAttention]: "要確認",
  [JOB_STATUS.rateLimited]: "利用上限で中断（上限リセット後に自動で再実行）",
};
const JOB_STATUS_PREFIX = "状態: ";
// 別端末などで実行済みのジョブを監視している場合に、状態の前へ付ける文言
const JOB_ALREADY_ACTIVE_NOTE = "実行済みのジョブを表示中 / ";

// ジョブ状態の見た目（style.cssの.job-status-*と合わせる）
const JOB_STATUS_CLASS = {
  active: "job-status-active",
  success: "job-status-success",
  warning: "job-status-warning",
};
const JOB_STATUS_CLASSES = {
  [JOB_STATUS.queued]: JOB_STATUS_CLASS.active,
  [JOB_STATUS.running]: JOB_STATUS_CLASS.active,
  [JOB_STATUS.succeeded]: JOB_STATUS_CLASS.success,
  [JOB_STATUS.failed]: JOB_STATUS_CLASS.warning,
  [JOB_STATUS.needsAttention]: JOB_STATUS_CLASS.warning,
  [JOB_STATUS.rateLimited]: JOB_STATUS_CLASS.warning,
};
const JOB_STATUS_ERROR_CLASS = "job-status-error";

// 実行中とみなすジョブの状態（実行中はMRの操作ボタンを無効化する）
const ACTIVE_JOB_STATUSES = [JOB_STATUS.queued, JOB_STATUS.running];

// 操作中（API応答待ち・実装の実行中）のMRのID
const busySubtaskIds = new Set();
// 監視中のジョブID
const pollingJobIds = new Set();
// 実行を拒否され、既存ジョブの監視に切り替えたジョブID
const followedJobIds = new Set();
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

// 連番の丸数字は①〜⑳・㉑〜㉟・㊱〜㊿の3ブロック（core/mr_naming.pyと合わせる）
const CIRCLED_NUMBER_RANGES = [
  { first: 1, last: 20, base: 0x2460 },
  { first: 21, last: 35, base: 0x3251 },
  { first: 36, last: 50, base: 0x32b1 },
];

// 表示・非表示を切り替えるペインのID
const SECTION_IDS = {
  repo: "issue-list",
  issue: "subtask-list",
  mr: "subtask-detail",
};

/**
 * ペインの表示・非表示を切り替える
 *
 * 親項目が未選択で表示内容が無いペインは、見出し行ごと非表示にする。
 * 縦長表示・横長表示を問わず切り替える。
 * 表示中のタブの対象外のペインは、表示指定でも隠す。
 */
function setSectionShown(sectionId, shown) {
  const section = document.getElementById(sectionId);
  section.dataset.shown = String(shown);
  applySectionShown(section);
}

/**
 * ペインの表示指定と表示中のタブから、表示・非表示を反映する
 */
function applySectionShown(section) {
  section.hidden = section.dataset.shown !== "true" || isSectionHiddenByTab(section.id);
}

// 選択の切り替え要求の通番（後発の要求があれば、先発の取得結果で表示を上書きしない）
let selectionRequestId = 0;

function nextSelectionRequest() {
  selectionRequestId += 1;
  return selectionRequestId;
}

function isLatestSelectionRequest(requestId) {
  return requestId === selectionRequestId;
}

/**
 * 選択の切り替え要求を実行する
 *
 * 取得結果は、後発の要求が無い場合のみ表示に反映する。
 * blockingの場合は、取得中に画面をブロックして更新中を表示する。
 * 更新中の表示は、最新の要求の終了時（失敗時も含む）に消す。
 */
async function runSelectionRequest(load, apply, { blocking = true } = {}) {
  const requestId = nextSelectionRequest();
  if (blocking) setSelectionBusy(true);
  try {
    const result = await load();
    if (isLatestSelectionRequest(requestId)) apply(result);
  } finally {
    if (isLatestSelectionRequest(requestId)) setSelectionBusy(false);
  }
}

// 選択の切り替えで更新待ちか
let selectionBusy = false;
// 更新待ちの操作の数（並行して実行された操作が全て終わるまで更新中を表示する）
let busyActionCount = 0;

function setSelectionBusy(busy) {
  selectionBusy = busy;
  updateBusyOverlay();
}

/**
 * 更新待ちの操作を実行する
 *
 * 実行中は選択の切り替えと同じく、画面をブロックして更新中を表示する。
 * 失敗時も含め、操作の終了時に表示を戻す。
 */
async function runBusyAction(action) {
  busyActionCount += 1;
  updateBusyOverlay();
  try {
    return await action();
  } finally {
    busyActionCount -= 1;
    updateBusyOverlay();
  }
}

function updateBusyOverlay() {
  document.getElementById("selection-busy").hidden = !selectionBusy && busyActionCount === 0;
}

/**
 * 固定表示のヘッダーの高さを、本文の余白とスクロール位置に反映する
 *
 * ヘッダーは画面幅やレート制限表示で折り返して高さが変わるため、変化を監視する。
 */
function setupHeaderOffset() {
  const header = document.querySelector("header");
  const apply = () =>
    document.documentElement.style.setProperty("--header-height", `${header.offsetHeight}px`);
  new ResizeObserver(apply).observe(header);
  apply();
}

/**
 * 開閉欄のエキスパンダの初期化
 *
 * 開閉欄は閉じている間、見出しのみ表示する。
 * 開閉の初期状態はHTMLのcollapsedクラスで指定する。
 */
function setupFoldExpanders() {
  document.querySelectorAll(".fold-heading > .expander").forEach((button) => {
    const block = button.closest(".fold-block");
    button.addEventListener("click", () => setFoldBlockExpanded(block, block.classList.contains("collapsed")));
  });
}

/**
 * 開閉欄の開閉状態の設定
 */
function setFoldBlockExpanded(block, expanded) {
  block.classList.toggle("collapsed", !expanded);
  block.querySelector(".fold-heading > .expander").setAttribute("aria-expanded", String(expanded));
}

/**
 * 開閉欄を閉じる
 *
 * 作成フォームなど開閉欄内の要素を受け取り、その開閉欄を閉じる。
 */
function collapseFoldBlock(element) {
  setFoldBlockExpanded(element.closest(".fold-block"), false);
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
 * 保存が終わるまで更新中を表示する。
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
      const error = await runBusyAction(() => onSave(title));
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
  const warning = titleEl.closest(`.${MR_TITLE_WARNING_CLASS}`)
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
 * 命名規則に沿う場合はIssue名・区切り文字・MR固有名に分けて表示する。
 * 収まらない場合はIssue名の部分のみ省略し、MR固有名は常に表示する。
 * 沿わない場合は全体を警告表示する。
 */
function renderMrTitle(s, { id = "", className = "" } = {}) {
  const suffix = splitMrTitle(s.title);
  const warning = suffix === null;
  const classes = ["mr-title", className, warning ? MR_TITLE_WARNING_CLASS : ""].filter(Boolean).join(" ");
  const idAttr = id ? ` id="${id}"` : "";
  const tooltip = warning ? `${s.title}\n${MR_TITLE_WARNING_TEXT}` : s.title;
  const content = warning ? renderMrTitlePart("whole", s.title) : renderMrTitleParts(suffix);
  return `<span${idAttr} class="${classes}" title="${escapeAttr(tooltip)}">${content}</span>`;
}

function renderMrTitleParts(suffix) {
  return (
    renderMrTitlePart("issue", currentIssueTitle) +
    renderMrTitlePart("separator", MR_NAME_SEPARATOR) +
    renderMrTitlePart("suffix", suffix)
  );
}

function renderMrTitlePart(part, text) {
  return `<span class="mr-title-${part}">${escapeHtml(text)}</span>`;
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
 * POST操作の実行
 *
 * 成功時は応答本文、失敗時はエラー文言を返す。
 */
async function postAction(url) {
  const response = await fetch(url, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  return response.ok ? { body } : { error: body.detail || response.statusText };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 見出しの種別表示
 *
 * URLがある場合はGitHubを開くリンクにする。
 */
function renderTitleNumber(label, url) {
  if (!url) return `<span class="title-number">${label}</span>`;
  return `<a class="title-number" href="${url}" target="_blank" rel="noopener" title="GitHubで開く">${label}</a>`;
}

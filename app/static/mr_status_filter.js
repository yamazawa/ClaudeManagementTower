/**
 * ヘッダーのMRステータスフィルタ・レート制限表示
 *
 * 全リポジトリのMRステータス集計を定期取得し、フィルタと件数を更新する。
 * Claudeサブスクリプションの使用率を定期取得して表示する。
 */

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
 * ボタンは1度だけ作り、選択状態と選択可否はupdateMrStatusFilterButtonsで更新する。
 * ステータスのボタンは隙間なく並べる。
 */
function setupMrStatusFilter() {
  const container = document.getElementById("mr-status-filter");
  container.innerHTML =
    `<span class="mr-status-filter-segments">` +
    MR_STATUS_FILTER_BUTTONS.map(renderMrStatusFilterButton).join("") +
    `</span>`;
  container
    .querySelectorAll("[data-status]")
    .forEach((b) => b.addEventListener("click", () => toggleMrStatusFilter(b.dataset.status)));
  updateMrStatusFilterButtons();
}

function renderMrStatusFilterButton(def) {
  const tooltip = `${MR_STATUS_LABELS[def.status]}${MR_STATUS_FILTER_TOOLTIP}`;
  return (
    `<button type="button" class="mr-status-filter-button" data-status="${def.status}"` +
    ` aria-pressed="false" title="${escapeAttr(tooltip)}">` +
    `<span class="mr-status-filter-label">${def.label}</span>` +
    `<span class="mr-status-filter-count"></span></button>`
  );
}

function mrStatusFilterCount(status) {
  return mrStatusSummary.counts[status] ?? 0;
}

/**
 * MRステータスフィルタのボタンの選択状態・選択可否・件数を更新する
 *
 * MRが0件のステータスは無効化する（件数は0と表示する）。
 */
function updateMrStatusFilterButtons() {
  MR_STATUS_FILTER_BUTTONS.forEach((def) => {
    const button = document.querySelector(`#mr-status-filter [data-status="${def.status}"]`);
    const count = mrStatusFilterCount(def.status);
    button.setAttribute("aria-pressed", String(selectedMrStatuses.has(def.status)));
    button.disabled = count === 0;
    button.querySelector(".mr-status-filter-count").textContent = String(count);
  });
}

/**
 * MRステータスフィルタの選択を切り替える
 *
 * 選択できるステータスは1つのみとする。
 * 一覧の再表示後に、画面の一番下までスクロールする。
 */
async function toggleMrStatusFilter(status) {
  const wasSelected = selectedMrStatuses.has(status);
  selectedMrStatuses.clear();
  if (!wasSelected) selectedMrStatuses.add(status);
  await onMrStatusFilterChanged();
  scrollToPageBottom();
}

/**
 * 選択中のステータスが0件になった場合に、選択を次のステータスへ移す
 *
 * 後続で1件以上あるステータスを選択する。
 * 該当が無い場合（Merged選択中など）は未選択に戻す。
 * 選択を変更した場合はtrueを返す。
 */
function moveEmptyMrStatusSelection() {
  const index = MR_STATUS_FILTER_BUTTONS.findIndex((def) => selectedMrStatuses.has(def.status));
  if (index < 0 || mrStatusFilterCount(MR_STATUS_FILTER_BUTTONS[index].status) > 0) return false;
  const next = MR_STATUS_FILTER_BUTTONS.slice(index + 1).find((def) => mrStatusFilterCount(def.status) > 0);
  selectedMrStatuses.clear();
  if (next) selectedMrStatuses.add(next.status);
  return true;
}

function isMrStatusFilterActive() {
  return selectedMrStatuses.size > 0;
}

/**
 * MRステータスフィルタの選択変更をIssue一覧・MR一覧に反映する
 *
 * 選択中はIssue一覧・MR一覧の既存フィルタを隠す。
 * 選択時はIssue作成・MR作成の作成欄を閉じる。
 * リポジトリを選択し直した場合は、Issue一覧の読み込みを選択処理に任せる。
 * MR一覧はIssue一覧の読み込み後に、Issue一覧とまとめて描画し直す。
 * 再表示（失敗時も含む）の完了を待つPromiseを返す。
 */
async function onMrStatusFilterChanged() {
  updateMrStatusFilterButtons();
  const active = isMrStatusFilterActive();
  MR_STATUS_FILTER_HIDDEN_IDS.forEach((id) => (document.getElementById(id).hidden = active));
  if (active) MR_STATUS_FILTER_COLLAPSED_IDS.forEach((id) => setFoldBlockExpanded(document.getElementById(id), false));
  const reselected = refreshProjectCounts();
  if (reselected) return reselected;
  if (currentProjectId !== null) await reloadIssues().catch(() => {});
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
  if (isMrStatusFilterActive() && currentProjectId !== null) reloadIssues({ blocking: false }).catch(() => {});
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
  updateDeployButton();
  if (moveEmptyMrStatusSelection()) {
    onMrStatusFilterChanged();
    return;
  }
  updateMrStatusFilterButtons();
  refreshProjectCounts();
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
 * 使用率・リセット時刻が未受信の場合は--と表示する。
 */
function formatRateLimit(label, limit) {
  const hasUtilization = limit && limit.utilization != null;
  const percent = hasUtilization ? `${Math.round(limit.utilization * 100)}%` : RATE_LIMIT_UNKNOWN_TEXT;
  const statusClass = (limit && RATE_LIMIT_STATUS_CLASSES[limit.status]) || "";
  const resetText = limit && limit.resets_at ? formatResetTime(limit.resets_at) : RATE_LIMIT_UNKNOWN_TEXT;
  const reset = `<span class="token-usage-reset">${resetText}</span>`;
  return `<span class="token-usage-item ${statusClass}"><span class="token-usage-label">${label}</span>${percent}${reset}</span>`;
}

function formatResetTime(unixSeconds) {
  const date = new Date(unixSeconds * 1000);
  const hhmm = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? hhmm : `${date.getMonth() + 1}/${date.getDate()} ${hhmm}`;
}

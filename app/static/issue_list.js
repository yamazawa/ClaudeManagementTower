/**
 * Issue一覧
 *
 * 選択中のリポジトリのIssue一覧を取得・表示し、MR数を更新する。
 */

/**
 * Issue一覧の再読み込み
 *
 * 選択中のIssueが一覧から外れた場合は、先頭のIssueを選択し直す。
 * 表示するIssueが無い場合は、Issue・MRの表示を消してペインを閉じる。
 * Issue内容の取得後に、Issue一覧からMR内容までまとめて表示を切り替える。
 * 定期更新など操作起点でない再読み込みは、blockingをfalseにして画面をブロックしない。
 */
async function reloadIssues({ blocking = true } = {}) {
  await runSelectionRequest(
    fetchIssueListWithSelection,
    ({ issues, target }) => applyIssueList(issues, target),
    { blocking }
  );
}

/**
 * Issue一覧と、一覧の更新後に選択するIssueの内容を取得する
 */
async function fetchIssueListWithSelection() {
  return withIssueSelection(await fetchIssueList());
}

async function withIssueSelection(issues) {
  const target = await fetchIssueSelection(issues);
  return { issues, target };
}

/**
 * Issue一覧の取得
 *
 * フィルタに該当するIssueを返す。
 * MRステータスフィルタの選択中は、Open・Closeを問わず該当Issueを返す。
 * Openを取得した場合は、リポジトリ一覧のMR数の集計に使う値も更新する。
 * 取得した一覧は、リポジトリ切り替え時にすぐ表示するため保持する。
 */
async function fetchIssueList() {
  lastMatchedIssueKey = matchedIssueKey();
  const projectId = currentProjectId;
  const cacheKey = issueListCacheKey();
  const filtered = isMrStatusFilterActive();
  const state = document.getElementById("issue-filter").value;
  const issues = filtered ? await fetchIssuesByMrStatus() : await fetchIssues(state);
  if (!filtered && state === "open") setOpenIssueNumbers(projectId, issues);
  cacheIssueList(cacheKey, issues);
  return issues;
}

/**
 * 表示中のリポジトリとフィルタに対応する、Issue一覧の保持キー
 *
 * MRステータスフィルタの選択中は、絞り込み対象のIssue番号の組ごとに分ける。
 */
function issueListCacheKey() {
  if (isMrStatusFilterActive()) return `mr:${matchedIssueKey()}`;
  return stateIssueListCacheKey(currentProjectId, document.getElementById("issue-filter").value);
}

function stateIssueListCacheKey(projectId, state) {
  return `state:${projectId}:${state}`;
}

/**
 * 取得したIssue一覧を保持する
 *
 * 取得失敗時の応答（配列でない値）は保持しない。
 */
function cacheIssueList(cacheKey, issues) {
  if (Array.isArray(issues)) issueListCache.set(cacheKey, issues);
}

/**
 * Issue一覧の更新後に選択するIssueを決め、内容を取得する
 *
 * 選択中のIssueが一覧に有る場合は選択し直さない（内容は取得しない）。
 * 一覧に無い場合は先頭のIssueとし、一覧が空の場合は未選択とする。
 * Issue内容は一覧の取得値とDB上のMR一覧で組み立て、GitHubへは問い合わせない。
 */
async function fetchIssueSelection(issues) {
  if (issues.some((issue) => issue.number === currentIssueNumber)) return { number: currentIssueNumber, detail: null };
  const [first] = issues;
  if (!first) return { number: null, detail: null };
  return { number: first.number, detail: await fetchIssueContent(first) };
}

/**
 * 取得したIssue一覧と選択するIssueを表示に反映する
 *
 * 選択し直したIssueは内容とMR一覧・MR内容を描画する。
 * 選択を変えない場合も、フィルタの変更に追従させるためMR一覧を描画し直す。
 */
function applyIssueList(issues, { number, detail }) {
  if (number === null) clearIssueSelection();
  else currentIssueNumber = number;
  renderIssueList(issues);
  if (detail) showIssueDetail(detail);
  else if (number !== null) renderSubtaskList();
  refreshProjectCounts();
}

function renderIssueList(issues) {
  const listEl = document.getElementById("issue-list-items");
  listEl.innerHTML = "";
  listedIssues.clear();
  if (issues.length === 0) listEl.innerHTML = '<li class="empty">Issueがありません。</li>';
  else issues.forEach((issue) => listEl.appendChild(renderIssueItem(issue)));
}

async function fetchIssues(state) {
  return fetchProjectIssues(currentProjectId, state);
}

async function fetchProjectIssues(projectId, state) {
  return fetch(`/api/projects/${projectId}/issues?state=${encodeURIComponent(state)}`).then((r) => r.json());
}

/**
 * 選択中のステータスのMRを持つIssueを、Open・Closeの両方から取得する
 *
 * 並び順はIssue番号の降順とする。
 * 一覧に無い番号（PR番号に紐づいたMRなど）は個別に取得して表示する。
 */
async function fetchIssuesByMrStatus() {
  const numbers = new Set(matchedIssueNumbers());
  if (numbers.size === 0) return [];
  const lists = await Promise.all(ISSUE_STATES.map(fetchIssues));
  const listed = lists.flat().filter((issue) => numbers.has(issue.number));
  const listedNumbers = new Set(listed.map((issue) => issue.number));
  const missing = [...numbers].filter((number) => !listedNumbers.has(number));
  const extra = await Promise.all(missing.map(fetchUnlistedIssue));
  return [...listed, ...extra].sort((a, b) => b.number - a.number);
}

/**
 * Issue一覧APIに含まれない番号を個別に取得する
 *
 * 取得に失敗した場合も、MRへ辿れるよう番号だけの行にする。
 */
async function fetchUnlistedIssue(number) {
  const response = await fetch(`/api/projects/${currentProjectId}/issues/${number}`);
  const detail = response.ok ? await response.json() : { number, title: `#${number}`, state: "CLOSED" };
  const subtasks = detail.subtasks || [];
  return { number, title: detail.title, state: detail.state, url: detail.url, mr_counts: countMrs(subtasks) };
}

/**
 * Issue一覧の1行
 *
 * 見出しと同様に番号リンク・1行省略のタイトル・閉じるボタンを並べる。
 * リンクとボタンのクリックではIssueを選択しない。
 */
function renderIssueItem(issue) {
  listedIssues.set(issue.number, toIssueSummary(issue));
  const li = document.createElement("li");
  li.className = "issue-item";
  li.classList.toggle("active", issue.number === currentIssueNumber);
  li.dataset.number = issue.number;
  li.dataset.state = issue.state;
  li.innerHTML = `
    ${renderTitleNumber("Issue", issue.url)}
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
  button.textContent = isOpen ? "Close" : "ReOpen";
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
 * 一覧の再取得が終わるまで更新中を表示する。
 */
async function toggleIssue(number, isOpen, button) {
  const verb = isOpen ? "閉じ" : "再開し";
  if (!confirm(`Issue #${number} を${verb}ますか？`)) return;
  await runBusyAction(async () => {
    await postIssueToggle(number, isOpen, button, verb);
    await reloadIssues();
  });
}

/**
 * Issueを閉じる・再開する要求を送り、結果を表示する
 */
async function postIssueToggle(number, isOpen, button, verb) {
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
}

/**
 * Issue名の保存
 *
 * Issue見出し・MR見出しのどちらからも呼ばれる。
 * サーバー側で紐づくMR名も書き換わるため、MR一覧とMR見出しを描画し直す。
 * MR名の書き換えに失敗したMRがあれば件数を表示する。
 */
async function saveIssueTitle(number, title) {
  const { error, body } = await patchTitle(
    `/api/projects/${currentProjectId}/issues/${number}`,
    title
  );
  if (error) return error;
  updateIssueTitleDisplay(number, title);
  if (number !== currentIssueNumber) return null;
  const failedCount = (body.failed_subtasks || []).length;
  const renameStatus = document.getElementById("issue-rename-status");
  if (renameStatus)
    renameStatus.textContent = failedCount > 0 ? `MR名の書き換えに${failedCount}件失敗しました` : "";
  await refreshSubtaskStates().catch(() => {});
  refreshSelectedSubtaskTitle();
  return null;
}

/**
 * Issue一覧の行・Issue見出しのIssue名を差し替える
 *
 * Issue見出しは表示中のIssueの場合のみ差し替える。
 */
function updateIssueTitleDisplay(number, title) {
  const listed = listedIssues.get(number);
  if (listed) listed.title = title;
  const itemTitle = document.querySelector(`.issue-item[data-number="${number}"] .issue-item-title`);
  if (itemTitle) {
    itemTitle.textContent = title;
    itemTitle.title = title;
  }
  const headingTitle = document.getElementById("issue-title");
  if (number !== currentIssueNumber || !headingTitle) return;
  headingTitle.textContent = title;
  updateTitleTooltip(headingTitle);
  currentIssueTitle = title;
  updateSubtaskFormPrefix();
}

/**
 * Issueの選択
 *
 * Issue内容の取得後に、Issue一覧の選択表示からMR内容までまとめて切り替える。
 * Issue一覧に表示中の場合は、一覧の取得値とDB上のMR一覧で内容を組み立てる。
 * 一覧に無い場合のみ、GitHubへ問い合わせる詳細APIで取得する。
 */
async function selectIssue(number) {
  const listed = listedIssues.get(number);
  await runSelectionRequest(
    () => (listed ? fetchIssueContent(listed) : fetchIssueDetail(number)),
    (detail) => {
      currentIssueNumber = number;
      highlightSelectedIssue();
      showIssueDetail(detail);
    }
  );
}

function highlightSelectedIssue() {
  document
    .querySelectorAll(".issue-item")
    .forEach((el) => el.classList.toggle("active", Number(el.dataset.number) === currentIssueNumber));
}

/**
 * 選択し直したIssueの内容を表示する
 *
 * MR一覧に表示中の先頭MRを自動選択する。
 * 表示中のMRが無い場合は未選択とし、MR内容を非表示にする。
 */
function showIssueDetail(issue) {
  currentSelectedSubtaskId = null;
  renderIssueDetail(issue);
  setSectionShown(SECTION_IDS.issue, true);
}

/**
 * GitHubへ問い合わせてIssue内容を取得する
 *
 * Issue一覧に無い番号の取得に限って使う。
 */
async function fetchIssueDetail(number) {
  return fetch(`/api/projects/${currentProjectId}/issues/${number}`).then((r) => r.json());
}

/**
 * Issue内容の組み立て
 *
 * 取得済みの番号・タイトル・状態・URLに、DB上のMR一覧を合わせる。
 * GitHubへは問い合わせない。
 */
async function fetchIssueContent(issue) {
  const subtasks = await fetchIssueSubtasks(currentProjectId, issue.number);
  return { ...toIssueSummary(issue), subtasks };
}

function toIssueSummary(issue) {
  return { number: issue.number, title: issue.title, state: issue.state, url: issue.url };
}

/**
 * DB上のMR一覧の取得（GitHubへは問い合わせない）
 */
async function fetchIssueSubtasks(projectId, issueNumber) {
  const response = await fetch(`/api/projects/${projectId}/issues/${issueNumber}/subtasks`);
  if (!response.ok) throw new Error(`MR一覧の取得に失敗しました: ${response.status}`);
  return response.json();
}

/**
 * 選択中のIssueの内容を取得し直して描画する
 *
 * 見出しは表示中の値を使い、MR一覧のみDBから取得し直す。
 * MRの選択は、MR一覧に表示中であれば維持する。
 */
async function refreshIssueDetail() {
  const issueNumber = currentIssueNumber;
  const issue = await fetchIssueContent({
    number: issueNumber,
    title: currentIssueTitle,
    state: currentIssueState,
    url: currentIssueUrl,
  });
  if (issueNumber !== currentIssueNumber) return;
  renderIssueDetail(issue);
}

/**
 * Issue内容（見出し・MR作成フォーム・MR一覧）の描画
 */
function renderIssueDetail(issue) {
  currentSubtasks = issue.subtasks;
  currentIssueTitle = issue.title;
  currentIssueUrl = issue.url;
  updateIssueMrCounts(issue.number, issue.subtasks);

  document.getElementById("issue-heading").innerHTML =
    `${renderTitleNumber("Issue", issue.url)}<span id="issue-title">${escapeHtml(issue.title)}</span>` +
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

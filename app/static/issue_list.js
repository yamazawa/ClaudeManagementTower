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

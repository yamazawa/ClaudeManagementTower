/**
 * リポジトリ一覧・Issue/MRの作成と画面の初期化
 *
 * 機能単位のファイルを読み込んだ後に読み込み、画面を初期化する。
 */

// 登録済みのリポジトリ（/api/projectsの応答）
let allProjects = [];
// リポジトリIDごとのOpenなIssue番号（取得前のリポジトリは含めない）
const openIssueNumbersByProject = new Map();
const OPEN_ISSUES_POLL_MS = 60000;
// リポジトリとフィルタの組ごとに最後に取得したIssue一覧（キーはissueListCacheKeyの値）
const issueListCache = new Map();
// リポジトリ一覧のMR数で解決済とみなす表示ステータス（それ以外は未解決とする）
const MR_STATUS_RESOLVED = [MR_STATUS.merged, MR_STATUS.deploying, MR_STATUS.deployed];
const PROJECT_COUNT_TOOLTIP = "OpenなIssueの未解決MR数 / 解決済MR数";
const PROJECT_COUNT_FILTERED_TOOLTIP = "OpenなIssueで、選択中のステータスのMR数";
const PROJECT_LIST_NO_PROJECT_TEXT = "リポジトリが登録されていません。";
const PROJECT_LIST_NO_MATCH_TEXT = "選択中のステータスのMRを持つリポジトリはありません。";

/**
 * Issueの選択を外し、Issue・MRを未選択の表示に戻す
 *
 * Issue内容・MR内容のペインは非表示にする。
 */
function clearIssueSelection() {
  currentIssueNumber = null;
  currentIssueState = null;
  currentIssueTitle = null;
  currentIssueUrl = null;
  currentSubtasks = [];
  currentSelectedSubtaskId = null;
  highlightSelectedIssue();
  document.getElementById("issue-heading").textContent = "Issue";
  document.getElementById("subtask-list-body").innerHTML =
    '<p class="empty">一覧からIssueを選択してください。</p>';
  document.getElementById("subtask-panel").hidden = true;
  setSectionShown(SECTION_IDS.issue, false);
  renderSubtaskDetail(null);
}

/**
 * リポジトリの選択を外し、Issue一覧以降を未選択の表示に戻す
 *
 * Issue一覧・Issue内容・MR内容のペインは非表示にする。
 * CLI・Ideaの選択も外す。
 */
function clearProjectSelection() {
  nextSelectionRequest();
  currentProjectId = null;
  highlightSelectedProject();
  document.getElementById("repo-heading").textContent = "Repo";
  document.getElementById("issue-list-placeholder").hidden = false;
  document.getElementById("repo-panel").hidden = true;
  document.getElementById("issue-list-items").innerHTML = "";
  setSectionShown(SECTION_IDS.repo, false);
  clearIssueSelection();
  clearRepoItemSelection();
}

async function init() {
  allProjects = await fetch("/api/projects").then((r) => r.json());
  const listEl = document.getElementById("project-list-items");
  listEl.innerHTML = "";
  if (allProjects.length === 0) listEl.innerHTML = `<li class="empty">${PROJECT_LIST_NO_PROJECT_TEXT}</li>`;
  else renderProjectItems(listEl);
  pollOpenIssues();
  pollRateLimits();
  pollMrStatuses();
  pollSubtaskStates();
}

/**
 * リポジトリの選択
 *
 * Issue一覧と先頭Issueの内容を取得してから、MR内容までまとめて表示を切り替える。
 * 前回取得したIssue一覧を保持している場合は、それをすぐ表示する。
 * その後、画面をブロックせずに最新の一覧を取得して差し替える。
 * 保持している一覧が無い場合のみ、画面をブロックして取得する。
 * 再取得の前に別リポジトリへ切り替えた場合は、再取得しない。
 * 別リポジトリへ切り替えた場合は、前のIssue・MR・CLI・Ideaの選択を外す。
 */
async function selectProject(project) {
  if (project.id !== currentProjectId) {
    currentIssueNumber = null;
    clearRepoItemSelection();
  }
  currentProjectId = project.id;
  const apply = ({ issues, target }) => {
    showProject(project);
    applyIssueList(issues, target);
  };
  const cached = issueListCache.get(issueListCacheKey());
  if (!cached) return runSelectionRequest(fetchIssueListWithSelection, apply);
  await runSelectionRequest(() => withIssueSelection(cached), apply, { blocking: false });
  if (currentProjectId === project.id) await reloadIssues({ blocking: false });
}

/**
 * 選択したリポジトリの見出しとIssue一覧のペインを表示する
 *
 * CLI・Ideaのタブの表示中は、その一覧も取得し直す。
 */
function showProject(project) {
  highlightSelectedProject();
  setSectionShown(SECTION_IDS.repo, true);
  document.getElementById("issue-list-placeholder").hidden = true;
  document.getElementById("repo-panel").hidden = false;
  renderRepoHeading(project);
  onRepoItemProjectShown();
}

function highlightSelectedProject() {
  document
    .querySelectorAll(".project-item")
    .forEach((li) => li.classList.toggle("active", Number(li.dataset.projectId) === currentProjectId));
}

/**
 * リポジトリ一覧の各行と、フィルタで全て隠れた場合の文言を並べる
 */
function renderProjectItems(listEl) {
  allProjects.forEach((project) => listEl.appendChild(renderProjectItem(project)));
  listEl.insertAdjacentHTML("beforeend", `<li id="project-list-no-match" class="empty" hidden>${PROJECT_LIST_NO_MATCH_TEXT}</li>`);
}

/**
 * リポジトリ一覧の1行
 *
 * 「表示名 MR数」を並べる。
 */
function renderProjectItem(project) {
  const li = document.createElement("li");
  li.className = "project-item";
  li.dataset.projectId = project.id;
  li.innerHTML =
    `<span class="project-name" title="${escapeAttr(project.display_name)}">${escapeHtml(project.display_name)}</span>` +
    `<span class="project-count"></span>`;
  li.addEventListener("click", () => selectProject(project));
  return li;
}

/**
 * 全リポジトリのOpenなIssue番号の定期取得
 *
 * GitHubへの問い合わせを伴うため、MR状態の集計より長い間隔で取得する。
 * 取得したOpen一覧は、リポジトリ切り替え時の表示用にも保持する。
 */
async function pollOpenIssues() {
  await Promise.all(allProjects.map((project) => refreshOpenIssueNumbers(project.id)));
  refreshProjectCounts();
  setTimeout(pollOpenIssues, OPEN_ISSUES_POLL_MS);
}

async function refreshOpenIssueNumbers(projectId) {
  try {
    const issues = await fetchProjectIssues(projectId, "open");
    setOpenIssueNumbers(projectId, issues);
    cacheIssueList(stateIssueListCacheKey(projectId, "open"), issues);
  } catch (error) {
    // サーバー再起動中などで取得に失敗した場合は前回の値のまま表示する
  }
}

function setOpenIssueNumbers(projectId, issues) {
  openIssueNumbersByProject.set(projectId, new Set(issues.map((issue) => issue.number)));
}

/**
 * リポジトリのOpenなIssueが持つMRのうち、条件に合うステータスのMR数を数える
 */
function countOpenIssueMrs(projectId, matchesStatus) {
  const openNumbers = openIssueNumbersByProject.get(projectId) || new Set();
  return Object.entries(mrStatusSummary.projects[projectId] || {})
    .filter(([number]) => openNumbers.has(Number(number)))
    .flatMap(([, statusCounts]) => Object.entries(statusCounts))
    .filter(([status]) => matchesStatus(status))
    .reduce((sum, [, count]) => sum + count, 0);
}

function countSelectedStatusOpenIssueMrs(projectId) {
  return countOpenIssueMrs(projectId, (status) => selectedMrStatuses.has(status));
}

/**
 * リポジトリのMR数表示
 *
 * 通常は「未解決MR数/解決済MR数」とする。
 * MRステータスフィルタの選択中は、選択中のステータスのMR数とする。
 * OpenなIssue番号の取得前は表示しない。
 */
function projectCountText(projectId) {
  if (!openIssueNumbersByProject.has(projectId)) return "";
  if (isMrStatusFilterActive()) return String(countSelectedStatusOpenIssueMrs(projectId));
  const unresolved = countOpenIssueMrs(projectId, (status) => !MR_STATUS_RESOLVED.includes(status));
  const resolved = countOpenIssueMrs(projectId, (status) => MR_STATUS_RESOLVED.includes(status));
  return `${unresolved}/${resolved}`;
}

/**
 * MRステータスフィルタの選択中に、該当MRが0件のリポジトリか
 *
 * OpenなIssue番号の取得前は判定できないため表示する。
 */
function isProjectFilteredOut(projectId) {
  if (!isMrStatusFilterActive() || !openIssueNumbersByProject.has(projectId)) return false;
  return countSelectedStatusOpenIssueMrs(projectId) === 0;
}

function renderProjectItemCount(li) {
  const projectId = Number(li.dataset.projectId);
  const el = li.querySelector(".project-count");
  el.textContent = projectCountText(projectId);
  el.title = isMrStatusFilterActive() ? PROJECT_COUNT_FILTERED_TOOLTIP : PROJECT_COUNT_TOOLTIP;
  li.hidden = isProjectFilteredOut(projectId);
}

/**
 * リポジトリ一覧のMR数・表示有無を更新する
 *
 * MRステータスフィルタの選択中は、該当MRが0件のリポジトリを隠す。
 * 選択の変更有無はselectFirstVisibleProjectの戻り値で返す。
 */
function refreshProjectCounts() {
  const items = [...document.querySelectorAll(".project-item")];
  items.forEach(renderProjectItemCount);
  const noMatch = document.getElementById("project-list-no-match");
  if (noMatch) noMatch.hidden = items.some((li) => !li.hidden);
  return selectFirstVisibleProject(items);
}

/**
 * 選択中のリポジトリが非表示になった場合に、表示中の先頭のリポジトリを選択し直す
 *
 * 選択中のリポジトリが表示中の場合は選択し直さない。
 * 未選択の場合は、MRステータスフィルタの選択中のみ先頭を選択する。
 * 表示中のリポジトリが無い場合は選択を外す。
 * 選択を変更しない場合はfalseを返す。
 * 選び直した場合は選択の完了を待つPromise、選択を外した場合はtrueを返す。
 */
function selectFirstVisibleProject(items) {
  const visible = items.filter((li) => !li.hidden);
  if (visible.some((li) => Number(li.dataset.projectId) === currentProjectId)) return false;
  if (currentProjectId === null && !isMrStatusFilterActive()) return false;
  const [first] = visible;
  if (!first) return clearVisibleProjectSelection();
  const project = allProjects.find((p) => p.id === Number(first.dataset.projectId));
  return selectProject(project).catch(() => {});
}

function clearVisibleProjectSelection() {
  if (currentProjectId === null) return false;
  clearProjectSelection();
  return true;
}

/**
 * リポジトリ見出しの表示
 *
 * 「Repo 表示名」とし、「Repo」部分はGitHubのリポジトリページへのリンクにする。
 */
function renderRepoHeading(project) {
  document.getElementById("repo-heading").innerHTML =
    `${renderTitleNumber("Repo", project.repo_url)}<span id="repo-title">${escapeHtml(project.display_name)}</span>`;
}

/**
 * Issue作成フォームの送信
 *
 * 作成したIssueとMRを開くまで更新中を表示する。
 */
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
    await runBusyAction(() => createAndOpenIssue(form, projectId, title, statusEl));
  } finally {
    form.querySelector("button").disabled = false;
  }
}

/**
 * IssueとMRを作成し、作成したIssueとMRを開く
 *
 * 作成中に別プロジェクトへ切り替えた場合は開かない。
 */
async function createAndOpenIssue(form, projectId, title, statusEl) {
  const created = await createIssueWithSubtask(projectId, title, statusEl);
  if (!created) return;
  if (form.title.value === title) form.reset();
  collapseCreatedIssueForm(form, statusEl, created);
  if (projectId === currentProjectId) await openCreatedIssueAndSubtask(created.issue, created.subtaskId);
}

/**
 * IssueとMRの作成完了後にIssue作成欄を閉じる
 *
 * MR作成のみ失敗した場合は、失敗の表示を残すため閉じない。
 * 次に開いた時に完了表示が残らないよう、状態表示を消す。
 */
function collapseCreatedIssueForm(form, statusEl, created) {
  if (created.subtaskId === null) return;
  statusEl.textContent = "";
  collapseFoldBlock(form);
}

/**
 * IssueとMRの作成
 *
 * 高速化のため、Issue作成とMR作成を並行して行い、MRへのIssue紐付けは後から行う。
 * 作成中は画面を更新せず、作成完了後にまとめて反映する。
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
 * 高速化のため、Issue一覧と作成したIssueの内容を並行して取得する。
 * Issue内容は作成結果とDB上のMR一覧で組み立て、GitHubへは問い合わせない。
 * GitHubの一覧反映が遅れても、作成したIssueを選択する。
 * MRの指示内容の入力欄にフォーカスし、画面の一番下までスクロールする。
 * MR作成に失敗した場合はIssueのみ開く。
 */
async function openCreatedIssueAndSubtask(issue, subtaskId) {
  const requestId = nextSelectionRequest();
  const created = { ...issue, state: "OPEN" };
  const fetched = await Promise.all([fetchIssueList(), fetchIssueContent(created)]).catch(() => null);
  if (!fetched || !isLatestSelectionRequest(requestId)) return;
  const [issues, detail] = fetched;
  applyIssueList(issues, { number: issue.number, detail });
  supplementCreatedIssue(issue);
  if (subtaskId === null || issue.number !== currentIssueNumber) return;
  showCreatedSubtask(subtaskId);
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

/**
 * MR作成フォームの送信
 *
 * 作成したMRを開くまで更新中を表示する。
 */
async function onSubmitSubtaskForm(event) {
  event.preventDefault();
  if (isCurrentIssueAutoMrCreating()) return;
  const form = event.target;
  const statusEl = document.getElementById("subtask-form-status");
  const title = form.title.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const issueNumber = currentIssueNumber;
  await runBusyAction(async () => {
    const { body, error } = await createSubtask(issueNumber, title);
    if (error) {
      statusEl.textContent = `失敗しました: ${error}`;
      form.querySelector("button").disabled = false;
      return;
    }
    collapseFoldBlock(form);
    await openCreatedSubtask(issueNumber, body.id);
  });
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
 */
async function openCreatedSubtask(issueNumber, subtaskId) {
  if (issueNumber === currentIssueNumber) {
    await refreshSubtaskStates();
    resetSubtaskForm();
  } else {
    await selectIssue(issueNumber);
  }
  if (issueNumber !== currentIssueNumber) return;
  showCreatedSubtask(subtaskId);
}

/**
 * 作成したMRを選択し、指示内容の入力欄を見せる
 *
 * 入力欄にフォーカスし、画面の一番下までスクロールする。
 */
function showCreatedSubtask(subtaskId) {
  selectSubtask(subtaskId);
  document.getElementById(`instruction-${subtaskId}`)?.focus({ preventScroll: true });
  scrollToPageBottom();
}

/**
 * 画面の一番下までスクロールする
 */
function scrollToPageBottom() {
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
}

setupHeaderOffset();
setupFoldExpanders();
setupMrStatusFilter();
updateDeployButton();
document.getElementById("deploy-button").addEventListener("click", openDeployDialog);
document.getElementById("deploy-dialog-list").addEventListener("change", updateDeployDialogConfirm);
document.getElementById("deploy-dialog-cancel").addEventListener("click", () => document.getElementById("deploy-dialog").close());
document.getElementById("deploy-dialog-confirm").addEventListener("click", onConfirmDeployDialog);
document.getElementById("issue-create-form").addEventListener("submit", onSubmitIssueForm);
document.getElementById("issue-filter").addEventListener("change", () => reloadIssues().catch(() => {}));
document.getElementById("subtask-filter").addEventListener("change", renderSubtaskList);
document.getElementById("subtask-form").addEventListener("submit", onSubmitSubtaskForm);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  refreshSubtaskStates().catch(() => {});
});

init();

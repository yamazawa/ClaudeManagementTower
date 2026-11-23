/**
 * MR一覧・MR内容
 *
 * 選択中のIssueのMR一覧・MR内容を表示し、MRの状態に応じた操作を行う。
 */

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
  ensureSubtaskSelection(subtasks);
}

/**
 * 選択中のMRがMR一覧から外れた場合に、先頭のMRを選択し直す
 *
 * 選択中のMRが表示中の場合は選択し直さない。
 * 表示するMRが無い場合は、MR内容の表示を消してペインを閉じる。
 */
function ensureSubtaskSelection(visibleSubtasks) {
  if (visibleSubtasks.some((s) => s.id === currentSelectedSubtaskId)) return;
  const [first] = visibleSubtasks;
  if (first) selectSubtask(first.id);
  else clearSubtaskSelection();
}

/**
 * MRの選択を外し、MR未選択の表示に戻す
 *
 * 未選択のまま一覧を描画し直した場合は、MR内容を描画し直さない。
 */
function clearSubtaskSelection() {
  if (currentSelectedSubtaskId === null && !isSubtaskDetailShown()) return;
  currentSelectedSubtaskId = null;
  highlightSelectedSubtaskRow();
  renderSubtaskDetail(null);
}

function isSubtaskDetailShown() {
  return document.getElementById("subtask-actions") !== null;
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
 * MR名の保存
 *
 * 編集対象はMR固有名のみ。保存後は命名規則に沿うため見出しを描画し直す。
 */
async function saveSubtaskTitle(subtaskId, suffix) {
  const { error } = await patchTitle(`/api/subtasks/${subtaskId}`, suffix);
  if (error) return error;
  await refreshSubtaskStates().catch(() => {});
  refreshSelectedSubtaskTitle();
  return null;
}

/**
 * 選択中MRの見出しタイトルを描画し直す
 *
 * 編集中（テキストボックス表示中）は描画し直さない。
 */
function refreshSelectedSubtaskTitle() {
  const titleEl = document.getElementById("subtask-title");
  const selected = currentSubtasks.find((s) => s.id === currentSelectedSubtaskId);
  if (!titleEl || !selected || titleEl.querySelector(".title-input")) return;
  titleEl.outerHTML = renderMrTitle(selected, { id: "subtask-title" });
  setupSubtaskTitleEditing(selected.id);
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
 * 状態ごとの色分け用に、状態名のクラスを付ける。
 */
function renderSubtaskState(s) {
  const status = mrStatus(s);
  const label = MR_STATUS_LABELS[status] || status;
  const merge = s.latest_merge;
  const showFailure = status === MR_STATUS.resolved && merge && merge.status === MERGE_STATUS.failed;
  const suffix = showFailure ? `（${MERGE_STATUS_LABELS[merge.status]}）` : "";
  const tooltipText = showFailure ? merge.error_message : mrStatusTooltip(status, merge);
  const tooltip = tooltipText ? ` title="${escapeAttr(tooltipText)}"` : "";
  const className = subtaskStateClassName(status, showFailure);
  return `<span class="${className}"${tooltip}>${label}${suffix}</span>`;
}

/**
 * MRの状態表示のクラス名
 *
 * マージ失敗を併記する場合は警告色のクラスを足す。
 */
function subtaskStateClassName(status, showFailure) {
  const classes = ["subtask-state", `state-${escapeAttr(status)}`];
  if (showFailure) classes.push("state-merge-failed");
  return classes.join(" ");
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
 * 見出しの種別表示
 *
 * URLがある場合はGitHubを開くリンクにする。
 */
function renderTitleNumber(label, url) {
  if (!url) return `<span class="title-number">${label}</span>`;
  return `<a class="title-number" href="${url}" target="_blank" rel="noopener" title="GitHubで開く">${label}</a>`;
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

/* MR作成フォームの初期化

フォームはIssue切り替え後も使い回すため、入力値と状態表示を初期状態に戻す。
MR自動作成中は作成ボタンを無効のままにする。
*/
function resetSubtaskForm() {
  const form = document.getElementById("subtask-form");
  form.reset();
  form.title.value = nextDefaultMrSuffix();
  form.querySelector("button").disabled = isCurrentIssueAutoMrCreating();
  document.getElementById("subtask-form-status").textContent = "";
  updateSubtaskFormPrefix();
}

/**
 * MR作成フォームの「Issue名ー」表示を更新する
 *
 * 省略表示時も区切り文字が残るよう、Issue名と区切り文字を別要素に設定する。
 */
function updateSubtaskFormPrefix() {
  const prefixEl = document.getElementById("subtask-form-prefix");
  document.getElementById("subtask-form-prefix-title").textContent = currentIssueTitle;
  document.getElementById("subtask-form-prefix-separator").textContent = MR_NAME_SEPARATOR;
  prefixEl.title = currentIssueTitle;
}

/**
 * MR作成フォームに初期入力するMR固有名
 *
 * ①から順に走査し、表示中IssueのMR名と重複しない最初の番号を返す。
 * サーバー側で空欄時に割り当てる連番（core/mr_naming.py）と合わせる。
 */
function nextDefaultMrSuffix() {
  const used = new Set(currentSubtasks.map((s) => s.title));
  let n = 1;
  while (used.has(`${currentIssueTitle}${MR_NAME_SEPARATOR}${numberLabel(n)}`)) n++;
  return numberLabel(n);
}

/**
 * 連番の表示文字列
 *
 * 丸数字が無い番号は半角数字にする。
 */
function numberLabel(n) {
  const range = CIRCLED_NUMBER_RANGES.find((r) => r.first <= n && n <= r.last);
  return range ? String.fromCodePoint(range.base + n - range.first) : String(n);
}

function selectSubtask(subtaskId) {
  currentSelectedSubtaskId = subtaskId;
  highlightSelectedSubtaskRow();
  const subtask = currentSubtasks.find((s) => s.id === subtaskId) || null;
  renderSubtaskDetail(subtask);
}

/**
 * MR見出しの種別表示
 *
 * PR作成前はリンクにせず「MR」のみ表示する。
 */
function renderSubtaskNumber(s) {
  return renderTitleNumber("MR", s.pr_url);
}

function renderSubtaskDetail(s) {
  const el = document.getElementById("subtask-detail-body");
  const heading = document.getElementById("subtask-heading");
  if (!s) {
    heading.textContent = "MR";
    el.innerHTML = '<p class="empty">一覧からMRを選択してください。</p>';
    setSectionShown(SECTION_IDS.mr, false);
    return;
  }
  setSectionShown(SECTION_IDS.mr, true);

  heading.innerHTML =
    `${renderSubtaskNumber(s)}${renderMrTitle(s, { id: "subtask-title" })}${renderSubtaskState(s)}`;
  el.innerHTML = `
    <p id="subtask-title-status" class="title-status empty"></p>
    <div class="instruction-form">
      <div class="attachment-area">
        <button type="button" id="attach-file-button" class="subtask-action-button attach-button">ファイル添付</button>
        <button type="button" id="attach-image-button" class="subtask-action-button attach-button">画像添付</button>
        <input type="file" id="attach-file-input" multiple hidden />
        <input type="file" id="attach-image-input" accept="image/*" hidden />
        <span id="attachment-status" class="empty"></span>
      </div>
      <div id="attachment-list" data-subtask-id="${s.id}"></div>
      <textarea id="instruction-${s.id}" name="instruction" aria-label="指示内容" placeholder="Claudeへの指示内容を入力してください（添付ファイルはS1、S2などのIDで指定できます）">${escapeHtml(s.instruction)}</textarea>
      <div id="subtask-actions" class="subtask-actions" data-subtask-id="${s.id}"></div>
    </div>
    <p id="subtask-action-status" class="title-status empty"></p>
    <p class="job-status empty" data-subtask-id="${s.id}"></p>
    <iframe class="report-frame" sandbox="" data-subtask-id="${s.id}" hidden></iframe>
  `;

  renderSubtaskActions(s);
  setupSubtaskTitleEditing(s.id);
  setupAttachmentForm(s.id);

  restoreJobState(s);
}

/**
 * MR見出しのタイトル編集の初期化
 *
 * Issue名とMR固有名をそれぞれクリックして別々に編集する。
 * Issue名の編集はIssue名の変更（紐づくMR名の書き換えを含む）とする。
 * 命名規則に沿わない場合は全体をクリックしてMR固有名を編集する。
 */
function setupSubtaskTitleEditing(subtaskId) {
  const titleEl = document.getElementById("subtask-title");
  const statusEl = document.getElementById("subtask-title-status");
  const issueEl = titleEl.querySelector(".mr-title-issue");
  const suffixEl = titleEl.querySelector(".mr-title-suffix, .mr-title-whole");
  const issueNumber = currentIssueNumber;
  if (issueEl) makeTitleEditable(issueEl, statusEl, (title) => saveIssueTitle(issueNumber, title));
  makeTitleEditable(suffixEl, statusEl, (title) => saveSubtaskTitle(subtaskId, title));
}

function restoreJobState(s) {
  const job = s.latest_job;
  if (!job) {
    return;
  }

  const statusEl = document.querySelector(`.job-status[data-subtask-id="${s.id}"]`);
  renderJobStatus(statusEl, job);

  if (isJobActive(job)) {
    pollJob(job.id, s.id);
    return;
  }

  if (job.status === JOB_STATUS.succeeded && job.has_report) {
    showReport(job.id, s.id);
  }
}

async function pollSubtaskStates() {
  try {
    if (!document.hidden) {
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
  const subtasks = await fetchIssueSubtasks(projectId, issueNumber);
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
 * 実装ジョブの状態表示
 *
 * 状態を日本語で表示し、状態ごとの見た目のクラスを付ける。
 * 失敗理由がある場合は状態の下に表示し、ツールチップに全文を出す。
 */
function renderJobStatus(statusEl, job) {
  const label = JOB_STATUS_LABELS[job.status] || job.status;
  setJobStatusText(statusEl, `${JOB_STATUS_PREFIX}${label}`, JOB_STATUS_CLASSES[job.status]);
  if (JOB_STATUS_CLASSES[job.status] !== JOB_STATUS_CLASS.warning || !job.error_message) return;
  const errorEl = document.createElement("span");
  errorEl.className = JOB_STATUS_ERROR_CLASS;
  errorEl.textContent = job.error_message;
  errorEl.title = job.error_message;
  statusEl.appendChild(errorEl);
}

/**
 * ジョブ状態欄の文言と見た目を差し替える
 *
 * 見た目のクラスを指定しない場合は補足の文言として薄く表示する。
 */
function setJobStatusText(statusEl, text, statusClass = null) {
  statusEl.classList.remove(...Object.values(JOB_STATUS_CLASS));
  if (statusClass) statusEl.classList.add(statusClass);
  statusEl.classList.toggle("empty", !statusClass);
  statusEl.textContent = text;
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
 * 要求の応答待ちの間は更新中を表示する。
 */
async function runSubtaskStateAction(subtask, def) {
  if (!confirm(`MR「${subtask.title}」${def.confirm}`)) return;
  const statusEl = document.getElementById("subtask-action-status");
  setSubtaskBusy(subtask.id, true);
  statusEl.textContent = def.progress;
  const { body, error } = await runBusyAction(() => postAction(`/api/subtasks/${subtask.id}/${def.path}`));
  const latest = currentSubtasks.find((s) => s.id === subtask.id);
  if (!error && latest) latest.lifecycle_state = body.lifecycle_state;
  if (!error && latest && body.latest_merge) latest.latest_merge = body.latest_merge;
  if (!error && body.latest_merge) refreshMrStatuses().catch(() => {});
  busySubtaskIds.delete(subtask.id);
  updateIssueMrCounts(currentIssueNumber, currentSubtasks);
  renderSubtaskList();
  refreshSelectedSubtaskState();
  if (statusEl.isConnected) statusEl.textContent = error ? `失敗しました: ${error}` : def.done;
}

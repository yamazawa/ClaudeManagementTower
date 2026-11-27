/**
 * Ideaタブの項目の内容（アイデアマン）
 *
 * 項目ごとにアイデア出しを実行し、提案を確認・承認・却下する。
 * アイデア出しの実行時は、アイデアを出してほしい観点を任意で指定できる。
 * 提案は未処理／承認済み／却下済みのタブに分けて表示する。
 * アイデア出しの実行中は、項目を一定間隔で取得して状態を表示する。
 * 画面構成はMR内容と揃え、観点の入力欄・実行ボタン・状態表示・提案一覧の順に並べる。
 */

// アイデア出し実行中の項目の取得間隔
const IDEA_VIEW_POLL_MS = 3000;

// 提案一覧のタブ（app/routes/ideas.pyのtabと合わせる）
const IDEA_TABS = [
  { tab: "pending", label: "未処理" },
  { tab: "approved", label: "承認済み" },
  { tab: "rejected", label: "却下済み" },
];
// 承認の種類（core/idea_approval.pyのApprovalModeと合わせる）
// 画面からはMRまで作成する承認のみ行う
const IDEA_APPROVAL_MODES = { withSubtask: "with_subtask" };
// アイデア出しジョブの実行中の状態（core/idea_queue.pyのIdeaJobStatusと合わせる）
const IDEA_JOB_ACTIVE_STATUSES = ["queued", "running"];
// 承認・却下の操作を置く提案の状態（core/ideas.pyのIdeaStatusと合わせる）
const IDEA_STATUS_PROPOSED = "proposed";
// 後からサブタスクを作成できる提案の状態（core/ideas.pyのIdeaStatusと合わせる）
const IDEA_STATUS_ISSUE_CREATED = "issue_created";

const IDEA_CATEGORY_LABELS = {
  bug: "不具合",
  feature: "機能",
  refactor: "リファクタ",
  tech_debt: "技術的負債",
  docs: "ドキュメント",
};
const IDEA_STATUS_LABELS = {
  proposed: "未処理",
  approved_issue_only: "Issue作成中",
  approved_with_subtask: "サブタスク作成中",
  rejected: "却下",
  issue_created: "Issue作成済",
  subtask_created: "サブタスク作成済",
};
const IDEA_JOB_STATUS_LABELS = {
  queued: "アイデア出し待機中...",
  running: "アイデア出し実行中...",
  succeeded: "前回のアイデア出し：完了",
  failed: "前回のアイデア出し：失敗",
  needs_attention: "前回のアイデア出し：要確認",
  rate_limited: "前回のアイデア出し：利用上限で中断",
};
// Idea一覧の行に表示するジョブの状態
const IDEA_JOB_ROW_LABELS = {
  queued: "待機中",
  running: "実行中",
};

const IDEA_VIEW_MESSAGES = {
  focusPlaceholder: "アイデアを出してほしい観点（任意）　例：テスト不足の箇所、エラー処理の抜け漏れ",
  execute: "そのまま実装に進む",
  run: "アイデア出し実行",
  closed: "Closeの項目ではアイデア出しを実行できません（ReOpenすると実行できます）。",
  empty: "提案はありません。",
  loadFailed: "提案一覧を取得できませんでした",
  runFailed: "アイデア出しを開始できませんでした",
  actionFailed: "操作に失敗しました",
  detail: "詳細",
  rationale: "根拠",
  relatedFiles: "関連ファイル",
  relatedIssue: (n) => `対象Issue #${n}`,
  createdIssue: (n) => `作成したIssue #${n}`,
  rejectReason: (r) => `却下理由：${r}`,
  rejectPlaceholder: "却下理由（任意・次回の提案に反映）",
  createWithSubtask: "Issue・MRを作成",
  createSubtaskOnly: "MRを作成",
  reject: "却下",
  confirmWithSubtask: (t) => `提案「${t}」でIssue・MR（Draft PR）を作成しますか？`,
  confirmSubtaskOnly: (t, n) => `提案「${t}」でIssue #${n} にMR（Draft PR）を作成しますか？`,
  confirmExecute: "作成後、そのまま実装を開始します。",
  approved: (n) => `Issue #${n} に反映しました`,
};

// 表示中の項目（item・表示中のタブ・操作中か）
let ideaViewState = null;
let ideaViewPollTimer = null;

/**
 * Idea一覧の行の状態表示
 */
function ideaItemMeta(item) {
  return (item.latest_job && IDEA_JOB_ROW_LABELS[item.latest_job.status]) || "";
}

function isIdeaJobActive(job) {
  return !!job && IDEA_JOB_ACTIVE_STATUSES.includes(job.status);
}

/**
 * Ideaの項目の内容を表示する
 *
 * 観点の入力欄は、前回のアイデア出しの観点で埋める（同じ観点で再実行しやすくするため）。
 * 実行前に入力した観点の下書きがあれば、そちらを優先する。
 */
function showIdeaItem(item, container) {
  hideIdeaItem();
  ideaViewState = { item, tab: IDEA_TABS[0].tab, busy: false };
  container.innerHTML = `
    <div class="instruction-form idea-view-form">
      <textarea id="idea-view-focus" rows="3" maxlength="1000" aria-label="アイデアを出してほしい観点"
        placeholder="${IDEA_VIEW_MESSAGES.focusPlaceholder}"></textarea>
      <div class="subtask-actions">
        <button type="button" id="idea-view-run" class="subtask-action-button primary">${IDEA_VIEW_MESSAGES.run}</button>
        <label class="idea-view-execute"><input type="checkbox" id="idea-view-execute" checked />${IDEA_VIEW_MESSAGES.execute}</label>
      </div>
    </div>
    <p id="idea-view-message" class="title-status repo-item-action-status empty" role="status"></p>
    <p id="idea-view-job" class="job-status empty" role="status"></p>
    <div id="idea-view-tabs" class="idea-tabs" role="group" aria-label="提案の状態"></div>
    <div id="idea-view-list" class="idea-list" aria-live="polite"></div>
  `;
  const focus = document.getElementById("idea-view-focus");
  focus.value = (item.latest_job && item.latest_job.focus) || "";
  bindDraft(focus, draftKey(DRAFT_KINDS.idea, item.id));
  document.getElementById("idea-view-run").addEventListener("click", onRunIdeaGeneration);
  renderIdeaTabs();
  renderIdeaJob(item);
  pollIdeaItem(item);
  refreshIdeaList();
}

function hideIdeaItem() {
  clearTimeout(ideaViewPollTimer);
  ideaViewPollTimer = null;
  ideaViewState = null;
}

function setIdeaViewMessage(text) {
  document.getElementById("idea-view-message").textContent = text;
}

function renderIdeaTabs() {
  const container = document.getElementById("idea-view-tabs");
  container.replaceChildren(...IDEA_TABS.map(renderIdeaTabButton));
}

function renderIdeaTabButton(def) {
  const button = ideaElement("button", "idea-tab-button", def.label);
  button.type = "button";
  button.setAttribute("aria-pressed", String(ideaViewState.tab === def.tab));
  button.addEventListener("click", () => selectIdeaTab(def.tab));
  return button;
}

async function selectIdeaTab(tab) {
  if (!ideaViewState) return;
  ideaViewState.tab = tab;
  renderIdeaTabs();
  await refreshIdeaList();
}

async function fetchIdeaJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || response.statusText);
  return body;
}

function postIdeaJson(url, payload) {
  return fetchIdeaJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * アイデア出しの実行中は、項目を一定間隔で取得し直す
 */
function pollIdeaItem(item) {
  clearTimeout(ideaViewPollTimer);
  if (isIdeaJobActive(item.latest_job)) ideaViewPollTimer = setTimeout(() => refreshIdeaItem(true), IDEA_VIEW_POLL_MS);
}

/**
 * 項目を取得し直して、最新のアイデア出しの状態を表示する
 *
 * 実行中から終わった場合は提案一覧を取得し直す。
 * 取得に失敗した場合（サーバー再起動中など）も取得し直す。
 */
async function refreshIdeaItem(wasActive = false) {
  const state = ideaViewState;
  if (!state) return;
  const item = await fetchIdeaJson(`/api/idea-sessions/${state.item.id}`).catch(() => null);
  if (state !== ideaViewState) return;
  if (!item) {
    ideaViewPollTimer = setTimeout(() => refreshIdeaItem(wasActive), IDEA_VIEW_POLL_MS);
    return;
  }
  state.item = item;
  renderIdeaJob(item);
  updateRepoItemRow(REPO_ITEM_TABS.idea, item);
  if (wasActive && !isIdeaJobActive(item.latest_job)) await refreshIdeaList();
  pollIdeaItem(item);
}

/**
 * 最新のアイデア出しの状態と実行可否を表示する
 *
 * 実行中・Closeの項目では実行できない。
 */
function renderIdeaJob(item) {
  const job = item.latest_job;
  const status = document.getElementById("idea-view-job");
  status.textContent = job ? IDEA_JOB_STATUS_LABELS[job.status] || job.status : "";
  status.title = (job && (job.error_message || job.result_summary)) || "";
  const open = item.state === REPO_ITEM_STATES.open;
  const active = isIdeaJobActive(job);
  document.getElementById("idea-view-run").disabled = active || !open;
  document.getElementById("idea-view-focus").readOnly = active || !open;
  if (!open) setIdeaViewMessage(IDEA_VIEW_MESSAGES.closed);
}

async function onRunIdeaGeneration() {
  const state = ideaViewState;
  if (!state) return;
  document.getElementById("idea-view-run").disabled = true;
  const focus = document.getElementById("idea-view-focus").value;
  try {
    await postIdeaJson(`/api/idea-sessions/${state.item.id}/run`, { focus });
    clearDraft(draftKey(DRAFT_KINDS.idea, state.item.id));
    setIdeaViewMessage("");
  } catch (error) {
    setIdeaViewMessage(`${IDEA_VIEW_MESSAGES.runFailed}: ${error.message}`);
  }
  await refreshIdeaItem(true);
}

async function refreshIdeaList() {
  const state = ideaViewState;
  if (!state) return;
  const list = document.getElementById("idea-view-list");
  try {
    const ideas = await fetchIdeaJson(`/api/idea-sessions/${state.item.id}/ideas?tab=${state.tab}`);
    if (state !== ideaViewState) return;
    renderIdeaList(list, ideas);
  } catch (error) {
    if (state === ideaViewState) list.replaceChildren(ideaEmptyText(`${IDEA_VIEW_MESSAGES.loadFailed}: ${error.message}`));
  }
}

function renderIdeaList(list, ideas) {
  if (ideas.length === 0) list.replaceChildren(ideaEmptyText(IDEA_VIEW_MESSAGES.empty));
  else list.replaceChildren(...ideas.map(renderIdeaCard));
}

function ideaEmptyText(text) {
  return ideaElement("p", "empty", text);
}

function ideaElement(tag, className, text) {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

/**
 * 提案1件のカード
 *
 * タイトル・分類・概要・根拠・関連ファイル・対象Issueを表示する。
 * 状態に応じて承認・却下の操作を置く。
 */
function renderIdeaCard(idea) {
  const card = ideaElement("article", "idea-card");
  card.append(renderIdeaCardHeader(idea), ...renderIdeaCardBody(idea), ...renderIdeaCardNotes(idea));
  const actions = renderIdeaActions(idea);
  if (actions) card.appendChild(actions);
  return card;
}

function renderIdeaCardHeader(idea) {
  const header = ideaElement("div", "idea-card-header");
  header.append(
    ideaElement("span", "idea-category", IDEA_CATEGORY_LABELS[idea.category] || idea.category),
    ideaElement("span", "idea-title", idea.title),
    ideaElement("span", "idea-status", IDEA_STATUS_LABELS[idea.status] || idea.status),
  );
  return header;
}

function renderIdeaCardBody(idea) {
  const sections = [
    [IDEA_VIEW_MESSAGES.rationale, idea.rationale],
    [IDEA_VIEW_MESSAGES.relatedFiles, idea.related_files.join("\n")],
    [IDEA_VIEW_MESSAGES.detail, idea.detail],
  ];
  return [
    ideaElement("p", "idea-summary", idea.summary),
    ...sections.filter(([, text]) => text).map(([label, text]) => renderIdeaSection(label, text)),
  ];
}

function renderIdeaSection(label, text) {
  const details = ideaElement("details", "idea-section");
  details.append(ideaElement("summary", "", label), ideaElement("div", "idea-section-text", text));
  return details;
}

function renderIdeaCardNotes(idea) {
  const notes = [];
  if (idea.related_issue_number) notes.push(IDEA_VIEW_MESSAGES.relatedIssue(idea.related_issue_number));
  if (idea.created_issue_number) notes.push(IDEA_VIEW_MESSAGES.createdIssue(idea.created_issue_number));
  if (idea.reject_reason) notes.push(IDEA_VIEW_MESSAGES.rejectReason(idea.reject_reason));
  return notes.map((text) => ideaElement("p", "idea-note", text));
}

/**
 * 提案の状態に応じた操作
 *
 * 未処理：Issue・MRを作成／却下（既存Issue配下はMRを作成／却下）。
 * Issue作成済：MRを作成（作成失敗時の再実行を兼ねる）。
 */
function renderIdeaActions(idea) {
  if (idea.status === IDEA_STATUS_PROPOSED) return renderProposedActions(idea);
  if (idea.status !== IDEA_STATUS_ISSUE_CREATED) return null;
  const actions = ideaElement("div", "idea-actions");
  actions.appendChild(ideaActionButton(IDEA_VIEW_MESSAGES.createSubtaskOnly, true, () =>
    approveIdea(idea, IDEA_APPROVAL_MODES.withSubtask)));
  return actions;
}

function renderProposedActions(idea) {
  const actions = ideaElement("div", "idea-actions");
  const reason = ideaElement("input", "idea-reject-reason");
  reason.type = "text";
  reason.placeholder = IDEA_VIEW_MESSAGES.rejectPlaceholder;
  actions.append(...renderApproveButtons(idea), reason,
    ideaActionButton(IDEA_VIEW_MESSAGES.reject, false, () => rejectIdea(idea, reason.value)));
  return actions;
}

function renderApproveButtons(idea) {
  const label = idea.related_issue_number
    ? IDEA_VIEW_MESSAGES.createSubtaskOnly
    : IDEA_VIEW_MESSAGES.createWithSubtask;
  return [ideaActionButton(label, true, () => approveIdea(idea, IDEA_APPROVAL_MODES.withSubtask))];
}

function ideaActionButton(label, primary, onClick) {
  const button = ideaElement("button", `subtask-action-button idea-action-button${primary ? " primary" : ""}`, label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function approveConfirmText(idea, execute) {
  const issueNumber = idea.related_issue_number || idea.created_issue_number;
  const text = issueNumber
    ? IDEA_VIEW_MESSAGES.confirmSubtaskOnly(idea.title, issueNumber)
    : IDEA_VIEW_MESSAGES.confirmWithSubtask(idea.title);
  return execute ? `${text}\n${IDEA_VIEW_MESSAGES.confirmExecute}` : text;
}

/**
 * 提案を承認する
 *
 * GitHubへ即時反映されるため、実行前に確認する。
 * 実行ボタン横のチェックがあれば、MR作成後にそのまま実装を開始する。
 */
async function approveIdea(idea, mode) {
  const execute = document.getElementById("idea-view-execute").checked;
  if (!confirm(approveConfirmText(idea, execute))) return;
  await runIdeaAction(async () => {
    const result = await postIdeaJson(`/api/ideas/${idea.id}/approve`, { mode, execute });
    const issueNumber = result.idea.related_issue_number || result.idea.created_issue_number;
    setIdeaViewMessage(IDEA_VIEW_MESSAGES.approved(issueNumber));
  });
}

async function rejectIdea(idea, reason) {
  await runIdeaAction(async () => {
    await postIdeaJson(`/api/ideas/${idea.id}/reject`, { reason });
    setIdeaViewMessage("");
  });
}

/**
 * 承認・却下の操作を1件ずつ実行し、提案一覧を取得し直す
 *
 * 失敗時は文言を表示する（承認前の状態に戻った提案も一覧に反映する）。
 */
async function runIdeaAction(action) {
  const state = ideaViewState;
  if (!state || state.busy) return;
  state.busy = true;
  setIdeaActionsDisabled(true);
  try {
    await action();
  } catch (error) {
    if (state === ideaViewState) setIdeaViewMessage(`${IDEA_VIEW_MESSAGES.actionFailed}: ${error.message}`);
  }
  state.busy = false;
  await refreshIdeaList();
}

function setIdeaActionsDisabled(disabled) {
  document.querySelectorAll("#idea-view-list .idea-action-button").forEach((b) => (b.disabled = disabled));
}

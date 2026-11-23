/**
 * 提案一覧（アイデアマン）ダイアログ
 *
 * リポジトリごとにアイデア出しを実行し、提案を確認・承認・却下する。
 * 提案は未処理／承認済み／却下済みのタブに分けて表示する。
 * アイデア出しの実行中は、最新ジョブを一定間隔で取得して状態を表示する。
 */

// アイデア出し実行中の最新ジョブの取得間隔
const IDEA_DIALOG_POLL_MS = 3000;

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

const IDEA_DIALOG_MESSAGES = {
  title: (name) => `提案一覧（アイデアマン） - ${name}`,
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

// 表示中の提案一覧（projectId・表示中のタブ・操作中か）
let ideaDialogState = null;
let ideaDialogPollTimer = null;

async function openIdeaDialog(project) {
  ideaDialogState = { projectId: project.id, tab: IDEA_TABS[0].tab, busy: false };
  document.getElementById("idea-dialog-title").textContent = IDEA_DIALOG_MESSAGES.title(project.display_name);
  setIdeaDialogMessage("");
  renderIdeaTabs();
  document.getElementById("idea-dialog").showModal();
  await Promise.all([refreshIdeaJob(), refreshIdeaList()]);
}

function closeIdeaDialog() {
  document.getElementById("idea-dialog").close();
}

function onIdeaDialogClosed() {
  clearTimeout(ideaDialogPollTimer);
  ideaDialogPollTimer = null;
  ideaDialogState = null;
}

function setIdeaDialogMessage(text) {
  document.getElementById("idea-dialog-message").textContent = text;
}

function renderIdeaTabs() {
  const container = document.getElementById("idea-dialog-tabs");
  container.replaceChildren(...IDEA_TABS.map(renderIdeaTabButton));
}

function renderIdeaTabButton(def) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "idea-tab-button";
  button.textContent = def.label;
  button.setAttribute("aria-pressed", String(ideaDialogState.tab === def.tab));
  button.addEventListener("click", () => selectIdeaTab(def.tab));
  return button;
}

async function selectIdeaTab(tab) {
  if (!ideaDialogState) return;
  ideaDialogState.tab = tab;
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
 * 最新のアイデア出しジョブの状態を表示する
 *
 * 実行中は一定間隔で取得し直し、終わったら提案一覧を取得し直す。
 * 取得に失敗した場合（サーバー再起動中など）も取得し直す。
 */
async function refreshIdeaJob(wasActive = false) {
  clearTimeout(ideaDialogPollTimer);
  const state = ideaDialogState;
  if (!state) return;
  const job = await fetchIdeaJson(`/api/projects/${state.projectId}/idea-jobs/latest`).catch(() => undefined);
  if (state !== ideaDialogState) return;
  const fetched = job !== undefined;
  const active = fetched && job !== null && IDEA_JOB_ACTIVE_STATUSES.includes(job.status);
  if (fetched) renderIdeaJob(job, active);
  if (wasActive && fetched && !active) await refreshIdeaList();
  if (!fetched || active) {
    const nextWasActive = fetched ? active : wasActive;
    ideaDialogPollTimer = setTimeout(() => refreshIdeaJob(nextWasActive), IDEA_DIALOG_POLL_MS);
  }
}

function renderIdeaJob(job, active) {
  const status = document.getElementById("idea-dialog-job");
  status.textContent = job ? IDEA_JOB_STATUS_LABELS[job.status] || job.status : "";
  status.title = (job && (job.error_message || job.result_summary)) || "";
  document.getElementById("idea-dialog-run").disabled = active;
}

async function onRunIdeaGeneration() {
  const state = ideaDialogState;
  if (!state) return;
  document.getElementById("idea-dialog-run").disabled = true;
  try {
    await postIdeaJson(`/api/projects/${state.projectId}/ideas/run`, {});
    setIdeaDialogMessage("");
  } catch (error) {
    setIdeaDialogMessage(`${IDEA_DIALOG_MESSAGES.runFailed}: ${error.message}`);
  }
  await refreshIdeaJob();
}

async function refreshIdeaList() {
  const state = ideaDialogState;
  if (!state) return;
  const list = document.getElementById("idea-dialog-list");
  try {
    const ideas = await fetchIdeaJson(`/api/projects/${state.projectId}/ideas?tab=${state.tab}`);
    if (state !== ideaDialogState) return;
    renderIdeaList(list, ideas);
  } catch (error) {
    list.replaceChildren(ideaEmptyText(`${IDEA_DIALOG_MESSAGES.loadFailed}: ${error.message}`));
  }
}

function renderIdeaList(list, ideas) {
  if (ideas.length === 0) list.replaceChildren(ideaEmptyText(IDEA_DIALOG_MESSAGES.empty));
  else list.replaceChildren(...ideas.map(renderIdeaCard));
}

function ideaEmptyText(text) {
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  return p;
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
    [IDEA_DIALOG_MESSAGES.rationale, idea.rationale],
    [IDEA_DIALOG_MESSAGES.relatedFiles, idea.related_files.join("\n")],
    [IDEA_DIALOG_MESSAGES.detail, idea.detail],
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
  if (idea.related_issue_number) notes.push(IDEA_DIALOG_MESSAGES.relatedIssue(idea.related_issue_number));
  if (idea.created_issue_number) notes.push(IDEA_DIALOG_MESSAGES.createdIssue(idea.created_issue_number));
  if (idea.reject_reason) notes.push(IDEA_DIALOG_MESSAGES.rejectReason(idea.reject_reason));
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
  actions.appendChild(ideaActionButton(IDEA_DIALOG_MESSAGES.createSubtaskOnly, true, () =>
    approveIdea(idea, IDEA_APPROVAL_MODES.withSubtask)));
  return actions;
}

function renderProposedActions(idea) {
  const actions = ideaElement("div", "idea-actions");
  const reason = ideaElement("input", "idea-reject-reason");
  reason.type = "text";
  reason.placeholder = IDEA_DIALOG_MESSAGES.rejectPlaceholder;
  actions.append(...renderApproveButtons(idea), reason,
    ideaActionButton(IDEA_DIALOG_MESSAGES.reject, false, () => rejectIdea(idea, reason.value)));
  return actions;
}

function renderApproveButtons(idea) {
  const label = idea.related_issue_number
    ? IDEA_DIALOG_MESSAGES.createSubtaskOnly
    : IDEA_DIALOG_MESSAGES.createWithSubtask;
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
    ? IDEA_DIALOG_MESSAGES.confirmSubtaskOnly(idea.title, issueNumber)
    : IDEA_DIALOG_MESSAGES.confirmWithSubtask(idea.title);
  return execute ? `${text}\n${IDEA_DIALOG_MESSAGES.confirmExecute}` : text;
}

/**
 * 提案を承認する
 *
 * GitHubへ即時反映されるため、実行前に確認する。
 * 見出し行のチェックがあれば、MR作成後にそのまま実装を開始する。
 */
async function approveIdea(idea, mode) {
  const execute = document.getElementById("idea-dialog-execute").checked;
  if (!confirm(approveConfirmText(idea, execute))) return;
  await runIdeaAction(async () => {
    const result = await postIdeaJson(`/api/ideas/${idea.id}/approve`, { mode, execute });
    const issueNumber = result.idea.related_issue_number || result.idea.created_issue_number;
    setIdeaDialogMessage(IDEA_DIALOG_MESSAGES.approved(issueNumber));
  });
}

async function rejectIdea(idea, reason) {
  await runIdeaAction(async () => {
    await postIdeaJson(`/api/ideas/${idea.id}/reject`, { reason });
    setIdeaDialogMessage("");
  });
}

/**
 * 承認・却下の操作を1件ずつ実行し、提案一覧を取得し直す
 *
 * 失敗時は文言を表示する（承認前の状態に戻った提案も一覧に反映する）。
 */
async function runIdeaAction(action) {
  const state = ideaDialogState;
  if (!state || state.busy) return;
  state.busy = true;
  setIdeaActionsDisabled(true);
  try {
    await action();
  } catch (error) {
    setIdeaDialogMessage(`${IDEA_DIALOG_MESSAGES.actionFailed}: ${error.message}`);
  }
  state.busy = false;
  await refreshIdeaList();
}

function setIdeaActionsDisabled(disabled) {
  document.querySelectorAll("#idea-dialog-list .idea-action-button").forEach((b) => (b.disabled = disabled));
}

function setupIdeaDialog() {
  document.getElementById("idea-dialog-run").addEventListener("click", onRunIdeaGeneration);
  document.getElementById("idea-dialog-close").addEventListener("click", closeIdeaDialog);
  // Escキーで閉じた場合も取得を止める
  document.getElementById("idea-dialog").addEventListener("close", onIdeaDialogClosed);
}

setupIdeaDialog();

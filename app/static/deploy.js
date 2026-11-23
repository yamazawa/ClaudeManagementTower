/**
 * ヘッダーのDeployボタン・デプロイ確認ダイアログ
 *
 * MergedのMRがあるリポジトリをデプロイし、サーバー再起動を待つ。
 */

const SERVER_RESTART_POLL_MS = 1000;
const SERVER_RESTART_TIMEOUT_MS = 60000;
const DEPLOY_POLL_MS = 2000;
const DEPLOY_TIMEOUT_MS = 30 * 60 * 1000;
// サーバー再起動を表すデプロイ結果のrestartsの値（core/supervisor_control.pyと合わせる）
const DEPLOY_RESTART_SERVER = "restart_server";
const DEPLOY_BUTTON_TOOLTIP = "MergedのMRがあるリポジトリをデプロイします（デプロイすると動作確認できます）";
const DEPLOY_BUTTON_NO_MERGED_TOOLTIP = "MergedのMRがあるリポジトリはありません";
const DEPLOY_DIALOG_UNDEFINED_NOTE = "デプロイ未定義（MRをDeployedにするのみ）";
const DEPLOY_SKIPPED_TEXT = "デプロイ未定義のためMRをDeployedにしました";
// ヘッダーのDeployでデプロイ実行中か
let deployRunning = false;

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

/**
 * ヘッダーのDeployボタンの選択可否・色・ツールチップを更新する
 *
 * MergedのMRが無い場合・デプロイ実行中は無効化する。
 * MergedのMRがある場合はプライマリ色にする。
 */
function updateDeployButton() {
  const button = document.getElementById("deploy-button");
  const hasMerged = mergedProjects().length > 0;
  button.disabled = deployRunning || !hasMerged;
  button.classList.toggle("primary", hasMerged);
  button.title = hasMerged ? DEPLOY_BUTTON_TOOLTIP : DEPLOY_BUTTON_NO_MERGED_TOOLTIP;
}

function countMergedMrs(projectId) {
  return Object.values(mrStatusSummary.projects[projectId] || {}).reduce(
    (sum, statusCounts) => sum + (statusCounts[MR_STATUS.merged] || 0),
    0,
  );
}

// MergedのMRがあるリポジトリ
function mergedProjects() {
  return allProjects.filter((project) => countMergedMrs(project.id) > 0);
}

/**
 * デプロイ確認ダイアログの表示
 *
 * MergedのMRがあるリポジトリを、チェックボックス付き（既定ON）で一覧表示する。
 */
function openDeployDialog() {
  const projects = mergedProjects();
  if (projects.length === 0) return;
  document.getElementById("deploy-dialog-list").innerHTML = projects.map(renderDeployDialogItem).join("");
  updateDeployDialogConfirm();
  document.getElementById("deploy-dialog").showModal();
}

function renderDeployDialogItem(project) {
  const note = project.deploy_defined ? "" : `<span class="deploy-dialog-note">${DEPLOY_DIALOG_UNDEFINED_NOTE}</span>`;
  return (
    `<li><label><input type="checkbox" value="${project.id}" checked />` +
    `<span class="deploy-dialog-name">${escapeHtml(project.display_name)}</span>` +
    `<span class="deploy-dialog-count">Merged ${countMergedMrs(project.id)}</span>${note}</label></li>`
  );
}

function selectedDeployProjects() {
  const ids = [...document.querySelectorAll("#deploy-dialog-list input:checked")].map((input) => Number(input.value));
  return allProjects.filter((project) => ids.includes(project.id));
}

// 選択中のリポジトリが無い場合はデプロイできないようにする
function updateDeployDialogConfirm() {
  document.getElementById("deploy-dialog-confirm").disabled = selectedDeployProjects().length === 0;
}

async function onConfirmDeployDialog() {
  const projects = selectedDeployProjects();
  document.getElementById("deploy-dialog").close();
  if (projects.length > 0) await deployProjects(projects);
}

/**
 * 選択したリポジトリのデプロイ
 *
 * サーバー再起動を含むデプロイで他のデプロイが中断しないよう、1件ずつ順に実行する。
 * 実行中はヘッダーのDeployボタンを無効化し、完了後に各リポジトリの結果を表示する。
 */
async function deployProjects(projects) {
  const statusEl = document.getElementById("deploy-status");
  deployRunning = true;
  updateDeployButton();
  const results = [];
  try {
    // 順に実行するため、awaitを伴うループで書く
    for (const project of projects) {
      results.push(await deployProject(project, (text) => (statusEl.textContent = text)));
    }
    statusEl.textContent = results.join(" / ");
  } finally {
    deployRunning = false;
    await refreshMrStatuses().catch(() => {});
    updateDeployButton();
  }
}

async function deployProject(project, setStatus) {
  const name = project.display_name;
  setStatus(`${name}: デプロイ中...`);
  try {
    return `${name}: ${await runDeploy(project.id, (text) => setStatus(`${name}: ${text}`))}`;
  } catch (error) {
    return `${name}: デプロイに失敗しました: ${error.message}`;
  }
}

async function runDeploy(projectId, setStatus) {
  const oldBootId = await fetchBootId();
  const response = await fetch(`/api/projects/${projectId}/deploy`, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  if (body.skipped) return DEPLOY_SKIPPED_TEXT;

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

/**
 * リポジトリ一覧のリポジトリ追加ダイアログ
 *
 * 英語名・日本語名・何をするPJかを入力し、リポジトリを作成して一覧に追加する。
 * サーバー側で初期設定のIssue・MRのマージとIssueのクローズまで行う。
 */

const PROJECT_CREATE_RUNNING_TEXT = "作成中...（GitHub登録・初期設定のIssue・MRのマージまで行います）";
const PROJECT_CREATE_WARNING_TEXT = "リポジトリを追加しましたが、後始末に失敗しました";
// 作成中はダイアログを閉じさせない
let projectCreateRunning = false;

function setupProjectCreateDialog() {
  const dialog = document.getElementById("project-create-dialog");
  document.getElementById("project-create-button").addEventListener("click", openProjectCreateDialog);
  document.getElementById("project-create-cancel").addEventListener("click", () => dialog.close());
  document.getElementById("project-create-form").addEventListener("submit", onSubmitProjectCreateForm);
  dialog.addEventListener("cancel", (event) => {
    if (projectCreateRunning) event.preventDefault();
  });
}

function openProjectCreateDialog() {
  document.getElementById("project-create-status").textContent = "";
  document.getElementById("project-create-dialog").showModal();
}

function setProjectCreateRunning(running) {
  projectCreateRunning = running;
  document.getElementById("project-create-confirm").disabled = running;
  document.getElementById("project-create-cancel").disabled = running;
}

/**
 * リポジトリ追加フォームの送信
 *
 * 失敗時はダイアログを開いたまま失敗内容を表示する。
 * 登録まで済んだ場合は、失敗時も一覧に反映して追加したリポジトリを選択する。
 */
async function onSubmitProjectCreateForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("project-create-status");
  statusEl.textContent = PROJECT_CREATE_RUNNING_TEXT;
  setProjectCreateRunning(true);
  try {
    const result = await runBusyAction(() => postJson("/api/projects", projectCreatePayload(form)));
    await finishProjectCreate(form, statusEl, result);
  } finally {
    setProjectCreateRunning(false);
  }
}

function projectCreatePayload(form) {
  const value = (name) => form.elements.namedItem(name).value;
  return { name: value("name"), display_name: value("display_name"), description: value("description") };
}

/**
 * 作成結果を画面に反映する
 *
 * 失敗の詳細はメッセージと登録済みのリポジトリIDを持つ場合がある。
 */
async function finishProjectCreate(form, statusEl, { body, error }) {
  const projectId = body?.project_id ?? error?.project_id ?? null;
  if (projectId !== null) await showCreatedProject(projectId);
  if (error) {
    statusEl.textContent = `失敗しました: ${error.message ?? error}`;
    return;
  }
  if (body.warnings.length > 0) {
    statusEl.textContent = `${PROJECT_CREATE_WARNING_TEXT}\n${body.warnings.join("\n")}`;
    return;
  }
  form.reset();
  document.getElementById("project-create-dialog").close();
}

/**
 * 追加したリポジトリを一覧に反映して選択する
 */
async function showCreatedProject(projectId) {
  await loadProjects().catch(() => {});
  await refreshOpenIssueNumbers(projectId);
  refreshProjectCounts();
  const project = allProjects.find((p) => p.id === projectId);
  if (project) await selectProject(project).catch(() => {});
}

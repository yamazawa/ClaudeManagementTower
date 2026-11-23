/**
 * MR内容の添付ファイル
 *
 * 添付ファイルの一覧表示・アップロード・削除を行う。
 */

/**
 * 添付ボタン・添付ファイル一覧の初期化
 *
 * ファイル添付は選択したファイルをそのまま順にアップロードする。
 * 画像添付は選択した画像をお絵かきダイアログで加工してからアップロードする。
 */
function setupAttachmentForm(subtaskId) {
  bindFileChooser("attach-file-button", "attach-file-input", (files) => uploadAttachments(subtaskId, files));
  bindFileChooser("attach-image-button", "attach-image-input", async ([file]) => {
    const edited = await openImageEditor(file);
    if (edited) await uploadAttachments(subtaskId, [edited]);
  });
  loadAttachments(subtaskId);
}

/**
 * ボタンで規定のファイル選択を開き、選択結果を渡す
 *
 * 同じファイルを続けて選べるよう、選択後に入力値をクリアする。
 */
function bindFileChooser(buttonId, inputId, onSelect) {
  const button = document.getElementById(buttonId);
  const input = document.getElementById(inputId);
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    if (files.length) await onSelect(files);
  });
}

async function loadAttachments(subtaskId) {
  const attachments = await fetch(`/api/subtasks/${subtaskId}/attachments`)
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  renderAttachmentList(subtaskId, attachments);
}

/**
 * 添付ファイルの表（ID・ファイル）を描画する
 *
 * 画像はファイル名の代わりにサムネイルを表示する。
 * 削除ボタンは添付ボタンと同じ条件で無効化する。
 * 添付ファイルが無い場合は表を表示しない。
 */
function renderAttachmentList(subtaskId, attachments) {
  const container = document.getElementById("attachment-list");
  if (!container || Number(container.dataset.subtaskId) !== subtaskId) return;
  if (!attachments.length) {
    container.innerHTML = "";
    return;
  }
  const disabled = document.getElementById("attach-file-button")?.disabled ? " disabled" : "";
  const rows = attachments.map((a) => renderAttachmentRow(subtaskId, a, disabled)).join("");
  container.innerHTML =
    `<table class="attachment-table"><thead><tr><th>ID</th><th>ファイル</th><th></th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
  container
    .querySelectorAll(".attachment-delete-button")
    .forEach((b) => b.addEventListener("click", () => removeAttachment(subtaskId, b.dataset.attachmentId)));
}

function renderAttachmentRow(subtaskId, attachment, disabled) {
  const id = escapeHtml(attachment.id);
  const deleteButton =
    `<button type="button" class="subtask-action-button attach-button attachment-delete-button"` +
    ` data-attachment-id="${id}"${disabled}>削除</button>`;
  return `<tr><td>${id}</td><td>${renderAttachmentCell(subtaskId, attachment)}</td><td>${deleteButton}</td></tr>`;
}

function renderAttachmentCell(subtaskId, attachment) {
  if (!attachment.is_image) return escapeHtml(attachment.filename);
  const url = `/api/subtasks/${subtaskId}/attachments/${encodeURIComponent(attachment.id)}/file`;
  const name = escapeHtml(attachment.filename);
  return `<a href="${url}" target="_blank" rel="noopener"><img class="attachment-thumbnail" src="${url}" alt="${name}" title="${name}" loading="lazy" /></a>`;
}

/**
 * 選択したファイルを1件ずつアップロードする
 *
 * IDの採番順を選択順に揃えるため、並列にせず順に送る。
 * 一覧を読み直すまで更新中を表示する。
 */
async function uploadAttachments(subtaskId, files) {
  await runBusyAction(() => uploadAttachmentsInOrder(subtaskId, files));
}

async function uploadAttachmentsInOrder(subtaskId, files) {
  const statusEl = document.getElementById("attachment-status");
  const errors = [];
  for (const file of files) {
    statusEl.textContent = `アップロード中: ${file.name}`;
    const error = await uploadAttachment(subtaskId, file);
    if (error) errors.push(`${file.name}: ${error}`);
  }
  if (statusEl.isConnected) statusEl.textContent = errors.length ? `失敗しました: ${errors.join(" / ")}` : "";
  await loadAttachments(subtaskId);
}

/**
 * 確認のうえ添付ファイルを削除し、一覧を読み直す
 *
 * 失敗した場合は添付ボタン横の状態欄に理由を表示する。
 * 一覧を読み直すまで更新中を表示する。
 */
async function removeAttachment(subtaskId, attachmentId) {
  if (!confirm(`添付ファイル ${attachmentId} を削除しますか？`)) return;
  await runBusyAction(() => deleteAttachment(subtaskId, attachmentId));
}

async function deleteAttachment(subtaskId, attachmentId) {
  const response = await fetch(
    `/api/subtasks/${subtaskId}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" }
  ).catch(() => null);
  const statusEl = document.getElementById("attachment-status");
  if (statusEl) statusEl.textContent = response?.ok ? "" : `削除に失敗しました: ${attachmentId}`;
  await loadAttachments(subtaskId);
}

async function uploadAttachment(subtaskId, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/subtasks/${subtaskId}/attachments`, { method: "POST", body: form })
    .catch(() => null);
  if (!response) return "通信に失敗しました";
  if (response.ok) return null;
  const body = await response.json().catch(() => ({}));
  return body.detail || response.statusText;
}

/**
 * 添付ファイルの共通部品（MR内容・CLIタブ）
 *
 * 添付ボタン・お絵かきダイアログ・添付ファイル一覧の表を提供する。
 * APIのURLと要素IDを引数で受け取り、一覧表示・アップロード・削除を行う。
 * クリップボードの画像は、貼付ボタンまたは入力欄への貼り付けで添付する。
 */

const ATTACHMENT_MESSAGES = {
  attachFile: "ファイル添付",
  attachImage: "画像添付",
  pasteClipboard: "クリップボードから貼付",
  clipboardNoImage: "クリップボードに画像がありません",
  clipboardReadFailed: "クリップボードを読み取れませんでした（入力欄にCtrl+Vで貼り付けてください）",
  headerId: "ID",
  headerFile: "ファイル",
  delete: "削除",
  uploading: "アップロード中",
  uploadFailed: "失敗しました",
  networkFailed: "通信に失敗しました",
  confirmDelete: (id) => `添付ファイル ${id} を削除しますか？`,
  deleteFailed: (id) => `削除に失敗しました: ${id}`,
};

// 貼り付けた画像にファイル名が無い場合の名前
const ATTACHMENT_PASTED_IMAGE_NAME = "pasted-image.png";
const ATTACHMENT_IMAGE_TYPE_PREFIX = "image/";

// 表示中の部品（クリップボードの判定結果を貼付ボタンに反映する）
const attachmentForms = new Set();
// 最後に始めたクリップボードの判定（古い判定の結果は反映しない）
let clipboardCheckSeq = 0;

/**
 * 部品の要素IDを、接頭辞から決める
 */
function attachmentElementIds(prefix) {
  return {
    fileButton: `${prefix}-file-button`,
    fileInput: `${prefix}-file-input`,
    imageButton: `${prefix}-image-button`,
    imageInput: `${prefix}-image-input`,
    pasteButton: `${prefix}-paste-button`,
    status: `${prefix}-status`,
    list: `${prefix}-list`,
  };
}

/**
 * 添付ボタンの行と一覧の置き場所のHTML
 *
 * 画像添付は画像のみ選べるようにする（スマホでは写真の選択画面が開く）。
 * extraHtmlはボタンの行の末尾に置く（CLIの絞り込みなど）。
 */
function renderAttachmentFormHtml(ids, { hint = "", extraHtml = "" } = {}) {
  return `
    <div class="attachment-area">
      <button type="button" id="${ids.fileButton}" class="subtask-action-button attach-button">${ATTACHMENT_MESSAGES.attachFile}</button>
      <button type="button" id="${ids.imageButton}" class="subtask-action-button attach-button">${ATTACHMENT_MESSAGES.attachImage}</button>
      <button type="button" id="${ids.pasteButton}" class="subtask-action-button attach-button" hidden>${ATTACHMENT_MESSAGES.pasteClipboard}</button>
      <input type="file" id="${ids.fileInput}" multiple hidden />
      <input type="file" id="${ids.imageInput}" accept="image/*" hidden />
      ${extraHtml}
      <span id="${ids.status}" class="empty">${escapeHtml(hint)}</span>
    </div>
    <div id="${ids.list}" class="attachment-list"></div>
  `;
}

/**
 * 添付ボタン・添付ファイル一覧の初期化
 *
 * options
 *   apiUrl     : 添付ファイルのAPIのURL（一覧の取得・アップロードはこのURL、各添付は「URL/ID」）
 *   ids        : 要素ID（attachmentElementIdsの戻り値）
 *   hint       : 状態欄に普段表示する文言
 *   pasteTarget: 画像の貼り付けを受け付ける入力欄
 *   isShown    : 一覧に表示する添付か（省略時はすべて）
 *   rowClass   : 一覧の行に付けるクラス名
 *   canDelete  : 削除できる添付か（省略時はすべて）
 *   onChange   : 一覧を読み直した時に呼ぶ
 *
 * ファイル添付は選択したファイルをそのまま順にアップロードする。
 * 画像添付は選択した画像をお絵かきダイアログで加工してからアップロードする。
 * 貼付ボタンは、クリップボードに画像がある時のみ表示する。
 * 戻り値の部品で、一覧の読み直し・表示し直し・ボタンの無効化を行う。
 */
function setupAttachmentForm(options) {
  const form = {
    ...options,
    attachments: [],
    disabled: false,
    reload: () => loadAttachments(form),
    render: () => renderAttachmentList(form),
    setDisabled: (disabled) => setAttachmentFormDisabled(form, disabled),
    upload: (files) => uploadAttachments(form, files),
  };
  const { ids } = form;
  form.elements = {
    list: document.getElementById(ids.list),
    status: document.getElementById(ids.status),
    pasteButton: document.getElementById(ids.pasteButton),
    buttons: [ids.fileButton, ids.imageButton, ids.pasteButton].map((id) => document.getElementById(id)),
  };
  bindFileChooser(ids.fileButton, ids.fileInput, (files) => form.upload(files));
  bindFileChooser(ids.imageButton, ids.imageInput, ([file]) => attachEditedImages(form, [file]));
  form.elements.pasteButton.addEventListener("click", () => attachClipboardImage(form));
  form.pasteTarget?.addEventListener("paste", (event) => onAttachmentPaste(form, event));
  attachmentForms.add(form);
  refreshPasteButtons();
  form.reload();
  return form;
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

// 描画し直しやMRの切り替えで要素が消えた部品は、以降の表示を行わない
function isAttachmentFormShown(form) {
  return form.elements.list.isConnected;
}

// 状態の更新のたびに呼ばれるため、変わった時のみ描画し直す
function setAttachmentFormDisabled(form, disabled) {
  if (form.disabled === disabled) return;
  form.disabled = disabled;
  form.elements.buttons.forEach((b) => (b.disabled = disabled));
  form.render();
}

/**
 * 画像を1枚ずつお絵かきダイアログで加工してからアップロードする
 *
 * キャンセルした画像は添付しない。
 */
async function attachEditedImages(form, images) {
  const edited = [];
  for (const image of images) {
    const file = await openImageEditor(image);
    if (file) edited.push(file);
  }
  if (edited.length) await form.upload(edited);
}

/**
 * 入力欄に貼り付けたファイル（クリップボードの画像など）を添付する
 *
 * 画像はお絵かきダイアログを通し、それ以外のファイルはそのまま添付する。
 * ファイルを含まない貼り付けは、通常の文字の貼り付けとする。
 */
function onAttachmentPaste(form, event) {
  const files = [...(event.clipboardData?.files || [])];
  if (!files.length || form.disabled) return;
  event.preventDefault();
  const named = files.map(namePastedFile);
  const images = named.filter(isImageFile);
  const others = named.filter((f) => !isImageFile(f));
  (async () => {
    if (others.length) await form.upload(others);
    if (images.length) await attachEditedImages(form, images);
  })();
}

function isImageFile(file) {
  return file.type.startsWith(ATTACHMENT_IMAGE_TYPE_PREFIX);
}

/**
 * 貼付ボタンで、クリップボードの画像をお絵かきダイアログを通して添付する
 *
 * 画像が無い・読み取れない場合は状態欄に表示する。
 */
async function attachClipboardImage(form) {
  const image = await readClipboardImage().catch(() => undefined);
  if (image === undefined) setAttachmentStatus(form, ATTACHMENT_MESSAGES.clipboardReadFailed);
  else if (image === null) setAttachmentStatus(form, ATTACHMENT_MESSAGES.clipboardNoImage);
  else await attachEditedImages(form, [image]);
  refreshPasteButtons();
}

/**
 * クリップボードの先頭の画像をファイルとして返す
 *
 * 画像が無い場合はnull、読み取れない環境では例外とする。
 */
async function readClipboardImage() {
  for (const item of await navigator.clipboard.read()) {
    const type = item.types.find((t) => t.startsWith(ATTACHMENT_IMAGE_TYPE_PREFIX));
    if (type) return new File([await item.getType(type)], ATTACHMENT_PASTED_IMAGE_NAME, { type });
  }
  return null;
}

/**
 * クリップボードに画像があるかを判定する
 *
 * 画像の有無をtrue・false、判定できない環境ではnullを返す。
 * 許可を求めるダイアログを勝手に出さないよう、読み取りが許可済みの時のみ読む。
 * 画面にフォーカスが無く読めない時は、前回の判定を保つためundefinedを返す。
 */
async function clipboardHasImage() {
  if (!navigator.clipboard?.read || !navigator.permissions?.query) return null;
  const permission = await navigator.permissions.query({ name: "clipboard-read" }).catch(() => null);
  if (permission?.state !== "granted") return null;
  if (!document.hasFocus()) return undefined;
  const items = await navigator.clipboard.read().catch(() => null);
  if (!items) return null;
  return items.some((item) => item.types.some((t) => t.startsWith(ATTACHMENT_IMAGE_TYPE_PREFIX)));
}

/**
 * 表示中の部品の貼付ボタンを、クリップボードの判定結果に合わせて表示・非表示にする
 *
 * 判定できない環境では常に表示する。
 * 画面から消えた部品は対象から外す。
 */
async function refreshPasteButtons() {
  attachmentForms.forEach((form) => {
    if (!isAttachmentFormShown(form)) attachmentForms.delete(form);
  });
  if (!attachmentForms.size) return;
  const seq = ++clipboardCheckSeq;
  const hasImage = await clipboardHasImage().catch(() => null);
  if (seq !== clipboardCheckSeq || hasImage === undefined) return;
  attachmentForms.forEach((form) => (form.elements.pasteButton.hidden = hasImage === false));
}

window.addEventListener("focus", refreshPasteButtons);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshPasteButtons();
});

function namePastedFile(file) {
  return file.name ? file : new File([file], ATTACHMENT_PASTED_IMAGE_NAME, { type: file.type });
}

async function loadAttachments(form) {
  const attachments = await fetch(form.apiUrl)
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  if (!isAttachmentFormShown(form)) return;
  form.attachments = attachments;
  form.render();
  form.onChange?.(attachments);
}

/**
 * 添付ファイルの表（ID・ファイル）を描画する
 *
 * 画像はファイル名の代わりにサムネイルを表示する。
 * 削除ボタンは添付ボタンと同じ条件で無効化する。
 * 表示する添付ファイルが無い場合は表を表示しない。
 */
function renderAttachmentList(form) {
  const container = form.elements.list;
  const shown = form.attachments.filter((a) => (form.isShown ? form.isShown(a) : true));
  if (!shown.length) {
    container.innerHTML = "";
    return;
  }
  const rows = shown.map((a) => renderAttachmentRow(form, a)).join("");
  container.innerHTML =
    `<table class="attachment-table"><thead><tr><th>${ATTACHMENT_MESSAGES.headerId}</th>` +
    `<th>${ATTACHMENT_MESSAGES.headerFile}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  container
    .querySelectorAll(".attachment-delete-button")
    .forEach((b) => b.addEventListener("click", () => removeAttachment(form, b.dataset.attachmentId)));
}

function renderAttachmentRow(form, attachment) {
  const id = escapeHtml(attachment.id);
  const deletable = !form.disabled && (form.canDelete ? form.canDelete(attachment) : true);
  const rowClass = form.rowClass ? ` class="${form.rowClass(attachment)}"` : "";
  const deleteButton =
    `<button type="button" class="subtask-action-button attach-button attachment-delete-button"` +
    ` data-attachment-id="${id}"${deletable ? "" : " disabled"}>${ATTACHMENT_MESSAGES.delete}</button>`;
  return `<tr${rowClass}><td>${id}</td><td>${renderAttachmentCell(form, attachment)}</td><td>${deleteButton}</td></tr>`;
}

function attachmentUrl(form, attachmentId) {
  return `${form.apiUrl}/${encodeURIComponent(attachmentId)}`;
}

function renderAttachmentCell(form, attachment) {
  if (!attachment.is_image) return escapeHtml(attachment.filename);
  const url = `${attachmentUrl(form, attachment.id)}/file`;
  const name = escapeHtml(attachment.filename);
  return `<a href="${url}" target="_blank" rel="noopener"><img class="attachment-thumbnail" src="${url}" alt="${name}" title="${name}" loading="lazy" /></a>`;
}

function setAttachmentStatus(form, text) {
  form.elements.status.textContent = text || form.hint || "";
}

/**
 * 選択したファイルを1件ずつアップロードする
 *
 * IDの採番順を選択順に揃えるため、並列にせず順に送る。
 * 一覧を読み直すまで更新中を表示する。
 */
async function uploadAttachments(form, files) {
  await runBusyAction(() => uploadAttachmentsInOrder(form, files));
}

async function uploadAttachmentsInOrder(form, files) {
  const errors = [];
  for (const file of files) {
    setAttachmentStatus(form, `${ATTACHMENT_MESSAGES.uploading}: ${file.name}`);
    const error = await uploadAttachment(form, file);
    if (error) errors.push(`${file.name}: ${error}`);
  }
  setAttachmentStatus(form, errors.length ? `${ATTACHMENT_MESSAGES.uploadFailed}: ${errors.join(" / ")}` : "");
  await form.reload();
}

/**
 * 確認のうえ添付ファイルを削除し、一覧を読み直す
 *
 * 失敗した場合は添付ボタン横の状態欄に理由を表示する。
 * 一覧を読み直すまで更新中を表示する。
 */
async function removeAttachment(form, attachmentId) {
  if (!confirm(ATTACHMENT_MESSAGES.confirmDelete(attachmentId))) return;
  await runBusyAction(() => deleteAttachment(form, attachmentId));
}

async function deleteAttachment(form, attachmentId) {
  const response = await fetch(attachmentUrl(form, attachmentId), { method: "DELETE" }).catch(() => null);
  setAttachmentStatus(form, response?.ok ? "" : ATTACHMENT_MESSAGES.deleteFailed(attachmentId));
  await form.reload();
}

async function uploadAttachment(form, file) {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(form.apiUrl, { method: "POST", body }).catch(() => null);
  if (!response) return ATTACHMENT_MESSAGES.networkFailed;
  if (response.ok) return null;
  const detail = await response.json().catch(() => ({}));
  return detail.detail || response.statusText;
}

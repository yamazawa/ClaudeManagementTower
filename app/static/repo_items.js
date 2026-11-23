/**
 * リポジトリの項目（Issue・CLI・Idea）のタブ
 *
 * タブの切替はヘッダーのボタンで行い、リポジトリのペインには選択中のタブの一覧のみ表示する。
 * CLI・Ideaのタブは、Issueと同じ作成フォーム・一覧（Open・Closeのフィルタ）で項目を扱う。
 * CLI・Ideaのタブの表示中は、Issue内容・MR内容のペインの代わりに項目の内容のペインを表示する。
 * 項目の内容のペインは、項目を選択していない間は表示しない。
 */

// タブの種類
const REPO_ITEM_TABS = { issue: "issue", cli: "cli", idea: "idea" };
// 項目のOpen・Close（core/repo_items.pyのItemStateと合わせる）
const REPO_ITEM_STATES = { open: "open", closed: "closed" };
// CLI・Ideaのタブの表示中に隠すペイン（Issue内容・MR内容）
const REPO_ITEM_ISSUE_SECTION_IDS = ["subtask-list", "subtask-detail"];
const REPO_ITEM_DETAIL_SECTION_ID = "repo-item-detail";

// CLI・Ideaの項目の種類ごとの定義
const REPO_ITEM_KINDS = {
  [REPO_ITEM_TABS.cli]: {
    label: "CLI",
    listUrl: (projectId, state) => `/api/projects/${projectId}/cli-sessions?state=${state}`,
    createUrl: "/api/cli-sessions",
    itemUrl: (id) => `/api/cli-sessions/${id}`,
    meta: (item) => cliItemMeta(item),
    show: (item, container) => showCliItem(item, container),
    hide: () => hideCliItem(),
  },
  [REPO_ITEM_TABS.idea]: {
    label: "Idea",
    listUrl: (projectId, state) => `/api/projects/${projectId}/idea-sessions?state=${state}`,
    createUrl: "/api/idea-sessions",
    itemUrl: (id) => `/api/idea-sessions/${id}`,
    meta: (item) => ideaItemMeta(item),
    show: (item, container) => showIdeaItem(item, container),
    hide: () => hideIdeaItem(),
  },
};

const REPO_ITEM_MESSAGES = {
  empty: (label) => `${label}がありません。`,
  loadFailed: (label) => `${label}一覧を取得できませんでした`,
  creating: "作成中...",
  createFailed: "作成に失敗しました",
  close: "Close",
  reopen: "ReOpen",
  toggleFailed: "失敗しました",
};

let currentRepoItemTab = REPO_ITEM_TABS.issue;
// 種類ごとの選択中の項目（未選択はnull）
const selectedRepoItems = { [REPO_ITEM_TABS.cli]: null, [REPO_ITEM_TABS.idea]: null };
// 種類ごとの一覧の取得要求の通番（後発の要求があれば、先発の取得結果で表示を上書きしない）
const repoItemListRequestIds = { [REPO_ITEM_TABS.cli]: 0, [REPO_ITEM_TABS.idea]: 0 };

function isRepoItemKind(tab) {
  return tab in REPO_ITEM_KINDS;
}

/**
 * 表示中のタブの対象外のため隠すペインか
 *
 * Issue内容・MR内容のペインは、Issueのタブの表示中のみ表示する。
 */
function isSectionHiddenByTab(sectionId) {
  return REPO_ITEM_ISSUE_SECTION_IDS.includes(sectionId) && isRepoItemKind(currentRepoItemTab);
}

/**
 * タブを切り替える
 *
 * 表示中のタブの対象のペインのみ表示する。
 * CLI・Ideaのタブでは、MRステータスフィルタの選択を外し、一覧を取得し直す。
 */
function selectRepoItemTab(tab) {
  currentRepoItemTab = tab;
  if (isRepoItemKind(tab)) clearMrStatusFilter();
  document.querySelectorAll(".repo-item-switch-button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === tab)));
  document.querySelectorAll(".repo-item-panel").forEach((p) => (p.hidden = p.dataset.kind !== tab));
  REPO_ITEM_ISSUE_SECTION_IDS.forEach((id) => applySectionShown(document.getElementById(id)));
  renderRepoItemDetail();
  if (isRepoItemKind(tab) && currentProjectId !== null) reloadRepoItems(tab);
}

/**
 * リポジトリの切り替え時に、CLI・Ideaの選択を外す
 */
function clearRepoItemSelection() {
  Object.keys(selectedRepoItems).forEach((kind) => (selectedRepoItems[kind] = null));
  Object.keys(REPO_ITEM_KINDS).forEach((kind) => {
    document.getElementById(`${kind}-list-items`).innerHTML = "";
  });
  renderRepoItemDetail();
}

/**
 * リポジトリの表示時に、表示中のタブがCLI・Ideaであれば一覧を取得し直す
 */
function onRepoItemProjectShown() {
  if (isRepoItemKind(currentRepoItemTab)) reloadRepoItems(currentRepoItemTab);
}

/**
 * 一覧を取得して描画する
 *
 * 選択中の項目が一覧から外れた場合は選択を外す。
 */
async function reloadRepoItems(kind) {
  const def = REPO_ITEM_KINDS[kind];
  const projectId = currentProjectId;
  const requestId = ++repoItemListRequestIds[kind];
  const state = document.getElementById(`${kind}-filter`).value;
  const items = await fetch(def.listUrl(projectId, state))
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  if (requestId !== repoItemListRequestIds[kind] || projectId !== currentProjectId) return;
  renderRepoItemList(kind, items);
  const selected = selectedRepoItems[kind];
  if (items && selected && !items.some((item) => item.id === selected.id)) selectRepoItem(kind, null);
}

function renderRepoItemList(kind, items) {
  const label = REPO_ITEM_KINDS[kind].label;
  const listEl = document.getElementById(`${kind}-list-items`);
  if (items === null) listEl.innerHTML = `<li class="empty">${REPO_ITEM_MESSAGES.loadFailed(label)}</li>`;
  else if (items.length === 0) listEl.innerHTML = `<li class="empty">${REPO_ITEM_MESSAGES.empty(label)}</li>`;
  else listEl.replaceChildren(...items.map((item) => renderRepoItemRow(kind, item)));
}

/**
 * 一覧の1行
 *
 * Issue一覧と同様に種別・1行省略のタイトル・状態・閉じるボタンを並べる。
 * ボタンのクリックでは項目を選択しない。
 */
function renderRepoItemRow(kind, item) {
  const def = REPO_ITEM_KINDS[kind];
  const li = document.createElement("li");
  li.className = "repo-item-row";
  li.dataset.id = item.id;
  li.classList.toggle("active", selectedRepoItems[kind]?.id === item.id);
  li.innerHTML = `
    <span class="title-number">${def.label}</span>
    <span class="repo-item-row-title"></span>
    <span class="repo-item-meta"></span>
    <button type="button" class="title-action-button repo-item-toggle"></button>
  `;
  fillRepoItemRow(kind, li, item);
  li.addEventListener("click", () => selectRepoItem(kind, li.repoItem));
  li.querySelector(".repo-item-toggle").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleRepoItem(kind, li.repoItem, e.currentTarget);
  });
  return li;
}

function fillRepoItemRow(kind, li, item) {
  li.repoItem = item;
  const titleEl = li.querySelector(".repo-item-row-title");
  titleEl.textContent = item.title;
  titleEl.title = item.title;
  li.querySelector(".repo-item-meta").textContent = REPO_ITEM_KINDS[kind].meta(item);
  li.querySelector(".repo-item-toggle").textContent = toggleLabel(item);
}

function toggleLabel(item) {
  return item.state === REPO_ITEM_STATES.open ? REPO_ITEM_MESSAGES.close : REPO_ITEM_MESSAGES.reopen;
}

/**
 * 一覧の行を項目の最新の値で描画し直す
 *
 * 項目の内容のペインから、応答中・実行中の状態の変化を反映する。
 */
function updateRepoItemRow(kind, item) {
  const li = document.querySelector(`#${kind}-list-items .repo-item-row[data-id="${item.id}"]`);
  if (li) fillRepoItemRow(kind, li, item);
  if (selectedRepoItems[kind]?.id === item.id) selectedRepoItems[kind] = item;
}

/**
 * 項目の選択
 *
 * nullの場合は選択を外し、項目の内容のペインを隠す。
 */
function selectRepoItem(kind, item) {
  selectedRepoItems[kind] = item;
  document
    .querySelectorAll(`#${kind}-list-items .repo-item-row`)
    .forEach((li) => li.classList.toggle("active", Number(li.dataset.id) === item?.id));
  renderRepoItemDetail();
}

/**
 * 項目の内容のペインの描画
 *
 * CLI・Ideaのタブで項目を選択中の場合のみ表示する。
 * 見出しはMR内容と同様に、種別・クリックで編集できるタイトル・閉じるボタンを並べる。
 */
function renderRepoItemDetail() {
  Object.values(REPO_ITEM_KINDS).forEach((def) => def.hide());
  const kind = currentRepoItemTab;
  const item = isRepoItemKind(kind) ? selectedRepoItems[kind] : null;
  const section = document.getElementById(REPO_ITEM_DETAIL_SECTION_ID);
  section.hidden = item === null;
  if (item === null) return;
  const def = REPO_ITEM_KINDS[kind];
  document.getElementById("repo-item-heading").innerHTML =
    `<span class="title-number">${def.label}</span><span id="repo-item-title"></span>` +
    `<button type="button" id="repo-item-toggle" class="title-action-button">${toggleLabel(item)}</button>`;
  const titleEl = document.getElementById("repo-item-title");
  titleEl.textContent = item.title;
  const statusEl = document.getElementById("repo-item-title-status");
  statusEl.textContent = "";
  makeTitleEditable(titleEl, statusEl, (title) => saveRepoItemTitle(kind, item.id, title));
  const toggle = document.getElementById("repo-item-toggle");
  toggle.addEventListener("click", () => toggleRepoItem(kind, selectedRepoItems[kind], toggle));
  def.show(item, document.getElementById("repo-item-view"));
}

async function patchRepoItem(kind, id, payload) {
  const response = await fetch(REPO_ITEM_KINDS[kind].itemUrl(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (response.ok) return { body, error: null };
  return { body, error: body.detail || response.statusText };
}

/**
 * タイトルの保存
 *
 * 失敗時はエラー文言を返す。
 */
async function saveRepoItemTitle(kind, id, title) {
  const { body, error } = await patchRepoItem(kind, id, { title });
  if (!error) updateRepoItemRow(kind, body);
  return error;
}

/**
 * 項目を閉じる・再開する
 *
 * 一覧・見出しのどちらのボタンからも呼ぶ。
 * 選択中の項目は内容を描画し直し、一覧はフィルタに合わせて取得し直す。
 */
async function toggleRepoItem(kind, item, button) {
  const state = item.state === REPO_ITEM_STATES.open ? REPO_ITEM_STATES.closed : REPO_ITEM_STATES.open;
  button.disabled = true;
  const { body, error } = await patchRepoItem(kind, item.id, { state });
  button.disabled = false;
  if (error) {
    alert(`${REPO_ITEM_MESSAGES.toggleFailed}: ${error}`);
    return;
  }
  if (selectedRepoItems[kind]?.id === item.id) {
    selectedRepoItems[kind] = body;
    if (currentRepoItemTab === kind) renderRepoItemDetail();
  }
  await reloadRepoItems(kind);
}

/**
 * 作成フォームの送信
 *
 * 作成した項目が表示されるよう一覧のフィルタをOpenに戻し、作成した項目を選択する。
 */
async function onSubmitRepoItemForm(kind, event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById(`${kind}-create-status`);
  const button = form.querySelector("button");
  button.disabled = true;
  statusEl.textContent = REPO_ITEM_MESSAGES.creating;
  const payload = { project_id: currentProjectId, title: form.title.value };
  const { body: item, error } = await postJson(REPO_ITEM_KINDS[kind].createUrl, payload);
  button.disabled = false;
  if (error) {
    statusEl.textContent = `${REPO_ITEM_MESSAGES.createFailed}: ${error}`;
    return;
  }
  if (payload.project_id !== currentProjectId) return;
  form.reset();
  collapseFoldBlock(form);
  statusEl.textContent = "";
  document.getElementById(`${kind}-filter`).value = REPO_ITEM_STATES.open;
  selectedRepoItems[kind] = item;
  await reloadRepoItems(kind);
  selectRepoItem(kind, item);
}

function setupRepoItems() {
  document.querySelectorAll(".repo-item-switch-button").forEach((b) => b.addEventListener("click", () => selectRepoItemTab(b.dataset.kind)));
  Object.keys(REPO_ITEM_KINDS).forEach((kind) => {
    document.getElementById(`${kind}-create-form`).addEventListener("submit", (e) => onSubmitRepoItemForm(kind, e));
    document.getElementById(`${kind}-filter`).addEventListener("change", () => reloadRepoItems(kind));
  });
}

setupRepoItems();

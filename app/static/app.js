let currentProjectId = null;
let currentProjectName = null;
let currentIssueNumber = null;
let currentSubtasks = [];
let currentSelectedSubtaskId = null;

const LIFECYCLE_LABELS = {
  draft: "Draft",
  in_review: "レビュー中",
  merged: "マージ済",
  closed: "クローズ（未マージ）",
};

const WORKER_STATE_LABELS = {
  idle: "待機中",
  busy: "実行中",
};

async function pollWorkers() {
  const workers = await fetch("/api/workers").then((r) => r.json());
  const aliveWorkers = workers.filter((w) => !w.is_stale);
  const busyCount = aliveWorkers.filter((w) => w.state === "busy").length;

  const items = workers
    .map((w) => {
      if (w.is_stale) {
        return `<span class="worker-pill worker-offline">オフライン</span>`;
      }
      const label = WORKER_STATE_LABELS[w.state] || w.state;
      const job = w.current_job_id ? `job #${w.current_job_id}` : "";
      return `<span class="worker-pill worker-${w.state}">${label} ${job}</span>`;
    })
    .join("");
  document.getElementById("worker-status").innerHTML =
    `<span class="worker-summary">実行中 ${busyCount} / ${aliveWorkers.length}</span>${items}`;
  setTimeout(pollWorkers, 3000);
}

function renderBreadcrumb() {
  const el = document.getElementById("breadcrumb");
  if (currentProjectId === null) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <a href="#" id="breadcrumb-projects">リポジトリ一覧</a>
    <span class="breadcrumb-sep">&rsaquo;</span>
    <span class="breadcrumb-current">${currentProjectName}</span>
  `;
  document
    .getElementById("breadcrumb-projects")
    .addEventListener("click", (event) => {
      event.preventDefault();
      showProjectList();
    });
}

function showProjectList() {
  currentProjectId = null;
  currentProjectName = null;
  currentIssueNumber = null;
  document.getElementById("project-view").hidden = false;
  document.getElementById("issue-view").hidden = true;
  renderBreadcrumb();
}

async function init() {
  const projects = await fetch("/api/projects").then((r) => r.json());
  const listEl = document.getElementById("project-list-items");
  listEl.innerHTML = "";
  if (projects.length === 0) {
    listEl.innerHTML = '<li class="empty">リポジトリが登録されていません。</li>';
  } else {
    for (const project of projects) {
      const li = document.createElement("li");
      li.className = "project-item";
      li.innerHTML = `<span class="project-name">${project.name}</span><span class="project-branch">${project.default_branch}</span>`;
      li.addEventListener("click", () => selectProject(project.id, project.name));
      listEl.appendChild(li);
    }
  }
  pollWorkers();
}

async function selectProject(projectId, projectName) {
  currentProjectId = projectId;
  currentProjectName = projectName;
  document.getElementById("project-view").hidden = true;
  document.getElementById("issue-view").hidden = false;
  renderBreadcrumb();
  await loadIssues();
}

async function loadIssues() {
  const issues = await fetch(`/api/projects/${currentProjectId}/issues`).then((r) =>
    r.json()
  );
  const listEl = document.getElementById("issue-list-items");
  listEl.innerHTML = "";
  if (issues.length === 0) {
    listEl.innerHTML = '<li class="empty">タスクがありません。</li>';
    return;
  }
  for (const issue of issues) {
    const li = document.createElement("li");
    li.className = "issue-item";
    li.dataset.number = issue.number;
    li.innerHTML = `<span class="number">#${issue.number}</span>${issue.title}`;
    li.addEventListener("click", () => selectIssue(issue.number));
    listEl.appendChild(li);
  }
}

function renderSubtaskRow(s) {
  const label = LIFECYCLE_LABELS[s.lifecycle_state] || s.lifecycle_state;
  const prBadge = s.github_pr_number ? `PR #${s.github_pr_number}` : "";
  return `
    <li class="subtask-row" data-subtask-id="${s.id}">
      <span class="subtask-row-title">${s.title}</span>
      <span class="subtask-row-meta">${label} ${prBadge}</span>
    </li>
  `;
}

function highlightSelectedSubtaskRow() {
  document
    .querySelectorAll(".subtask-row")
    .forEach((row) =>
      row.classList.toggle("active", Number(row.dataset.subtaskId) === currentSelectedSubtaskId)
    );
}

async function selectIssue(number) {
  currentIssueNumber = number;
  currentSelectedSubtaskId = null;
  document
    .querySelectorAll(".issue-item")
    .forEach((el) => el.classList.toggle("active", Number(el.dataset.number) === number));

  await refreshIssueDetail();
  renderSubtaskDetail(null);
}

async function refreshIssueDetail() {
  const issue = await fetch(
    `/api/projects/${currentProjectId}/issues/${currentIssueNumber}`
  ).then((r) => r.json());
  currentSubtasks = issue.subtasks;

  const listEl = document.getElementById("subtask-list-body");
  const itemsHtml =
    currentSubtasks.length === 0
      ? '<p class="empty">サブタスクはまだありません。</p>'
      : `<ul id="subtask-list-items">${currentSubtasks.map(renderSubtaskRow).join("")}</ul>`;

  listEl.innerHTML = `
    <h3>#${issue.number} ${issue.title}</h3>
    <p>
      <a href="${issue.url}" target="_blank" rel="noopener">GitHubで開く</a>
      <button id="sync-button" type="button">同期</button>
      <span id="sync-status" class="empty"></span>
    </p>
    <p>${(issue.body || "").replace(/\n/g, "<br>")}</p>
    <form id="subtask-form">
      <input type="text" name="title" placeholder="タイトル" required />
      <textarea name="instruction" placeholder="指示内容" required></textarea>
      <button type="submit">作成</button>
      <p id="subtask-form-status" class="empty"></p>
    </form>
    ${itemsHtml}
  `;

  document
    .getElementById("subtask-form")
    .addEventListener("submit", onSubmitSubtaskForm);
  document.getElementById("sync-button").addEventListener("click", onClickSync);
  document
    .querySelectorAll(".subtask-row")
    .forEach((row) =>
      row.addEventListener("click", () => selectSubtask(Number(row.dataset.subtaskId)))
    );
  highlightSelectedSubtaskRow();
}

function selectSubtask(subtaskId) {
  currentSelectedSubtaskId = subtaskId;
  highlightSelectedSubtaskRow();
  const subtask = currentSubtasks.find((s) => s.id === subtaskId) || null;
  renderSubtaskDetail(subtask);
}

function renderSubtaskDetail(s) {
  const el = document.getElementById("subtask-detail-body");
  if (!s) {
    el.innerHTML = '<p class="empty">左の一覧からサブタスクを選択してください。</p>';
    return;
  }

  const prLink = s.pr_url
    ? ` <a href="${s.pr_url}" target="_blank" rel="noopener">PR #${s.github_pr_number}</a>`
    : "";
  const label = LIFECYCLE_LABELS[s.lifecycle_state] || s.lifecycle_state;

  el.innerHTML = `
    <h3>${s.title}</h3>
    <p>状態: ${label}${prLink}</p>
    <button class="run-button" data-subtask-id="${s.id}">実行する</button>
    <form class="rerun-form" data-subtask-id="${s.id}">
      <textarea name="instruction" placeholder="追加の指示（レビューNG時の修正依頼など）"></textarea>
      <button type="submit">この指示で再実行</button>
    </form>
    <p class="job-status empty" data-subtask-id="${s.id}"></p>
    <iframe class="report-frame" sandbox="" data-subtask-id="${s.id}" hidden></iframe>
  `;

  document.querySelector(".run-button").addEventListener("click", onClickRun);
  document.querySelector(".rerun-form").addEventListener("submit", onSubmitRerunForm);
}

async function onClickSync(event) {
  const button = event.target;
  button.disabled = true;
  document.getElementById("sync-status").textContent = "同期中...";

  const result = await fetch(`/api/projects/${currentProjectId}/sync`, {
    method: "POST",
  }).then((r) => r.json());

  const keepSelected = currentSelectedSubtaskId;
  await refreshIssueDetail();
  document.getElementById("sync-status").textContent =
    result.updated.length === 0 ? "変更なし" : `${result.updated.length}件更新`;
  if (keepSelected !== null) {
    selectSubtask(keepSelected);
  }
}

async function onSubmitIssueForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("issue-create-status");
  const title = form.title.value;
  const body = form.body.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const response = await fetch(`/api/projects/${currentProjectId}/issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body }),
  });

  form.querySelector("button").disabled = false;

  if (!response.ok) {
    const error = await response.json();
    statusEl.textContent = `失敗しました: ${error.detail}`;
    return;
  }

  form.reset();
  statusEl.textContent = "作成しました";
  await loadIssues();
}

async function onSubmitSubtaskForm(event) {
  event.preventDefault();
  const form = event.target;
  const statusEl = document.getElementById("subtask-form-status");
  const title = form.title.value;
  const instruction = form.instruction.value;

  statusEl.textContent = "作成中...";
  form.querySelector("button").disabled = true;

  const response = await fetch("/api/subtasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: currentProjectId,
      github_issue_number: currentIssueNumber,
      title,
      instruction,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    statusEl.textContent = `失敗しました: ${error.detail}`;
    form.querySelector("button").disabled = false;
    return;
  }

  await selectIssue(currentIssueNumber);
}

async function startExecution(subtaskId, instruction, button) {
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  button.disabled = true;
  statusEl.textContent = "実行待ち...";

  const body = instruction ? JSON.stringify({ instruction }) : undefined;
  const { job_id: jobId } = await fetch(`/api/subtasks/${subtaskId}/execute`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body,
  }).then((r) => r.json());

  pollJob(jobId, subtaskId, button);
}

async function onClickRun(event) {
  const subtaskId = event.target.dataset.subtaskId;
  await startExecution(subtaskId, null, event.target);
}

async function onSubmitRerunForm(event) {
  event.preventDefault();
  const form = event.target;
  const subtaskId = form.dataset.subtaskId;
  const instruction = form.instruction.value;
  if (!instruction) {
    return;
  }
  const button = form.querySelector("button");
  await startExecution(subtaskId, instruction, button);
}

async function pollJob(jobId, subtaskId, button) {
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  const job = await fetch(`/api/jobs/${jobId}`).then((r) => r.json());
  statusEl.textContent = `状態: ${job.status}`;

  if (job.status === "queued" || job.status === "running") {
    setTimeout(() => pollJob(jobId, subtaskId, button), 3000);
    return;
  }

  if (job.status === "succeeded") {
    // refreshIssueDetailが詳細ペインの選択状態を消すため、再描画してから選択し直す
    await refreshIssueDetail();
    selectSubtask(Number(subtaskId));
    await showReport(jobId, subtaskId);
  } else {
    button.disabled = false;
  }
}

async function showReport(jobId, subtaskId) {
  const frame = document.querySelector(`.report-frame[data-subtask-id="${subtaskId}"]`);
  const response = await fetch(`/api/jobs/${jobId}/report`);
  if (!response.ok) {
    return;
  }
  // iframeにURLを直接読み込ませる（レポート応答のCSPヘッダーを効かせるため）
  frame.src = `/api/jobs/${jobId}/report`;
  frame.hidden = false;
}

document.getElementById("issue-create-form").addEventListener("submit", onSubmitIssueForm);

init();

let currentProjectId = null;
let currentIssueNumber = null;

const LIFECYCLE_LABELS = {
  draft: "Draft",
  in_review: "レビュー中",
  merged: "マージ済",
  closed: "クローズ（未マージ）",
};

async function init() {
  const projects = await fetch("/api/projects").then((r) => r.json());
  if (projects.length === 0) {
    document.getElementById("issue-list-items").innerHTML =
      '<li class="empty">プロジェクトが登録されていません。</li>';
    return;
  }
  currentProjectId = projects[0].id;
  await loadIssues();
}

async function loadIssues() {
  const issues = await fetch(`/api/projects/${currentProjectId}/issues`).then((r) =>
    r.json()
  );
  const listEl = document.getElementById("issue-list-items");
  listEl.innerHTML = "";
  if (issues.length === 0) {
    listEl.innerHTML = '<li class="empty">Issueがありません。</li>';
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

function renderSubtask(s) {
  const prLink = s.pr_url
    ? ` <a href="${s.pr_url}" target="_blank" rel="noopener">PR #${s.github_pr_number}</a>`
    : "";
  const label = LIFECYCLE_LABELS[s.lifecycle_state] || s.lifecycle_state;
  return `
    <div class="subtask-item" data-subtask-id="${s.id}">
      <div>${s.title}（${label}）${prLink}</div>
      <button class="run-button" data-subtask-id="${s.id}">実行する</button>
      <p class="job-status empty" data-subtask-id="${s.id}"></p>
      <iframe class="report-frame" sandbox="" data-subtask-id="${s.id}" hidden></iframe>
    </div>
  `;
}

async function selectIssue(number) {
  currentIssueNumber = number;
  document
    .querySelectorAll(".issue-item")
    .forEach((el) => el.classList.toggle("active", Number(el.dataset.number) === number));

  const issue = await fetch(
    `/api/projects/${currentProjectId}/issues/${number}`
  ).then((r) => r.json());

  const detailEl = document.getElementById("issue-detail-body");
  const subtasksHtml =
    issue.subtasks.length === 0
      ? '<p class="empty">サブタスクはまだありません。</p>'
      : issue.subtasks.map(renderSubtask).join("");

  detailEl.innerHTML = `
    <h3>#${issue.number} ${issue.title}</h3>
    <p><a href="${issue.url}" target="_blank" rel="noopener">GitHubで開く</a></p>
    <p>${(issue.body || "").replace(/\n/g, "<br>")}</p>
    <h4>サブタスク履歴</h4>
    ${subtasksHtml}
    <h4>新規サブタスク作成</h4>
    <form id="subtask-form">
      <input type="text" name="title" placeholder="タイトル" required />
      <textarea name="instruction" placeholder="指示内容" required></textarea>
      <button type="submit">作成</button>
      <p id="subtask-form-status" class="empty"></p>
    </form>
  `;

  document
    .getElementById("subtask-form")
    .addEventListener("submit", onSubmitSubtaskForm);
  document
    .querySelectorAll(".run-button")
    .forEach((btn) => btn.addEventListener("click", onClickRun));
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

async function onClickRun(event) {
  const subtaskId = event.target.dataset.subtaskId;
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  event.target.disabled = true;
  statusEl.textContent = "実行待ち...";

  const { job_id: jobId } = await fetch(`/api/subtasks/${subtaskId}/execute`, {
    method: "POST",
  }).then((r) => r.json());

  pollJob(jobId, subtaskId, event.target);
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
    // selectIssueが画面を再描画するため、レポート表示は再描画の後に行う
    await selectIssue(currentIssueNumber);
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

init();

let currentProjectId = null;
let currentIssueNumber = null;

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
  return `<div class="subtask-item">${s.title}（${s.lifecycle_state}）${prLink}</div>`;
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

init();

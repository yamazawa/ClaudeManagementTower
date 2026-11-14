let currentProjectId = null;

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

async function selectIssue(number) {
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
      : issue.subtasks
          .map(
            (s) =>
              `<div class="subtask-item">${s.title}（${s.lifecycle_state}）</div>`
          )
          .join("");

  detailEl.innerHTML = `
    <h3>#${issue.number} ${issue.title}</h3>
    <p><a href="${issue.url}" target="_blank" rel="noopener">GitHubで開く</a></p>
    <p>${(issue.body || "").replace(/\n/g, "<br>")}</p>
    <h4>サブタスク履歴</h4>
    ${subtasksHtml}
  `;
}

init();

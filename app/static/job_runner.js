/**
 * 実装ジョブの実行
 *
 * 実装・再実装を実行し、終了までポーリングしてレポートを表示する。
 */

/**
 * 実装・再実装の実行
 *
 * 入力中の指示内容で実行し、終了までMRの操作ボタンを無効化する。
 */
async function executeSubtask(subtask) {
  const instruction = document.getElementById(`instruction-${subtask.id}`)?.value;
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtask.id}"]`);
  if (!instruction) {
    setJobStatusText(statusEl, "指示内容を入力してください");
    return;
  }
  setSubtaskBusy(subtask.id, true);
  setJobStatusText(statusEl, "実行待ち...", JOB_STATUS_CLASS.active);

  const response = await fetch(`/api/subtasks/${subtask.id}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  }).catch(() => null);
  const activeJob = await findActiveJobFromConflict(response);
  if (activeJob) {
    followActiveJob(activeJob, subtask.id, statusEl);
    return;
  }
  if (!response || !response.ok) {
    setJobStatusText(statusEl, "実行を開始できませんでした", JOB_STATUS_CLASS.warning);
    setSubtaskBusy(subtask.id, false);
    return;
  }
  pollJob((await response.json()).job_id, subtask.id);
}

/**
 * 実行拒否の応答から既存の実装ジョブを取り出す
 *
 * 別端末などで実行済みの場合、409の詳細にジョブIDと状態が入る。
 * それ以外の応答ではnullを返す。
 */
async function findActiveJobFromConflict(response) {
  if (!response || response.status !== 409) return null;
  const body = await response.json().catch(() => null);
  const detail = body && body.detail;
  if (!detail || typeof detail !== "object" || !detail.job_id) return null;
  return { id: detail.job_id, status: detail.status };
}

/**
 * 既存の実装ジョブの監視に切り替える
 *
 * 実行中であることを表示し、終了までポーリングする。
 */
function followActiveJob(job, subtaskId, statusEl) {
  followedJobIds.add(job.id);
  renderPolledJobStatus(statusEl, job, job.id);
  pollJob(job.id, subtaskId);
}

function renderPolledJobStatus(statusEl, job, jobId) {
  renderJobStatus(statusEl, job);
  if (followedJobIds.has(jobId) && isJobActive(job)) statusEl.prepend(JOB_ALREADY_ACTIVE_NOTE);
}

/**
 * ジョブの終了まで状態を監視する
 *
 * MR詳細の再描画のたびに呼ばれるため、同じジョブは重複して監視しない。
 */
function pollJob(jobId, subtaskId) {
  if (pollingJobIds.has(jobId)) return;
  pollingJobIds.add(jobId);
  busySubtaskIds.add(subtaskId);
  pollJobLoop(jobId, subtaskId);
}

async function pollJobLoop(jobId, subtaskId) {
  const job = await fetch(`/api/jobs/${jobId}`)
    .then((r) => r.json())
    .catch(() => null);
  const statusEl = document.querySelector(`.job-status[data-subtask-id="${subtaskId}"]`);
  if (statusEl && job) renderPolledJobStatus(statusEl, job, jobId);

  // 取得失敗時（サーバー再起動中など）も監視を継続する
  if (!job || isJobActive(job)) {
    setTimeout(() => pollJobLoop(jobId, subtaskId), JOB_POLL_MS);
    return;
  }
  pollingJobIds.delete(jobId);
  followedJobIds.delete(jobId);
  busySubtaskIds.delete(subtaskId);
  await onJobFinished(job, jobId, subtaskId);
}

async function onJobFinished(job, jobId, subtaskId) {
  if (job.status !== JOB_STATUS.succeeded) {
    // 失敗時はジョブ状態を取り直してボタンを戻す
    await refreshSubtaskStates().catch(() => {});
    refreshSelectedSubtaskState();
    return;
  }
  if (currentSelectedSubtaskId !== subtaskId) return;
  // 詳細ペインの表示を作り直すため、Issue内容を再描画してから選択し直す
  await refreshIssueDetail();
  // 再描画でMR一覧から外れて別のMRを選択し直した場合は、そちらの表示を優先する
  if (currentSelectedSubtaskId !== subtaskId) return;
  selectSubtask(subtaskId);
  await showReport(jobId, subtaskId);
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

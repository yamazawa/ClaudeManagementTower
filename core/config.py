from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    github_target_repo: str = "yamazawa/claude-tower-test-repo"
    github_target_repo_path: str = "C:/git/claude-tower-test-repo"
    github_default_branch: str = "master"
    worker_count: int = 3
    worktree_base_dir: str = "C:/git/claude-tower-worktrees"
    worker_poll_interval_seconds: int = 3
    job_heartbeat_interval_seconds: int = 5
    job_stale_timeout_seconds: int = 60
    # Claudeが応答しなくなった場合にワーカーを解放するための上限
    job_max_runtime_seconds: int = 7200
    idea_job_max_runtime_seconds: int = 1800
    worker_offline_timeout_seconds: int = 30
    worker_respawn_delay_seconds: float = 5.0
    database_path: str = "claude_tower.db"
    cloudflare_access_aud: str = ""
    supervisor_control_dir: str = ".tower-control"
    supervisor_poll_interval_seconds: float = 1.0
    pr_sync_interval_seconds: float = 5.0
    # GitHubのレート制限を考慮し、PR状態を同時に問い合わせるリポジトリ数を抑える
    pr_sync_max_workers: int = 3
    self_repo: str = "yamazawa/ClaudeManagementTower"
    claude_credentials_path: str = ""
    claude_usage_refresh_interval_seconds: float = 300.0
    idea_max_proposals: int = 5
    idea_history_limit: int = 10
    claude_shared_root: str = "C:/git"
    rate_limit_retry_delay_seconds: int = 600
    issue_list_cache_ttl_seconds: float = 45.0
    log_level: str = "INFO"
    # リポジトリ一覧から追加するリポジトリの作成先フォルダ・GitHubの所有者・公開範囲
    # 所有者が空の場合はself_repoの所有者とする
    new_repo_base_dir: str = "C:/git"
    new_repo_owner: str = ""
    new_repo_visibility: str = "private"


settings = Settings()

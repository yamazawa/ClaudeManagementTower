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
    worker_offline_timeout_seconds: int = 30
    worker_respawn_delay_seconds: float = 5.0
    database_path: str = "claude_tower.db"
    cloudflare_access_aud: str = ""
    supervisor_control_dir: str = ".tower-control"
    supervisor_poll_interval_seconds: float = 1.0
    pr_sync_interval_seconds: float = 5.0
    self_repo: str = "yamazawa/ClaudeManagementTower"
    claude_credentials_path: str = ""
    claude_usage_cache_seconds: float = 60.0


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    github_target_repo: str = "yamazawa/claude-tower-test-repo"
    github_target_repo_path: str = "C:/git/claude-tower-test-repo"
    github_default_branch: str = "master"
    worker_count: int = 3
    worktree_base_dir: str = "C:/git/claude-tower-worktrees"
    database_path: str = "claude_tower.db"
    cloudflare_access_aud: str = ""


settings = Settings()

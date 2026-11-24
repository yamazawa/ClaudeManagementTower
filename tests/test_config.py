from core.config import Settings


def test_settings_default_values():
    settings = Settings(_env_file=None)
    assert settings.github_target_repo == "yamazawa/claude-tower-test-repo"
    assert settings.worker_count == 3
    assert settings.job_max_runtime_seconds == 7200
    assert settings.idea_job_max_runtime_seconds == 1800

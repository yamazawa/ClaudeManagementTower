from core.config import Settings


def test_settings_default_values():
    settings = Settings(_env_file=None)
    assert settings.github_target_repo == "yamazawa/claude-tower-test-repo"
    assert settings.worker_count == 3

"""The setup wizard must preserve existing user secrets and validate input."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest
from dotenv import dotenv_values

@pytest.fixture
def wizard(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('paceboard_onboard', Path(__file__).resolve().parents[2] / 'scripts/onboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env.example').write_text('PACEBOARD_TIMEZONE=Europe/Oslo\nSTRAVA_CLIENT_ID=\nSTRAVA_CLIENT_SECRET=\n')
    return module

def answers(monkeypatch, values):
    replies = iter(values)
    monkeypatch.setattr('builtins.input', lambda _: next(replies))

def test_first_setup_creates_private_config(wizard, monkeypatch):
    answers(monkeypatch, ['UTC', 'n', 'n'])
    wizard.main()
    env = wizard.ROOT / '.env'
    assert dotenv_values(env)['PACEBOARD_TIMEZONE'] == 'UTC'
    assert env.stat().st_mode & 0o777 == 0o600

def test_repeat_setup_preserves_secret(wizard, monkeypatch):
    env = wizard.ROOT / '.env'
    env.write_text('PACEBOARD_TIMEZONE=UTC\nSTRAVA_CLIENT_SECRET=existing-test-secret\n')
    answers(monkeypatch, ['', 'n', 'n'])
    wizard.main()
    assert dotenv_values(env)['STRAVA_CLIENT_SECRET'] == 'existing-test-secret'
    assert dotenv_values(env)['PACEBOARD_TIMEZONE'] == 'UTC'

def test_invalid_timezone_leaves_config_unchanged(wizard, monkeypatch):
    answers(monkeypatch, ['not/a-zone'])
    with pytest.raises(SystemExit, match='Unknown timezone'):
        wizard.main()
    assert dotenv_values(wizard.ROOT / '.env')['PACEBOARD_TIMEZONE'] == 'Europe/Oslo'

def test_authentication_failure_stops_setup(wizard, monkeypatch):
    answers(monkeypatch, ['', 'y'])
    mock = Mock(side_effect=wizard.subprocess.CalledProcessError(1, 'garmin-mcp-auth'))
    monkeypatch.setattr(wizard.subprocess, 'run', mock)
    with pytest.raises(wizard.subprocess.CalledProcessError):
        wizard.main()
    assert mock.call_args.kwargs['check'] is True

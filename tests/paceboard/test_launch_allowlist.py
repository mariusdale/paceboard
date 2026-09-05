"""Exercise shell concatenation: every catalog entry must survive line wrapping."""
import subprocess
from pathlib import Path
from paceboard_api.providers.garmin.catalog import READ_ONLY_ALLOWLIST

def test_shell_allowlist_exactly_matches_catalog(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = (root / 'scripts/garmin-mcp-readonly.sh').read_text()
    assignment = script[script.index('GARMIN_ENABLED_TOOLS='):script.index('export GARMIN_ENABLED_TOOLS')]
    result = subprocess.check_output(['bash', '-c', assignment + '\nprintf "%s" "$GARMIN_ENABLED_TOOLS"'], text=True)
    assert set(result.split(',')) == set(READ_ONLY_ALLOWLIST)
    assert len(result.split(',')) == len(READ_ONLY_ALLOWLIST)

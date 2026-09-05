"""Interactive local setup. Never prints or saves a Garmin password."""
from pathlib import Path
import getpass
import os
import shutil
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]

def main():
    os.chdir(ROOT)
    env = ROOT / '.env'
    if not env.exists():
        env.touch(mode=0o600)
        shutil.copyfile(ROOT / '.env.example', env)
    env.chmod(0o600)
    values = dotenv_values(env)
    print('\nWelcome to Paceboard. Your accounts and health data stay on this computer.\n')
    zone = input(f'Timezone [{values.get("PACEBOARD_TIMEZONE", "Europe/Oslo")}]: ').strip()
    if zone:
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            raise SystemExit('Unknown timezone. Use a name such as Europe/Oslo or America/New_York; rerun setup.')
        set_key(env, 'PACEBOARD_TIMEZONE', zone)
    if input('Connect Garmin now? [Y/n]: ').strip().lower() != 'n':
        subprocess.run(['uv', 'run', '--python', '3.12', 'garmin-mcp-auth'], check=True)
    if input('Configure Strava too? [y/N]: ').strip().lower() == 'y':
        print('\nCreate your own app at https://www.strava.com/settings/api')
        print('Set Authorization Callback Domain to: 127.0.0.1')
        print('Website can be http://127.0.0.1:3000. Keep your client secret private.')
        client = input('Client ID (blank keeps existing): ').strip()
        secret = getpass.getpass('Client secret (blank keeps existing): ').strip()
        if client:
            if not client.isdigit():
                raise SystemExit('Client ID must contain digits only. Rerun setup.')
            set_key(env, 'STRAVA_CLIENT_ID', client)
        if secret:
            set_key(env, 'STRAVA_CLIENT_SECRET', secret)
    print('\nReady. Run ./scripts/start.sh to open Paceboard.')
    print('In Connections, authorize Strava if configured, then choose Backfill for your history.')

if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('\nSetup paused. Run ./scripts/setup.sh again to continue.')

"""Start disposable local services and run the live Playwright smoke checks."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
from dotenv import dotenv_values

test_dir = Path(__file__).resolve().parent
project = test_dir.parent
url = 'http://127.0.0.1:8091'


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_ready(process):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if httpx.get(f'{url}/ready', timeout=2).is_success:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise RuntimeError('The test server did not become ready.')


def main():
    connections = [{'type': 'mcp', 'url': 'http://127.0.0.1:8092/mcp', 'auth_type': 'none',
                    'info': {'id': 'smoke', 'name': 'AgroChat smoke'}, 'config': {'enable': True,
                    'access_grants': [{'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]}}]
    with tempfile.TemporaryDirectory(prefix='agrochat-smoke-') as data, ExitStack() as stack:
        env = {**os.environ, **{k: v for k, v in dotenv_values(project / '.env').items() if v and k not in os.environ}}
        env.update(DATA_DIR=data, AGROCHAT_ORIGIN=url, AGROCHAT_HOST='127.0.0.1', PORT='8091',
                   AGROCHAT_MEMORY_INTERVAL_SECONDS='15', TOOL_SERVER_CONNECTIONS=json.dumps(connections),
                   AGROCHAT_TEST_MCP='1', AGROCHAT_TEST_URL=url, DATABASE_URL=f'sqlite:///{data}/webui.db',
                   VECTOR_DB='chroma', STORAGE_PROVIDER='local')
        for label, args in [('mcp', [str(test_dir / 'mcp_fixture.py')]), ('app', ['-m', 'agrochat'])]:
            with (Path(data) / f'{label}.log').open('w') as log:
                process = subprocess.Popen([sys.executable, *args], cwd=project, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
            stack.callback(stop, process)
        try:
            wait_ready(process)
            subprocess.run([sys.executable, str(test_dir / 'smoke.py')], cwd=project, env=env, check=True)
        except (RuntimeError, subprocess.CalledProcessError):
            if destination := os.getenv('AGROCHAT_TEST_LOG_DIR'):
                path = Path(destination)
                path.mkdir(parents=True, exist_ok=True)
                for name in ('mcp.log', 'app.log'):
                    shutil.copyfile(Path(data) / name, path / name)
            print(f'Test failed (application process exit status: {process.poll()}).')
            raise


if __name__ == '__main__':
    main()

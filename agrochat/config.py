import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

MODELS = ('gpt-6.2-sol', 'gpt-6.2-astra')
EMBEDDING_MODEL = 'text-embedding-3-large'


def configure():
    load_dotenv(Path.cwd() / '.env')
    env = os.environ
    for name in ('AZURE_CHAT_API_KEY', 'AZURE_EMBEDDING_API_KEY'):
        if not env.get(name, '').strip():
            raise RuntimeError(f'{name} must be set')

    container_app = env.get('CONTAINER_APP_NAME')
    dns_suffix = env.get('CONTAINER_APP_ENV_DNS_SUFFIX')
    default_origin = f'https://{container_app}.{dns_suffix}' if container_app and dns_suffix else 'http://127.0.0.1:8080'
    origin = env.get('AGROCHAT_ORIGIN', default_origin).rstrip('/')
    url = urlsplit(origin)
    if not url.hostname or url.path or url.query or url.fragment or url.username:
        raise RuntimeError('AGROCHAT_ORIGIN must be an origin without a path')
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise RuntimeError('AGROCHAT_ORIGIN must use HTTPS outside localhost')
    if url.scheme == 'https' and not env.get('WEBUI_SECRET_KEY'):
        raise RuntimeError('HTTPS deployments require WEBUI_SECRET_KEY')

    data = Path(env.get('DATA_DIR', '.data')).resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not env.get('WEBUI_SECRET_KEY'):
        keyfile = data / 'agrochat-secret'
        try:
            with os.fdopen(os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as key:
                key.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
        env['WEBUI_SECRET_KEY'] = keyfile.read_text().strip()

    chat_base = env.get('AGROCHAT_CHAT_BASE', 'https://agroai-dev.services.ai.azure.com/openai/v1').rstrip('/')
    embedding_base = env.get('AGROCHAT_EMBEDDING_BASE', 'https://agro-llm.services.ai.azure.com/openai/v1').rstrip('/')
    env.setdefault('ENABLE_WEB_SEARCH', 'true')
    env.setdefault('WEB_SEARCH_ENGINE', 'duckduckgo')
    env.setdefault('DEFAULT_MODEL_METADATA', json.dumps({'defaultFeatureIds': ['web_search']}))
    env.update(
        FROM_INIT_PY='true',
        DATA_DIR=str(data),
        WEBUI_NAME='AgroChat',
        WEBUI_URL=origin,
        CORS_ALLOW_ORIGIN=origin,
        WEBUI_AUTH='true',
        WEBUI_AUTH_TRUSTED_EMAIL_HEADER='',
        WEBUI_ADMIN_EMAIL='',
        WEBUI_ADMIN_PASSWORD='',
        WEBUI_SESSION_COOKIE_SECURE=str(url.scheme == 'https').lower(),
        WEBUI_AUTH_COOKIE_SECURE=str(url.scheme == 'https').lower(),
        ENABLE_PERSISTENT_CONFIG='false',
        ENABLE_SIGNUP='false',
        ENABLE_INITIAL_ADMIN_SIGNUP='false',
        ENABLE_LDAP='false',
        ENABLE_SCIM='false',
        ENABLE_MFA='false',
        ENABLE_API_KEY='false',
        ENABLE_ADMIN_CHAT_ACCESS='false',
        ENABLE_OLLAMA_API='false',
        ENABLE_OPENAI_API='true',
        BYPASS_MODEL_ACCESS_CONTROL='true',
        OPENAI_API_BASE_URLS=chat_base,
        OPENAI_API_KEYS=env['AZURE_CHAT_API_KEY'],
        OPENAI_API_CONFIGS=json.dumps({'0': {'model_ids': MODELS, 'api_type': 'responses'}}),
        DEFAULT_MODELS=MODELS[0],
        TASK_MODEL_EXTERNAL=MODELS[0],
        RAG_EMBEDDING_ENGINE='openai',
        RAG_EMBEDDING_MODEL=EMBEDDING_MODEL,
        RAG_EMBEDDING_BATCH_SIZE='32',
        RAG_OPENAI_API_BASE_URL=embedding_base,
        RAG_OPENAI_API_KEY=env['AZURE_EMBEDDING_API_KEY'],
        ENABLE_MEMORIES='false',
        ENABLE_FUNCTIONS='false',
        ENABLE_TOOLS='false',
        ENABLE_TOOL_SERVERS='true',
        ENABLE_COMMUNITY_SHARING='false',
        ENABLE_VERSION_UPDATE_CHECK='false',
        ENABLE_EVALUATION_ARENA_MODELS='false',
        ENABLE_FORWARD_USER_INFO_HEADERS='false',
        ENABLE_AUTOMATIONS='false',
        USER_PERMISSIONS_CHAT_SHARE='false',
        USER_PERMISSIONS_FOLDERS_ALLOW_SHARING='false',
        USER_PERMISSIONS_FEATURES_CHANNELS='false',
        USER_PERMISSIONS_FEATURES_API_KEYS='false',
        USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS='false',
        USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS='false',
        ENABLE_REALTIME_CHAT_SAVE='true',
    )
    return origin, chat_base

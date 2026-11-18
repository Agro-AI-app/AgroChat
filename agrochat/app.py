import asyncio
import copy
import logging
from contextlib import asynccontextmanager, suppress
from importlib import import_module
from pathlib import Path
from urllib.parse import parse_qs

from .config import MODELS, configure

_, CHAT_BASE = configure()

from fastapi import HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import update
from starlette.routing import Mount

from open_webui.internal.db import async_engine, get_async_db_context
from open_webui.models.chats import Chat, ChatModel, Chats
from open_webui.models.folders import Folders

from .memory import add_memory, scheduler
from .profiles import meta, router

log = logging.getLogger(__name__)
static = Path(__file__).parent / 'static'
webui = import_module('open_webui.main')
app = webui.app
native_lifespan = app.router.lifespan_context
native_payload = webui.process_chat_payload
chat_middleware = import_module('open_webui.utils.middleware')
native_builtin_tools = chat_middleware.get_builtin_tools
native_move_chat = Chats.update_chat_folder_id_by_id_and_user_id


@asynccontextmanager
async def lifespan(application):
    async with native_lifespan(application):
        async with async_engine.begin() as connection:
            await connection.run_sync(meta.create_all)
        job = asyncio.create_task(scheduler(CHAT_BASE), name='agrochat-memory')
        try:
            yield
        finally:
            job.cancel()
            with suppress(asyncio.CancelledError):
                await job


async def scoped_payload(request, form_data, user, metadata, model):
    if form_data.get('model') not in MODELS:
        raise HTTPException(404, 'Select an AgroChat model.')
    model = copy.deepcopy(model)
    builtin = model.setdefault('info', {}).setdefault('meta', {}).setdefault('builtinTools', {})
    # Do not let the model browse user-wide conversation, note, or skill history.
    builtin.update(chats=False, notes=False, memory=False, skills=False)
    if not (metadata.get('chat_id') or '').startswith(('local:', 'temporary:', 'channel:')):
        if metadata.get('chat_id'):
            metadata['folder_id'] = await Chats.get_chat_folder_id(metadata['chat_id'], user.id)
    folder_id = metadata.get('folder_id')
    if folder_id and not await Folders.get_folder_by_id_and_user_id(folder_id, user.id):
        raise HTTPException(404, 'Project not found.')
    form_data, metadata, events, paused = await native_payload(request, form_data, user, metadata, model)
    if not paused:
        try:
            await add_memory(form_data, user.id, metadata)
        except Exception:
            log.exception('Memory context unavailable; continuing the chat')
    return form_data, metadata, events, paused


async def scoped_builtin_tools(request, extra_params, features=None, model=None, is_note_chat=False):
    model = copy.deepcopy(model) if model else {}
    metadata = extra_params.get('__metadata__') or {}
    # Keep RAG for explicitly attached documents and folder knowledge; no global browsing.
    model.setdefault('info', {}).setdefault('meta', {}).setdefault('builtinTools', {})['knowledge'] = bool(
        chat_middleware.get_attached_knowledge(model, metadata)
    )
    return await native_builtin_tools(request, extra_params, features, model, is_note_chat)


async def move_chat(id, user_id, folder_id, db=None):
    async with get_async_db_context(db) as session:
        chat = await session.get(Chat, id)
        if chat and chat.folder_id and chat.folder_id != folder_id:
            raise HTTPException(409, 'Project chats cannot be moved outside their project.')
        return await native_move_chat(id, user_id, folder_id, db=session)


async def toggle_archive(id, db=None):
    async with get_async_db_context(db) as session:
        chat = await session.get(Chat, id)
        if not chat:
            return None
        # Upstream clears folder_id when archiving. Retain it to keep project context isolated.
        chat.archived = not chat.archived
        await session.commit()
        return ChatModel.model_validate(chat)


async def archive_all(user_id, db=None):
    async with get_async_db_context(db) as session:
        await session.execute(update(Chat).where(Chat.user_id == user_id).values(archived=True))
        await session.commit()
        return True


webui.process_chat_payload = scoped_payload
chat_middleware.get_builtin_tools = scoped_builtin_tools
Chats.update_chat_folder_id_by_id_and_user_id = move_chat
Chats.toggle_chat_archive_by_id = toggle_archive
Chats.archive_all_chats_by_user_id = archive_all
app.router.lifespan_context = lifespan


@app.exception_handler(RequestValidationError)
async def validate_request(request, error):
    if request.url.path.startswith('/agrochat/api/'):
        return JSONResponse({'detail': 'Check the form and try again.'}, status_code=422)
    return await request_validation_exception_handler(request, error)


class ManagedRoutes:
    """Only profile registration creates users; managed provider settings are operator-only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '').rstrip('/')
        if scope['type'] == 'websocket' and path.startswith('/api/v1/tether'):
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] == 'http':
            auth = '/api/v1/auths/'
            blocked = (path == '/openai' or path.startswith('/openai/') or
                       path.startswith(('/api/v1/tether', '/api/v1/scim/', '/api/v1/users/default/permissions')) or
                       path.startswith(tuple(auth + suffix for suffix in ('ldap', 'admin', 'oauth', 'mfa', 'api_key'))) or
                       path in {auth + route for route in ('signup', 'signin', 'add')} or
                       (scope['method'] != 'GET' and (path == '/api/v1/models' or path.startswith('/api/v1/models/'))) or
                       (path.startswith('/oauth/') and not path.startswith('/oauth/clients/')) or
                       (scope['method'] == 'DELETE' and path.startswith('/api/v1/users/')))
            if blocked:
                return await JSONResponse({'detail': 'This endpoint is managed by AgroChat.'}, status_code=404)(
                    scope, receive, send
                )
            if scope['method'] == 'DELETE' and path.startswith('/api/v1/folders/'):
                values = parse_qs(scope['query_string'].decode()).get('delete_contents', [])
                if values and any(value.lower() not in {'true', 't', 'yes', 'y', '1', 'on'} for value in values):
                    return await JSONResponse({'detail': 'Delete a project together with its chats.'}, status_code=409)(
                        scope, receive, send
                    )
        await self.app(scope, receive, send)


app.add_middleware(ManagedRoutes)

# Register our routes ahead of Open WebUI's Svelte SPA fallback.
spa = app.router.routes.pop()
if not isinstance(spa, Mount) or spa.name != 'spa-static-files':
    raise RuntimeError('Unexpected Open WebUI frontend mount')
app.include_router(router)


@app.get('/auth', include_in_schema=False)
@app.get('/profiles', include_in_schema=False)
async def profile_page():
    return FileResponse(static / 'profiles.html', headers={'Cache-Control': 'no-store'})


@app.get('/account', include_in_schema=False)
async def account_page():
    return FileResponse(static / 'account.html', headers={'Cache-Control': 'no-store'})


@app.get('/agrochat/assets/{filename}', include_in_schema=False)
async def assets(filename: str):
    if filename not in {'style.css', 'profiles.js', 'account.js', 'shell.js', 'client.js', 'shell.css'}:
        raise HTTPException(404)
    return FileResponse(static / filename, headers={'Cache-Control': 'no-cache'})


class ChatFrontend(webui.SPAStaticFiles):
    index = (webui.FRONTEND_BUILD_DIR / 'index.html').read_text().replace(
        '</head>', '<link rel="stylesheet" href="/agrochat/assets/shell.css">'
        '<script defer src="/agrochat/assets/shell.js"></script></head>', 1,
    )

    async def get_response(self, path, scope):
        result = await super().get_response(path, scope)
        if isinstance(result, FileResponse) and Path(result.path).name == 'index.html':
            request = Request(scope)
            if not request.cookies.get('token') and path in {'.', '', 'index.html'}:
                return RedirectResponse('/profiles', status_code=303, headers={'Cache-Control': 'no-store'})
            return HTMLResponse(self.index, headers={'Cache-Control': 'no-cache'})
        return result


app.mount('/', ChatFrontend(directory=webui.FRONTEND_BUILD_DIR, html=True), name='frontend')

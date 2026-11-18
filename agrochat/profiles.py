import asyncio
import base64
import hmac
import io
import os
import time
import unicodedata
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from PIL import Image
from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, Integer, MetaData, String, Table,
                        delete, func, insert, select, update)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import get_async_session
from open_webui.models.auths import Auth, Auths, SigninForm
from open_webui.models.users import User, UserModel, Users
from open_webui.routers.auths import signin, signout
from open_webui.utils.auth import get_password_hash, get_verified_user, verify_password

LIMIT = 6
meta = MetaData()
profiles = Table(
    'agrochat_profile', meta,
    Column('user_id', String, primary_key=True),
    Column('slot', Integer, nullable=False, unique=True),
    Column('full_name', String(121), nullable=False),
    Column('name_key', String(256), nullable=False, unique=True),
    Column('paused', Boolean, nullable=False),
    Column('since', Integer, nullable=False),
    Column('revision', Integer, nullable=False),
    Column('memory', JSON, nullable=False),
    CheckConstraint(f'slot BETWEEN 1 AND {LIMIT}'),
)
registration_lock = asyncio.Lock()


def same_origin(request: Request):
    if request.headers.get('origin') != os.environ['WEBUI_URL']:
        raise HTTPException(403, 'This action must be submitted from AgroChat.')


router = APIRouter(prefix='/agrochat/api')


class Registration(BaseModel):
    first_name: str = Field(max_length=60)
    surname: str = Field(max_length=60)
    password: SecretStr
    confirm_password: SecretStr
    enrollment_code: SecretStr = SecretStr('')


class Login(BaseModel):
    profile_id: UUID
    password: SecretStr


class DeleteAccount(BaseModel):
    full_name: str = Field(max_length=121)
    password: SecretStr


class Photo(BaseModel):
    image: str | None = Field(max_length=140_000)


def clean_name(value):
    value = ' '.join(unicodedata.normalize('NFC', value).split())
    if not any(char.isalpha() for char in value) or any(unicodedata.category(c).startswith('C') for c in value):
        raise HTTPException(422, 'Enter a valid first name and surname.')
    return value


async def profile_row(db, user_id):
    return (await db.execute(select(profiles).where(profiles.c.user_id == user_id))).mappings().one_or_none()


@router.get('/profiles')
async def list_profiles(response: Response, db: AsyncSession = Depends(get_async_session)):
    response.headers['Cache-Control'] = 'no-store'
    rows = (await db.execute(select(profiles.c.user_id, profiles.c.full_name, profiles.c.slot)
                            .join(User, User.id == profiles.c.user_id).order_by(profiles.c.slot))).all()
    return {'profiles': [{'id': row.user_id, 'name': row.full_name, 'slot': row.slot} for row in rows],
            'limit': LIMIT, 'code_required': bool(os.getenv('AGROCHAT_ENROLLMENT_CODE'))}


@router.post('/profiles', dependencies=[Depends(same_origin)], status_code=201)
async def register(form: Registration, db: AsyncSession = Depends(get_async_session)):
    code = os.getenv('AGROCHAT_ENROLLMENT_CODE', '')
    supplied = form.enrollment_code.get_secret_value()
    if code and not hmac.compare_digest(code.encode(), supplied.encode()):
        raise HTTPException(403, 'The enrollment code is incorrect.')
    password = form.password.get_secret_value()
    if password != form.confirm_password.get_secret_value():
        raise HTTPException(422, 'Passwords do not match.')
    if not 12 <= len(password) or len(password.encode()) > 72:
        raise HTTPException(422, 'Use at least 12 characters and at most 72 UTF-8 bytes.')
    name = f'{clean_name(form.first_name)} {clean_name(form.surname)}'
    name_key = unicodedata.normalize('NFKC', name).casefold()
    user_id = str(uuid4())
    email = f'{user_id}@profiles.invalid'
    async with registration_lock:
        if await db.scalar(select(func.count()).select_from(User)) >= LIMIT:
            raise HTTPException(409, 'All six profiles are in use.')
        slots = set((await db.scalars(select(profiles.c.slot))).all())
        slot = next((s for s in range(1, LIMIT + 1) if s not in slots), None)
        if slot is None:
            raise HTTPException(409, 'All six profiles are in use.')
        if await db.scalar(select(profiles.c.user_id).where(profiles.c.name_key == name_key)):
            raise HTTPException(409, 'A profile with this name already exists.')
        now = int(time.time())
        user = UserModel(id=user_id, email=email, name=name, role='user', profile_image_url='/user.png',
                         last_active_at=now, created_at=now, updated_at=now)
        db.add(User(**user.model_dump()))
        db.add(Auth(id=user_id, email=email, active=True, session_stamp=str(uuid4()),
                    password=await get_password_hash(password)))
        try:
            await db.execute(insert(profiles).values(user_id=user_id, slot=slot, full_name=name, name_key=name_key,
                                                    paused=False, since=0, revision=0, memory={}))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, 'The profile list changed. Please try again.') from None
    return {'id': user_id, 'name': name, 'slot': slot}


@router.post('/login', dependencies=[Depends(same_origin)])
async def login(form: Login, request: Request, response: Response, db: AsyncSession = Depends(get_async_session)):
    response.headers['Cache-Control'] = 'no-store'
    password = form.password.get_secret_value()
    if len(password.encode()) > 1024:
        raise HTTPException(400, 'Incorrect password.')
    if not await profile_row(db, str(form.profile_id)):
        raise HTTPException(404, 'Profile not found.')
    user = await Users.get_user_by_id(str(form.profile_id), db=db)
    if not user:
        raise HTTPException(404, 'Profile not found.')
    return await signin(request, response, SigninForm(email=user.email, password=password), db)


@router.get('/account')
async def get_account(response: Response, user=Depends(get_verified_user), db=Depends(get_async_session)):
    response.headers['Cache-Control'] = 'no-store'
    row = await profile_row(db, user.id)
    if not row:
        raise HTTPException(404)
    return {'name': row.full_name, 'id': user.id}


@router.post('/account/photo', dependencies=[Depends(same_origin)])
async def set_photo(form: Photo, user=Depends(get_verified_user), db=Depends(get_async_session)):
    url = '/user.png'
    if form.image is not None:
        prefix = 'data:image/jpeg;base64,'
        try:
            if not form.image.startswith(prefix):
                raise ValueError
            decoded = base64.b64decode(form.image.removeprefix(prefix), validate=True)
            with Image.open(io.BytesIO(decoded), formats=['JPEG']) as image:
                if image.width > 256 or image.height > 256:
                    raise ValueError
                out = io.BytesIO()
                image.convert('RGB').save(out, format='JPEG', quality=85)
            url = prefix + base64.b64encode(out.getvalue()).decode()
        except (ValueError, OSError, Image.DecompressionBombError):
            raise HTTPException(422, 'Choose a valid profile photo.') from None
    await Users.update_user_by_id(user.id, {'profile_image_url': url}, db=db)
    return {'ok': True}


@router.post('/account/delete', dependencies=[Depends(same_origin)])
async def delete_account(form: DeleteAccount, request: Request, response: Response,
                         user=Depends(get_verified_user), db=Depends(get_async_session)):
    row = await profile_row(db, user.id)
    if not row or form.full_name.strip() != row.full_name:
        raise HTTPException(422, 'Type your full name exactly as shown.')
    password = form.password.get_secret_value()
    from open_webui.routers.auths import signin_rate_limiter

    if await signin_rate_limiter.is_limited(request.app.state.redis, user.email):
        raise HTTPException(429, 'Too many attempts. Try again later.')
    if len(password.encode()) > 1024 or not await Auths.authenticate_user(
        user.email, lambda stored: verify_password(password, stored), db=db
    ):
        raise HTTPException(400, 'Incorrect password.')
    from open_webui.models.files import Files
    from open_webui.models.folders import Folder
    from open_webui.routers.files import delete_file_by_id

    for file in await Files.get_files_by_user_id(user.id, db=db):
        await delete_file_by_id(request, file.id, user, db)
    # Open WebUI removes group membership in a separate write transaction.
    # Let it do so before writing to SQLite on this session.
    if not await Auths.delete_auth_by_id(user.id, db=db):
        raise HTTPException(500, 'Could not delete the account.')
    await db.execute(delete(Folder).where(Folder.user_id == user.id))
    await db.execute(delete(profiles).where(profiles.c.user_id == user.id))
    await db.commit()
    return await signout(request, response, db)

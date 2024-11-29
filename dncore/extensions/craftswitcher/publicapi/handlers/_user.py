from fastapi import Response, Depends, Request, APIRouter
from fastapi.params import Form

from dncore.extensions.craftswitcher.database.model import User
from dncore.extensions.craftswitcher.publicapi import APIError, APIErrorCode, model
from dncore.extensions.craftswitcher.utils import datetime_now
from .common import *

api = APIRouter(
    tags=["User", ],
    dependencies=[Depends(get_authorized_user)],
)
no_auth_api = APIRouter(
    tags=["User", ],
)


async def getuser(user_id: int):
    user = await db.get_user_by_id(user_id)
    if not user:
        raise APIErrorCode.NOT_EXISTS_USER.of("Unknown user id", 404)
    return user


class OAuth2PasswordRequestForm:
    def __init__(
            self,
            *,
            username: str = Form(),
            password: str = Form(),
    ):
        self.username = username
        self.password = password


@no_auth_api.get(
    "/login",
    summary="セッションが有効かどうかを返す",
)
async def _get_login(request: Request) -> dict:
    try:
        result = bool(await get_authorized_user(request))
    except APIError:
        result = False
    return dict(result=result)


@no_auth_api.post(
    "/login",
    summary="セッションの生成と設定",
)
async def _login(request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
    user = await db.get_user(form_data.username)
    if not user or not db.verify_hash(form_data.password, user.password):
        raise APIErrorCode.INVALID_AUTHENTICATION_CREDENTIALS.of("Invalid authentication credentials", 401)

    _, token, expires_datetime = await db.update_user_token(
        user=user,
        last_login=datetime_now(),
        last_address=request.client.host,
    )

    response.set_cookie(
        key="session",
        value=token,
        expires=expires_datetime,
    )
    return dict(result=True)


@api.get(
    "/users",
    summary="登録されたユーザーの一覧",
)
async def _users() -> list[model.User]:
    return [model.User.create(u) for u in await db.get_users()]


@api.post(
    "/user/add",
    summary="ユーザーを作成",
)
async def _user_add(form_data: OAuth2PasswordRequestForm = Depends()) -> model.UserOperationResult:
    try:
        user_id = await inst.add_user(form_data.username, form_data.password)
    except ValueError:
        raise APIErrorCode.ALREADY_EXISTS_USER_NAME.of("Already exists name")

    return model.UserOperationResult.success(user_id)


@api.delete(
    "/user/remove",
    summary="ユーザーを削除",
)
async def _user_remove(user: User = Depends(getuser)) -> model.UserOperationResult:
    await db.remove_user(user)
    return model.UserOperationResult.success(user.id)

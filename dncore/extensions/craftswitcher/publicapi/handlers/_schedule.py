from typing import TYPE_CHECKING

from fastapi import Depends, APIRouter

from dncore.extensions.craftswitcher.publicapi import model, APIErrorCode
from .common import *

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess

api = APIRouter(
    tags=["Schedule", ],
    dependencies=[Depends(get_authorized_user), ],
)


@api.get(
    "/schedule/timer/types",
    summary="スケジュールタイマーのタイプ一覧",
    description="利用可能なタイマータイプの一覧を返します",
)
def _timer_types() -> list[str]:
    return list(schedules.timer_providers.keys())


@api.get(
    "/schedule/action/types",
    summary="スケジュールアクションのタイプ一覧",
    description="利用可能なアクションタイプの一覧を返します",
)
def _action_types() -> list[str]:
    return list(schedules.action_providers.keys())


@api.get(
    "/schedules",
    summary="スケジュール一覧",
    description="実行を待機している全てのスケジュールを返します",
)
def _schedules(
) -> list[model.Schedule]:
    return [model.Schedule.create(s) for s in schedules.schedules]


@api.get(
    "/schedule/{schedule_id}",
    summary="スケジュールを取得",
    description="実行を待機している指定されたスケジュールを返します",
)
def _get_schedule(
    schedule_id: int,
) -> model.Schedule:
    if schedule := schedules.get_schedule(schedule_id):
        return model.Schedule.create(schedule)
    raise APIErrorCode.SCHEDULE_NOT_FOUND.of("Schedule not found")


@api.delete(
    "/schedule/{schedule_id}",
    summary="スケジュールを削除",
    description="指定されたスケジュールを削除します",
)
async def _delete_schedule(
    schedule_id: int,
) -> bool:
    return await schedules.remove_schedule(schedule_id)


@api.get(
    "/server/{server_id}/schedules",
    summary="スケジュール一覧",
    description="実行を待機しているサーバーのスケジュールを返します",
)
def _server_schedules(
    server: "ServerProcess" = Depends(getserver),
) -> list[model.Schedule]:
    return [model.Schedule.create(s) for s in schedules.get_server_schedules(server.id)]


@api.post(
    "/server/{server_id}/schedule",
    summary="スケジュールの追加",
    description="スケジュールを登録します",
)
def _add_server_schedule(
    server: "ServerProcess" = Depends(getserver),
) -> None:
    return  # TODO: implement add schedule

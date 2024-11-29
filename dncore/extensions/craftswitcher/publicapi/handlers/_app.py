from logging import getLogger
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, Depends, APIRouter
from fastapi.params import Query

from dncore.configuration.configuration import ConfigValues
from dncore.extensions.craftswitcher.abc import ServerType
from dncore.extensions.craftswitcher.publicapi import APIErrorCode, model
from .common import *

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher.config import SwitcherConfig, JavaPresetConfig

log = getLogger(__name__)
api = APIRouter(
    tags=["App", ],
    dependencies=[Depends(get_authorized_user), ],
)
no_auth_api = APIRouter(
    tags=["App", ],
)


@api.get(
    "/config/app",
    summary="Switcher設定の取得",
    description="Switcherの設定を返します",
)
def _get_config() -> model.SwitcherConfig:
    def toflat(keys: list[str], conf: "ConfigValues") -> dict[str, Any]:
        ls = {}
        for key, entry in conf.get_values().items():
            if isinstance(entry.value, ConfigValues):
                ls.update(toflat([*keys, key], entry.value))
            else:
                ls[".".join([*keys, key])] = entry.value
        return ls

    return model.SwitcherConfig(**toflat([], inst.config))


@api.put(
    "/config/app",
    summary="Switcher設定の更新",
    description="Switcherの設定を変更します。変更しない値は省略できます。",
)
def _put_config(param: model.SwitcherConfig) -> model.SwitcherConfig:
    config = inst.config  # type: SwitcherConfig
    changed_keys = set()

    for key, value in param.model_dump(exclude_unset=True).items():
        conf = config
        changed_keys.add(key)
        key = key.split("__")
        while 2 <= len(key):
            conf = getattr(conf, key.pop(0))
        setattr(conf, key[0], value)

    config.save(force=True)
    return _get_config()


@api.get(
    "/config/server_global",
    summary="サーバーのデフォルト設定の取得",
)
async def _get_config_server_global() -> model.ServerGlobalConfig:
    def toflat(keys: list[str], conf: "ConfigValues") -> dict[str, Any]:
        ls = {}
        for key, entry in conf.get_values().items():
            if isinstance(entry.value, ConfigValues):
                ls.update(toflat([*keys, key], entry.value))
            else:
                ls[".".join([*keys, key])] = entry.value
        return ls

    return model.ServerGlobalConfig(**toflat([], inst.config.server_defaults))


@api.put(
    "/config/server_global",
    summary="サーバーのデフォルト設定の更新",
    description="変更しない値を省略できます",
)
async def _put_config_server_global(param: model.ServerGlobalConfig) -> model.ServerGlobalConfig:
    config = inst.config.server_defaults

    for key, value in param.model_dump(exclude_unset=True).items():
        conf = config

        key = key.split("__")
        while 2 <= len(key):
            conf = getattr(conf, key.pop(0))
        setattr(conf, key[0], value)

    inst.config.save(force=True)
    return await _get_config_server_global()


@api.get(
    "/java/preset/list",
    summary="Javaプリセット一覧",
    description=(
            "登録されているJavaプリセットを返します (自動検出したものを含みます)\n\n"
            "`server_type` と `server_version` を指定することで、Javaプリセットがサーバーに推奨されるか評価します。"
    ),
)
async def _get_java_preset_list(
    server_type: ServerType | None = None,
    server_version: str | None = None,
) -> list[model.JavaPreset]:
    presets = []  # type: list[model.JavaPreset]
    config_presets = list(inst.config.java.presets)  # type: list[JavaPresetConfig]

    java_major_version = None
    if server_type and server_version:
        try:
            java_major_version = await inst.get_java_version_from_server_type(server_type, server_version)
        except Exception as e:
            log.warning(f"Failed to get java version by server type: {e}")

    for preset in inst.java_presets:
        registered = preset.config in config_presets

        recommended = None
        if server_type and server_version and preset.info:
            if java_major_version:
                if java_major_version == preset.major_version:
                    recommended = 2
                elif java_major_version < preset.major_version:
                    recommended = 1
                else:
                    recommended = -1
            else:
                recommended = 0

        presets.append(model.JavaPreset(
            name=preset.name,
            executable=preset.executable,
            info=preset.info and model.JavaExecutableInfo.create(preset.info),
            available=bool(preset.info),
            registered=registered,
            recommended=recommended,
        ))

    return presets


@api.get(
    "/java/preset",
    summary="Javaプリセット情報",
)
def _get_java_preset(name: str = Query(description="プリセット名"), ) -> model.JavaPreset:
    config_presets = inst.config.java.presets

    if preset := inst.get_java_preset(name):
        registered = preset.config and preset.config in config_presets or False
        return model.JavaPreset(
            name=preset.name,
            executable=preset.executable,
            info=preset.info and model.JavaExecutableInfo.create(preset.info),
            available=bool(preset.info),
            registered=registered,
        )

    raise APIErrorCode.UNKNOWN_JAVA_PRESET.of(f"Not found preset: {name!r}")


@api.post(
    "/java/preset",
    summary="Javaプリセットを登録",
    description="Javaをテストしてプリセットを登録します。自動追加された同じ名のプリセットは上書きされます。",
)
async def _add_java_preset(
    name: str = Query(description="プリセット名"),
    executable: str = Query(description="Javaコマンドかパス"),
) -> model.JavaPreset:
    try:
        preset = await inst.add_java_preset(name, executable)
    except ValueError:
        raise APIErrorCode.ALREADY_EXISTS_ID.of(f"Already exists name: {name!r}")

    return model.JavaPreset(
        name=preset.name,
        executable=preset.executable,
        info=preset.info and model.JavaExecutableInfo.create(preset.info),
        available=bool(preset.info),
        registered=True,
    )


@api.delete(
    "/java/preset",
    summary="Javaプリセットを削除",
    description="該当するプリセット名を削除します。削除したものがあれば true を返します。",
)
async def _remove_java_preset(
    name: str = Query(description="プリセット名"),
) -> bool:
    return inst.remove_java_preset(name)


@api.get(
    "/java/detect/list",
    summary="検出されたJava一覧",
)
def _get_java_detect_list() -> list[model.JavaExecutableInfo]:
    return [model.JavaExecutableInfo.create(i) for i in inst.java_detections]


@api.post(
    "/java/detect/rescan",
    summary="Javaを再検出し、プリセットとリストを更新します",
)
async def _post_java_rescan() -> list[model.JavaPreset]:
    await inst.scan_java_executables()
    return await _get_java_preset_list()


@no_auth_api.websocket(
    "/ws",
    dependencies=[Depends(get_authorized_user_ws), ],
)
async def _websocket(websocket: WebSocket):
    return await api_handler._ws_handler(websocket)

import shutil

from fastapi import UploadFile, Depends, APIRouter
from fastapi.responses import FileResponse, JSONResponse

from dncore.extensions.craftswitcher.ext import SwitcherExtension, ExtensionInfo, EditableFile
from dncore.extensions.craftswitcher.publicapi import APIErrorCode, model
from .common import *

api = APIRouter(
    tags=["Plugins", ],
    dependencies=[Depends(get_authorized_user), ],
)


def getplugin(plugin_name: str):
    extension, info = inst.extensions.get_info(plugin_name)
    if not extension or not info:
        raise APIErrorCode.PLUGIN_NOT_FOUND.of("Plugin not found", 404)
    return extension, info


def getfile(key: str, plugin: tuple[SwitcherExtension, ExtensionInfo] = Depends(getplugin)):
    ext, info = plugin
    for file in ext.editable_files:
        if file.key == key:
            return file
    raise APIErrorCode.NOT_EXISTS_PLUGIN_FILE.of("Plugin file not found", 404)


@api.get(
    "/plugins",
    summary="プラグイン一覧",
)
def _plugins() -> list[model.PluginInfo]:
    return [
        model.PluginInfo.create(info, ext.editable_files)
        for ext, info in inst.extensions.extensions.items()
    ]


@api.get(
    "/plugin/{plugin_name}/file/{key}",
    summary="設定ファイルを取得",
    responses={400: {"model": model.PluginMessageResponse, }},
)
async def _plugin_file(
    plugin: tuple[SwitcherExtension, ExtensionInfo] = Depends(getplugin),
    file: EditableFile = Depends(getfile),
) -> FileResponse:
    ext, info = plugin

    res = await ext.on_file_load(file)
    if res:
        # noinspection PyTypeChecker
        return JSONResponse(status_code=400, content=model.PluginMessageResponse(
            caption=res.caption,
            content=res.content,
            errors=res.errors,
        ).model_dump_json())

    return FileResponse(file.path, filename=file.path.name)


@api.post(
    "/plugin/{plugin_name}/file/{key}",
    summary="設定ファイルを更新",
    responses={400: {"model": model.PluginMessageResponse, }},
)
async def _plugin_file(
    content: UploadFile,
    plugin: tuple[SwitcherExtension, ExtensionInfo] = Depends(getplugin),
    file: EditableFile = Depends(getfile),
) -> model.FileOperationResult:
    ext, info = plugin

    res = await ext.on_file_pre_update(file)
    if res:
        # noinspection PyTypeChecker
        return JSONResponse(status_code=400, content=model.PluginMessageResponse(
            caption=res.caption,
            content=res.content,
            errors=res.errors,
        ).model_dump_json())

    try:
        with file.path.open("wb") as f:
            # noinspection PyTypeChecker
            shutil.copyfileobj(content.file, f)
    finally:
        content.file.close()

    res = await ext.on_file_update(file)
    if res:
        # noinspection PyTypeChecker
        return JSONResponse(status_code=400, content=model.PluginMessageResponse(
            caption=res.caption,
            content=res.content,
            errors=res.errors,
        ).model_dump_json())

    return model.FileOperationResult.success(None, None)

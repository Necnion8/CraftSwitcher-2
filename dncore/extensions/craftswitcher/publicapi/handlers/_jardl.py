from fastapi import Depends, APIRouter

from dncore.extensions.craftswitcher.abc import ServerType
from dncore.extensions.craftswitcher.jardl import ServerDownloader, ServerMCVersion, ServerBuild
from dncore.extensions.craftswitcher.publicapi import model
from .common import *

api = APIRouter(
    prefix="/jardl",
    tags=["Server Installer", ],
    dependencies=[Depends(get_authorized_user), ],
)


@api.get(
    "/types",
    summary="利用可能なサーバーのタイプ",
)
def __lists() -> list[ServerType]:
    return [typ for typ, ls in inst.server_downloaders.items() if ls]


@api.get(
    "/{server_type}/versions",
    summary="対応バージョンの一覧"
)
async def __versions(downloader: ServerDownloader = Depends(getdownloader)) -> list[model.JarDLVersionInfo]:
    versions = await downloader.list_versions()

    return [model.JarDLVersionInfo(
        version=v.mc_version,
        build_count=None if v.builds is None else len(v.builds)
    ) for v in versions]


@api.get(
    "/{server_type}/version/{version}/builds",
    summary="ビルドの一覧",
)
async def __builds(version: ServerMCVersion = Depends(getversion)) -> list[model.JarDLBuildInfo]:
    builds = await version.list_builds()

    return [model.JarDLBuildInfo(
        build=b.build,
        download_url=b.download_url,
        java_major_version=b.java_major_version,
        require_jdk=b.require_jdk,
        updated_datetime=b.updated_datetime,
        recommended=b.recommended,
        is_require_build=b.is_require_build(),
        is_loaded_info=b.is_loaded_info(),
    ) for b in builds]


@api.get(
    "/{server_type}/version/{version}/build/{build}",
    summary="ビルドの情報",
    description="ビルドの追加情報を取得して返します。"
)
async def __build_info(build: ServerBuild = Depends(getbuild)) -> model.JarDLBuildInfo:
    await build.fetch_info()
    return model.JarDLBuildInfo(
        build=build.build,
        download_url=build.download_url,
        java_major_version=build.java_major_version,
        require_jdk=build.require_jdk,
        updated_datetime=build.updated_datetime,
        recommended=build.recommended,
        is_require_build=build.is_require_build(),
        is_loaded_info=build.is_loaded_info(),
    )

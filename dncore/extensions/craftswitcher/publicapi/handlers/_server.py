from typing import TYPE_CHECKING, Any

from fastapi import Depends, APIRouter
from fastapi.params import Query

from dncore.configuration.configuration import ConfigValues
from dncore.extensions.craftswitcher import errors
from dncore.extensions.craftswitcher.abc import ServerType, ServerState
from dncore.extensions.craftswitcher.errors import NoDownloadFile
from dncore.extensions.craftswitcher.jardl import ServerBuild
from dncore.extensions.craftswitcher.publicapi import APIErrorCode, model
from .common import *

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess
    from dncore.extensions.craftswitcher.config import ServerConfig

api = APIRouter(
    tags=["Server", ],
    dependencies=[Depends(get_authorized_user), ],
)


@api.get(
    "/servers",
    summary="登録サーバーの一覧",
    description="登録されているサーバーを返します",
)
async def _list(
    only_loaded: bool = False,
    include_status: bool = Query(False, description="サーバーとプロセスの情報を取得するか"),
) -> list[model.Server]:
    ls = []  # type: list[model.Server]

    for server_id, server in servers.items():
        if server:
            try:
                server_swi_path = inst.swipath_server(server)
            except ValueError:
                server_swi_path = None
            ls.append(model.Server.create(server, server_swi_path, include_status))
        elif not only_loaded:
            try:
                server_dir = inst.config.servers[server_id]
            except KeyError:
                continue  # 外部から削除または変更されていた場合はリストから静かに除外する
            ls.append(model.Server.create_no_data(server_id, inst.files.resolvepath(server_dir, force=True)))

    return ls


@api.post(
    "/server/{server_id}/start",
    summary="サーバーを起動",
    description="サーバーを起動します。\nbuild_status が STANDBY の場合はサーバーを起動せず、代わりにビルダーを実行します。",
)
async def _start(server: "ServerProcess" = Depends(getserver),
                 no_build: bool = Query(False, description="ビルダーが設定されていてもビルドを実行しません"),
                 ) -> model.ServerOperationResult:
    try:
        await server.start(no_build=no_build)
    except errors.AlreadyRunningError:
        raise APIErrorCode.SERVER_ALREADY_RUNNING.of("Already running")
    except errors.UnknownJavaPreset as e:
        raise APIErrorCode.UNKNOWN_JAVA_PRESET.of(f"Unknown java preset: {e}")
    except errors.OutOfMemoryError:
        raise APIErrorCode.OUT_OF_MEMORY.of("Out of memory")
    except errors.ServerLaunchError as e:
        raise APIErrorCode.SERVER_LAUNCH_ERROR.of(f"Failed to launch: {e}")
    except errors.OperationCancelledError as e:
        raise APIErrorCode.OPERATION_CANCELLED.of(f"Operation cancelled: {e}")

    return model.ServerOperationResult.success(server.id)


@api.post(
    "/server/{server_id}/stop",
    summary="サーバーを停止",
    description="サーバーを停止します",
)
async def _stop(server: "ServerProcess" = Depends(getserver), ) -> model.ServerOperationResult:
    try:
        await server.stop()
    except errors.NotRunningError:
        raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")
    except errors.ServerProcessingError:
        raise APIErrorCode.SERVER_PROCESSING.of("Server is processing")

    return model.ServerOperationResult.success(server.id)


@api.post(
    "/server/{server_id}/restart",
    summary="サーバーを再起動",
    description="サーバーを再起動します",
)
async def _restart(server: "ServerProcess" = Depends(getserver), ) -> model.ServerOperationResult:
    try:
        await server.restart()
    except errors.NotRunningError:
        raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")
    except errors.ServerProcessingError:
        raise APIErrorCode.SERVER_PROCESSING.of("Server is processing")

    return model.ServerOperationResult.success(server.id)


@api.post(
    "/server/{server_id}/kill",
    summary="サーバーを強制終了",
    description="サーバーを強制終了します",
)
async def _kill(server: "ServerProcess" = Depends(getserver), ) -> model.ServerOperationResult:
    try:
        await server.kill()
    except errors.NotRunningError:
        raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")

    return model.ServerOperationResult.success(server.id)


@api.post(
    "/server/{server_id}/send_line",
    summary="サーバープロセスに送信",
    description="コマンド文などの文字列をサーバープロセスへ書き込みます",
)
async def _send_line(line: str, server: "ServerProcess" = Depends(getserver), ) -> model.ServerOperationResult:
    try:
        await server.send_command(line)
    except errors.NotRunningError:
        raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")
    return model.ServerOperationResult.success(server.id)


@api.get(
    "/server/{server_id}/term/size",
    summary="疑似端末のウインドウサイズを取得",
    description="幅x高のカーソル数を返します",
)
def _get_term_size(
    server: "ServerProcess" = Depends(getserver),
) -> tuple[int, int]:
    return server.term_size


@api.post(
    "/server/{server_id}/term/size",
    summary="疑似端末のウインドウサイズを設定",
    description="幅x高のカーソル数を返します",
)
def _set_term_size(
    cols: int, rows: int,
    server: "ServerProcess" = Depends(getserver),
) -> tuple[int, int]:
    server.set_term_size(cols, rows)
    return server.term_size


@api.get(
    "/server/{server_id}/logs/latest",
    summary="サーバープロセスの出力ログ",
)
def _logs_latest(
    server: "ServerProcess" = Depends(getserver),
    max_lines: int | None = Query(None, ge=1, description=(
            "取得する最大行数。null でキャッシュされている全ての行を出力します。"
    )),
    include_buffer: bool = Query(False, description="改行されていない行を含みます"),
) -> list[str]:
    logs = server.logs
    ls = list(logs) if max_lines is None else list(logs)[-max_lines + include_buffer:]
    if include_buffer:
        ls.append(logs.buffer)
    return ls


@api.post(
    "/server/{server_id}/import",
    summary="構成済みのサーバーを追加",
    description="構成済みのサーバーを登録します",
)
async def _add(
    server_id: str,
    param: model.AddServerParam,
    eula: bool | None = Query(False, description="Minecraft EULA に同意されていれば true にできます"),
) -> model.ServerOperationResult:
    server_id = server_id.lower()
    if server_id in servers:
        raise APIErrorCode.ALREADY_EXISTS_ID.of("Already exists server id")

    server_dir = realpath(param.directory)
    if not server_dir.is_dir():
        raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Not exists directory")

    try:
        config = inst.import_server_config(server_dir)
    except FileNotFoundError:
        raise APIErrorCode.NOT_EXISTS_CONFIG_FILE.of("Not exists server config")

    server = inst.create_server(server_id, server_dir, config, set_creation_date=False, set_accept_eula=eula)
    return model.ServerOperationResult.success(server.id)


@api.get(
    "/server/{server_id}",
    summary="サーバー情報を取得",
)
def _get(
    server_id: str,
    include_status: bool = Query(False, description="サーバーとプロセスの情報を取得するか"),
) -> model.Server:
    server_id = server_id.lower()
    try:
        server = servers[server_id]
    except KeyError:
        raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

    if server is None:
        try:
            _server_dir = inst.config.servers[server_id]
            server_dir = inst.files.resolvepath(_server_dir, force=True)
        except KeyError:
            # 外部から削除または変更されていた場合はリストから静かに除外する
            raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

        return model.Server.create_no_data(server_id, server_dir)

    try:
        server_swi_path = inst.swipath_server(server)
    except ValueError:
        server_swi_path = None

    return model.Server.create(server, server_swi_path, include_status)


@api.post(
    "/server/{server_id}",
    summary="サーバーを作成",
    description="サーバーを作成します",
)
async def _create(
    server_id: str,
    param: model.CreateServerParam,
    eula: bool | None = Query(False, description="Minecraft EULA に同意されていれば true にできます"),
) -> model.ServerOperationResult:
    server_id = server_id.lower()
    if server_id in servers:
        raise APIErrorCode.ALREADY_EXISTS_ID.of("Already exists server id")

    server_dir = realpath(param.directory)
    if server_dir.exists():
        raise APIErrorCode.ALREADY_EXISTS_PATH.of("Already exists server directory")
    if not server_dir.parent.is_dir():
        raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Not exists parent directory")

    config = inst.create_server_config(server_dir)  # type: ServerConfig
    config.name = param.name
    config.type = param.type
    config.launch_option.java_preset = param.launch_option.java_preset
    config.launch_option.java_executable = param.launch_option.java_executable
    config.launch_option.java_options = param.launch_option.java_options
    config.launch_option.jar_file = param.launch_option.jar_file
    config.launch_option.server_options = param.launch_option.server_options
    config.launch_option.max_heap_memory = param.launch_option.max_heap_memory
    config.launch_option.min_heap_memory = param.launch_option.min_heap_memory
    config.launch_option.enable_free_memory_check = param.launch_option.enable_free_memory_check
    config.launch_option.enable_reporter_agent = param.launch_option.enable_reporter_agent
    config.launch_option.enable_screen = param.launch_option.enable_screen
    config.enable_launch_command = param.enable_launch_command
    config.launch_command = param.launch_command
    config.stop_command = param.stop_command
    config.shutdown_timeout = param.shutdown_timeout

    server = inst.create_server(server_id, server_dir, config, set_accept_eula=eula)

    return model.ServerOperationResult.success(server.id)


@api.delete(
    "/server/{server_id}",
    summary="サーバーを削除",
    description="サーバーを削除します",
)
async def _delete(server_id: str, delete_config_file: bool = False, ) -> model.ServerOperationResult:
    server_id = server_id.lower()
    try:
        server = servers[server_id]
    except KeyError:
        raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

    if server:
        if server.state.is_running:
            raise APIErrorCode.SERVER_ALREADY_RUNNING.of("Already running")
        inst.delete_server(server, delete_server_config=delete_config_file)

    else:
        inst.delete_server(server_id, delete_server_config=delete_config_file)

    return model.ServerOperationResult.success(server.id if server else server_id)


@api.get(
    "/server/{server_id}/config",
    summary="サーバー設定の取得",
    description="サーバーの設定を返します",
)
async def _get_config(server: "ServerProcess" = Depends(getserver), ) -> model.ServerConfig:
    def toflat(keys: list[str], conf: "ConfigValues") -> dict[str, Any]:
        ls = {}
        for key, entry in conf.get_values().items():
            if isinstance(entry.value, ConfigValues):
                ls.update(toflat([*keys, key], entry.value))
            else:
                ls[".".join([*keys, key])] = entry.value
        return ls

    return model.ServerConfig(**toflat([], server._config))


@api.put(
    "/server/{server_id}/config",
    summary="サーバー設定の更新",
    description="サーバーの設定を変更します。変更しない値は省略できます。",
)
async def _put_config(param: model.ServerConfig, server: "ServerProcess" = Depends(getserver),
                      ) -> model.ServerConfig:
    config = server._config  # type: ServerConfig
    for key, value in param.model_dump(exclude_unset=True).items():
        conf = config

        key = key.split("__")
        while 2 <= len(key):
            conf = getattr(conf, key.pop(0))
        setattr(conf, key[0], value)

    server._config.save(force=True)
    return await _get_config(server)


@api.post(
    "/server/{server_id}/config/reload",
    summary="サーバー設定ファイルの再読み込み",
    description="設定ファイルを再読み込みします",
)
async def _reload_config(server: "ServerProcess" = Depends(getserver), ) -> model.ServerConfig:
    server._config.load()
    return await _get_config(server)


@api.get(
    "/server/{server_id}/eula",
    summary="EULA の値を取得",
    description="EULAファイルの値を返します",
)
def _get_eula(server: "ServerProcess" = Depends(getserver), ) -> bool | None:
    try:
        return server.is_eula_accepted(ignore_not_exists=False)
    except FileNotFoundError:
        return None


@api.post(
    "/server/{server_id}/eula",
    summary="EULA の値を設定",
    description="EULAファイルの値を変更します",
)
def _post_eula(
    server: "ServerProcess" = Depends(getserver),
    accept: bool = Query(description="Minecraft EULA に同意されていれば true にできます"),
) -> model.FileInfo:
    eula_path = server.set_eula_accept(accept)
    return inst.create_file_info(eula_path, root_dir=server.directory)


@api.post(
    "/server/{server_id}/install",
    summary="サーバーJarのインストール",
    description="ビルドが必要な場合は、サーバーの初回起動時に実行されます。"
)
async def _post_install(
    server_type: ServerType,
    server: "ServerProcess" = Depends(getserver),
    build: ServerBuild = Depends(getbuild),
    java_preset: str | None = Query(None, description="ビルダーに使用するJavaプリセット名"),
) -> model.FileOperationResult:
    _java_preset = java_preset and inst.get_java_preset(java_preset) or None
    if java_preset and not _java_preset:
        raise APIErrorCode.UNKNOWN_JAVA_PRESET.of(f"Unknown java preset: {java_preset!r}")

    try:
        task = await inst.download_server_jar(server, build, server_type, builder_java_preset=_java_preset)
    except NoDownloadFile as e:
        raise APIErrorCode.NO_AVAILABLE_DOWNLOAD.of(str(e))
    return model.FileOperationResult.pending(task.id)


@api.delete(
    "/server/{server_id}/build",
    summary="ビルダーを削除します",
)
async def _delete_build(
    server: "ServerProcess" = Depends(getserver),
) -> model.ServerOperationResult:
    if ServerState.BUILD == server.state:
        return model.ServerOperationResult.failed(server)

    await server.clean_builder()
    return model.ServerOperationResult.success(server)

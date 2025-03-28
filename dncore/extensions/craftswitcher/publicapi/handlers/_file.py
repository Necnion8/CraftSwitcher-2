import asyncio
import shutil
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, NamedTuple

from fastapi import UploadFile, Depends, APIRouter
from fastapi.params import Form, Query
from fastapi.responses import FileResponse

from dncore.extensions.craftswitcher.errors import NoArchiveHelperError
from dncore.extensions.craftswitcher.files import FileTask, FileEventType
from dncore.extensions.craftswitcher.publicapi import APIError, APIErrorCode, model
from dncore.extensions.craftswitcher.publicapi.server import StreamingResponse
from dncore.extensions.craftswitcher.utils import disk_usage
from .common import *

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess

log = getLogger(__name__)
api = APIRouter(
    tags=["File", ],
    dependencies=[Depends(get_authorized_user), ],
)


class PairPath(NamedTuple):
    real: Path
    swi: str
    server: "ServerProcess | None"
    root_dir: Path | None


def create_file_info(path: PairPath | Path, root_dir: Path = None):
    if isinstance(path, PairPath):
        _path = path.real
        root_dir = root_dir or path.root_dir
    else:
        _path = path

    return inst.create_file_info(_path, root_dir=root_dir)


def wait_for_task(task: FileTask, timeout: float | None = 1) -> Coroutine[Any, Any, FileTask]:
    return asyncio.wait_for(asyncio.shield(task.fut), timeout=timeout)


# param


def get_pair_path(swi_path: str, *, server: "ServerProcess" = None):
    root_dir = server and server.directory or None  # type: Path | None
    try:
        real_path = files.realpath(swi_path, root_dir=root_dir)
    except ValueError as e:
        raise APIErrorCode.NOT_ALLOWED_PATH.of(f"{e}: {swi_path}")
    swi_path = files.swipath(real_path, force=True, root_dir=root_dir)
    return PairPath(real_path, swi_path, server, root_dir)


def get_path_of_root(query: str | Query = None, *, is_dir=False, is_file=False, exists=False, no_exists=False):
    if query is None or isinstance(query, Query):
        name = query and query.alias or "path"
    else:
        name = "path"
        query = Query(description=query)

    def check(path: str = query) -> PairPath:
        p = get_pair_path(path)
        if no_exists and p.real.exists():
            if p.real.is_dir():
                raise APIErrorCode.EXIST_DIRECTORY.of(f"Directory already exists: {name!r}")
            elif p.real.is_file():
                raise APIErrorCode.EXIST_FILE.of(f"File already exists: {name!r}")
            raise APIErrorCode.ALREADY_EXISTS_PATH.of(f"Already exists: {name!r}")
        elif is_dir and not p.real.is_dir():
            raise APIErrorCode.NOT_EXISTS_DIRECTORY.of(f"Not a directory or not exists: {name!r}", 404)
        elif is_file and not p.real.is_file():
            raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: {name!r}", 404)
        elif exists and not p.real.exists():
            raise APIErrorCode.NOT_EXISTS_PATH.of(f"Not exists: {name!r}", 404)
        return p

    return check


def get_path_of_server_root(query: str | Query = None, *, is_dir=False, is_file=False, exists=False,
                            no_exists=False):
    if query is None or isinstance(query, Query):
        name = query and query.alias or "path"
    else:
        name = "path"
        query = Query(description=query)

    def check(path: str = query, server: "ServerProcess" = Depends(getserver)) -> PairPath:
        p = get_pair_path(path, server=server)
        if no_exists and p.real.exists():
            if p.real.is_dir():
                raise APIErrorCode.EXIST_DIRECTORY.of(f"Directory already exists: {name!r}")
            elif p.real.is_file():
                raise APIErrorCode.EXIST_FILE.of(f"File already exists: {name!r}")
            raise APIErrorCode.ALREADY_EXISTS_PATH.of(f"Already exists: {name!r}")
        elif is_dir and not p.real.is_dir():
            raise APIErrorCode.NOT_EXISTS_DIRECTORY.of(f"Not a directory or not exists: {name!r}", 404)
        elif is_file and not p.real.is_file():
            raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: {name!r}", 404)
        elif exists and not p.real.exists():
            raise APIErrorCode.NOT_EXISTS_PATH.of(f"Not exists: {name!r}", 404)
        return p

    return check


# method

@api.get(
    "/file/tasks",
    summary="ファイルタスクの一覧",
    description="実行中のファイル操作タスクのリストを返す",
)
def _file_tasks() -> list[model.FileTask | model.BackupTask]:
    return [model.FileTask.create(task) for task in files.tasks]


@api.get(
    "/files",
    summary="ファイルの一覧",
    description="指定されたパスのファイルリストを返す",
)
async def _files(
    path: PairPath = Depends(get_path_of_root(is_dir=True)),
) -> model.FileDirectoryInfo:
    file_list = []
    try:
        for child in path.real.iterdir():
            try:
                file_list.append(create_file_info(child, path.root_dir))
            except Exception as e:
                log.warning("Failed to get file info: %s: %s", str(child), str(e))
    except PermissionError as e:
        raise APIErrorCode.NOT_ALLOWED_PATH.of(f"Unable to access: {e}")

    return model.FileDirectoryInfo(
        name="" if path.swi == "/" else path.real.name,
        path=files.swipath(path.real.parent, force=True, root_dir=path.root_dir),
        children=file_list,
    )


@api.get(
    "/file/info",
    summary="ファイル情報",
)
def _file_info(
    path: PairPath = Depends(get_path_of_root(exists=True)),
) -> model.FileInfo:
    return create_file_info(path, path.root_dir)


@api.get(
    "/file",
    summary="ファイルデータを取得",
    description="",
)
def _get_file(
    path: PairPath = Depends(get_path_of_root(is_file=True)),
):
    return FileResponse(path.real, filename=path.real.name)


@api.post(
    "/file",
    summary="ファイルデータを保存",
    description="",
)
async def _post_file(
    file: UploadFile,
    path: PairPath = Depends(get_path_of_root()),
    override: bool = Query(True, description="上書きを許可"),
) -> model.FileInfo:
    if not override and path.real.exists():
        raise APIErrorCode.ALREADY_EXISTS_PATH.of(f"Already exists: 'path'")
    if path.real.is_dir():
        raise APIErrorCode.NOT_FILE.of("Not a file: 'path'")

    def _do():
        try:
            with path.real.open("wb") as f:
                # noinspection PyTypeChecker
                shutil.copyfileobj(file.file, f)
        finally:
            file.file.close()

    await files.create_task_in_executor(
        FileEventType.CREATE, path.real, None, _do, executor=None,
        server=path.server, src_swi_path=path.swi, dst_swi_path=None,
    )
    return create_file_info(path, path.root_dir)


@api.delete(
    "/file",
    summary="ファイルを削除",
    description="",
)
async def _delete_file(
    path: PairPath = Depends(get_path_of_root(exists=True)),
) -> model.FileOperationResult:
    task = files.delete(path.real, path.server, path.swi)
    try:
        await wait_for_task(task)
    except asyncio.TimeoutError:
        return model.FileOperationResult.pending(task.id)
    except Exception as e:
        log.warning(f"Failed to delete: {e}: {path}")
        return model.FileOperationResult.failed(task.id)
    else:
        return model.FileOperationResult.success(task.id, None)


@api.post(
    "/file/mkdir",
    summary="空のディレクトリ作成",
    description="",
)
async def _mkdir(
    path: PairPath = Depends(get_path_of_root(no_exists=True)),
    parents: bool = Query(False, description="親ディレクトリも作成します"),
) -> model.FileOperationResult:
    try:
        await files.mkdir(path.real, parents=parents)
    except FileNotFoundError:
        raise APIErrorCode.NOT_EXISTS_PATH.of(f"Not exists parents: 'path'")
    except Exception as e:
        log.warning(f"Failed to mkdir: {e}: {path}")
        return model.FileOperationResult.failed(None)
    else:
        return model.FileOperationResult.success(None, create_file_info(path))


@api.put(
    "/file/copy",
    summary="ファイル複製",
    description="",
)
async def _copy(
    path: PairPath = Depends(get_path_of_root(exists=True)),
    dst_path: PairPath = Depends(get_path_of_root(Query(alias="dst_path"), no_exists=True)),
) -> model.FileOperationResult:
    task = files.copy(
        path.real, dst_path.real,
        server=path.server, src_swi_path=path.swi, dst_swi_path=dst_path.swi,
    )
    try:
        await wait_for_task(task)
    except asyncio.TimeoutError:
        return model.FileOperationResult.pending(task.id)
    except Exception as e:
        log.warning(f"Failed to copy: {e}: {path}")
        return model.FileOperationResult.failed(task.id)
    else:
        return model.FileOperationResult.success(task.id, create_file_info(dst_path))


@api.put(
    "/file/move",
    summary="ファイル移動",
    description="",
)
async def _move(
    path: PairPath = Depends(get_path_of_root(exists=True)),
    dst_path: PairPath = Depends(get_path_of_root(Query(alias="dst_path"), no_exists=True)),
) -> model.FileOperationResult:
    task = files.move(
        path.real, dst_path.real,
        server=path.server, src_swi_path=path.swi, dst_swi_path=dst_path.swi,
    )
    try:
        await wait_for_task(task)
    except asyncio.TimeoutError:
        return model.FileOperationResult.pending(task.id)
    except Exception as e:
        log.warning(f"Failed to move: {e}: {path}")
        return model.FileOperationResult.failed(task.id)
    else:
        return model.FileOperationResult.success(task.id, create_file_info(dst_path))


@api.post(
    "/file/archive/files",
    summary="アーカイブ内のファイル一覧",
    description="",
)
async def _archive_files(
    path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", is_file=True)),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),
) -> list[model.ArchiveFile]:
    try:
        arc_files = await files.list_archive(path.real, password=password, ignore_suffix=ignore_suffix)
    except NoArchiveHelperError as e:
        raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
    return [model.ArchiveFile.create(arc_file) for arc_file in arc_files]


@api.get(
    "/file/archive/file",
    summary="アーカイブに含まれるファイルの取得",
)
async def _archive_extract_file(
    path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", is_file=True)),
    filename: str = Query(description="取得するファイルのパス"),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),

) -> StreamingResponse:
    chunk_size = 1024 * 512

    helper = files.find_archive_helper(path.real, ignore_suffix=ignore_suffix)
    if not helper:
        raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of("No supported archive helper")

    async def _processing():
        try:
            # noinspection PyTypeChecker
            async for chunk in helper.extract_archived_file(
                    path.real, filename, password=password, chunk_size=chunk_size,
            ):
                yield chunk

        except FileNotFoundError:
            raise APIErrorCode.NOT_EXISTS_FILE.of("File not found in archive")

    return StreamingResponse(_processing(), filename)


@api.post(
    "/file/archive/extract",
    summary="アーカイブの展開",
    description="",
)
async def _archive_extract(
    path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", is_file=True)),
    output_dir: PairPath = Depends(
        get_path_of_root(Query(alias="output_dir", description="解凍先のフォルダパス"))),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),

) -> model.FileOperationResult:
    if not output_dir.real.parent.is_dir():
        raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Output path parent is not exists", 404)

    try:
        task = await files.extract_archive(
            path.real, output_dir.real, password,
            server=path.server, src_swi_path=path.swi, dst_swi_path=output_dir.swi, ignore_suffix=ignore_suffix,
        )
    except NoArchiveHelperError as e:
        raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
    return model.FileOperationResult.pending(task.id)


@api.post(
    "/file/archive/make",
    summary="アーカイブファイルの作成",
    description="",
)
async def _archive_make(
    path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", no_exists=True)),
    files_root: PairPath = Depends(
        get_path_of_root(Query(alias="files_root", description="格納するファイルのルートパス"))),
    include_files: list[str] = Query(description="格納するファイルのパス"),
) -> model.FileOperationResult:
    try:
        include_files = [realpath(p, root_dir=files_root.root_dir) for p in include_files]
    except APIError:
        raise

    if not any(p.exists() for p in include_files):
        raise APIErrorCode.NOT_EXISTS_PATH.of("No files")

    try:
        task = await files.make_archive(
            path.real, files_root.real, include_files,
            server=path.server, src_swi_path=path.swi,
        )
    except NoArchiveHelperError as e:
        raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
    return model.FileOperationResult.pending(task.id)


# server

@api.get(
    "/server/{server_id}/files",
    summary="ファイルの一覧",
    description="指定されたパスのファイルリストを返す",
)
async def _server_files(
    path: PairPath = Depends(get_path_of_server_root(is_dir=True)),
) -> model.FileDirectoryInfo:
    return await _files(path)


@api.get(
    "/server/{server_id}/file/info",
    summary="ファイル情報",
)
def _server_file_info(
    path: PairPath = Depends(get_path_of_server_root(exists=True)),
) -> model.FileInfo:
    return _file_info(path)


@api.get(
    "/server/{server_id}/file",
    summary="ファイルデータを取得",
    description="",
)
def _server_get_file(
    path: PairPath = Depends(get_path_of_server_root(is_file=True)),
):
    return _get_file(path)


@api.post(
    "/server/{server_id}/file",
    summary="ファイルデータを保存",
    description="",
)
async def _server_post_file(
    file: UploadFile,
    path: PairPath = Depends(get_path_of_server_root()),
    override: bool = Query(True, description="上書きを許可"),
) -> model.FileInfo:
    return await _post_file(file, path, override)


@api.delete(
    "/server/{server_id}/file",
    summary="ファイルを削除",
    description="",
)
async def _server_delete_file(
    path: PairPath = Depends(get_path_of_server_root(exists=True)),
) -> model.FileOperationResult:
    return await _delete_file(path)


@api.post(
    "/server/{server_id}/file/mkdir",
    summary="空のディレクトリ作成",
    description="",
)
async def _server_mkdir(
    path: PairPath = Depends(get_path_of_server_root(no_exists=True)),
    parents: bool = Query(False, description="親ディレクトリも作成します"),
) -> model.FileOperationResult:
    return await _mkdir(path, parents)


@api.put(
    "/server/{server_id}/file/copy",
    summary="ファイル複製",
    description="",
)
async def _server_copy(
    path: PairPath = Depends(get_path_of_server_root(exists=True)),
    dst_path: PairPath = Depends(get_path_of_server_root(Query(alias="dst_path"), no_exists=True)),
) -> model.FileOperationResult:
    return await _copy(path, dst_path)


@api.put(
    "/server/{server_id}/file/move",
    summary="ファイル移動",
    description="",
)
async def _server_move(
    path: PairPath = Depends(get_path_of_server_root(exists=True)),
    dst_path: PairPath = Depends(get_path_of_server_root(Query(alias="dst_path"), no_exists=True)),
) -> model.FileOperationResult:
    return await _move(path, dst_path)


@api.post(
    "/server/{server_id}/file/archive/files",
    summary="アーカイブ内のファイル一覧",
    description="",
)
async def _server_archive_files(
    path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", is_file=True)),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),
) -> list[model.ArchiveFile]:
    return await _archive_files(path, password, ignore_suffix)


@api.get(
    "/server/{server_id}/file/archive/file",
    summary="アーカイブに含まれるファイルの取得",
)
async def _server_archive_extract_file(
    path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", is_file=True)),
    filename: str = Query(description="取得するファイルのパス"),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),

) -> StreamingResponse:
    return await _archive_extract_file(path, filename, password, ignore_suffix)


@api.post(
    "/server/{server_id}/file/archive/extract",
    summary="アーカイブの展開",
    description="",
)
async def _server_archive_extract(
    path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", is_file=True)),
    output_dir: PairPath = Depends(
        get_path_of_server_root(Query(alias="output_dir", description="解凍先のフォルダパス"))),
    password: str | None = Form(None),
    ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),

) -> model.FileOperationResult:
    return await _archive_extract(path, output_dir, password, ignore_suffix)


@api.post(
    "/server/{server_id}/file/archive/make",
    summary="アーカイブファイルの作成",
    description="",
)
async def _server_archive_make(
    path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", no_exists=True)),
    files_root: PairPath = Depends(
        get_path_of_server_root(Query(alias="files_root", description="格納するファイルのルートパス"))),
    include_files: list[str] = Query(description="格納するファイルのパス"),
) -> model.FileOperationResult:
    return await _archive_make(path, files_root, include_files)


@api.get(
    "/storage/info",
    summary="ディスク使用量の取得",
)
def _storage_info(server_id: str | None = None) -> model.StorageInfo:
    if server_id is not None:
        info = disk_usage(getserver(server_id).directory)
    else:
        info = disk_usage(files.root_dir)
    return model.StorageInfo(
        total_size=info.total_bytes,
        used_size=info.used_bytes,
        free_size=info.free_bytes,
    )

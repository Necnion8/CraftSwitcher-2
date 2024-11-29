from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from fastapi import Depends, APIRouter
from fastapi.params import Query
from fastapi.responses import FileResponse

from dncore.extensions.craftswitcher.database.model import SnapshotErrorFile
from dncore.extensions.craftswitcher.errors import NoArchiveHelperError
from dncore.extensions.craftswitcher.fileback.abc import BackupFileErrorType, FileInfo, SnapshotStatus
from dncore.extensions.craftswitcher.fileback.snapshot import async_scan_files, compare_files_diff
from dncore.extensions.craftswitcher.files import BackupType
from dncore.extensions.craftswitcher.publicapi import APIErrorCode, model
from dncore.extensions.craftswitcher.publicapi.server import StreamingResponse
from .common import *

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess
    from dncore.extensions.craftswitcher.files.archive import ArchiveFile

api = APIRouter(
    tags=["Backup", ],
    dependencies=[Depends(get_authorized_user), ],
)


async def get_backup_files(backup_id: UUID, check_files: bool) -> "FilesResult":
    err_files: dict[str, tuple[BackupFileErrorType, SnapshotErrorFile | None]]

    if not (backup := await db.get_backup_or_snapshot(backup_id)):
        raise APIErrorCode.BACKUP_NOT_FOUND.of(f"Backup not found: {backup_id}")

    if BackupType.SNAPSHOT == backup.type:
        s_files = await backups.get_snapshot_file_info(backup_id) or {}
        err_files = {e.path: (e.error_type, e) for e in await db.get_snapshot_errors_files(backup_id) or []}
        total_files_size = backup.total_files_size
        final_size = None

        if check_files:
            _size = [0]  # no link size

            def check(p: Path):
                try:
                    f_stat = p.stat()
                    if f_stat.st_nlink == 1:
                        _size[0] += f_stat.st_size
                except OSError:
                    pass
                return True

            _files, _errors = await async_scan_files(backups.backups_dir / backup.path, check=check)
            err_files.update({p: (BackupFileErrorType.SCAN, None) for p in _errors})
            err_files.update({p: (BackupFileErrorType.EXISTS_CHECK, None) for p in s_files if p not in _files})

            for p in err_files:
                s_files.pop(p, None)

            total_files_size = sum(fi.size for fi in _files.values())
            final_size = _size[0]

    elif BackupType.FULL == backup.type:
        _backup_file = backups.backups_dir / backup.path
        if not _backup_file.is_file():
            raise APIErrorCode.INVALID_BACKUP.of("Backup file not exists")

        final_size = _backup_file.stat().st_size
        try:
            _files = await files.list_archive(backups.backups_dir / backup.path)
        except NoArchiveHelperError:
            raise
        try:
            _, _files = backups.find_server_directory_archive(_files)
        except ValueError as e:
            raise APIErrorCode.INVALID_BACKUP.of(str(e))

        s_files = {f.filename: FileInfo(f.size, f.modified_datetime, f.is_dir) for f in _files}
        total_files_size = sum(fi.size for fi in _files)
        err_files = {}

    else:
        raise NotImplementedError(f"Unknown backup type: {backup.type}")

    return FilesResult(s_files, total_files_size, convert_to_error_files_model(err_files), final_size)


def convert_to_error_files_model(error_files: dict[str, tuple[BackupFileErrorType, SnapshotErrorFile | None]]):
    return [model.BackupFilePathErrorInfo(
        path=p,
        error_type=e_type,
        error_message=e.error_message if e else None,
    ) for p, (e_type, e) in error_files.items()]


def create_backups_compare_result(
    old_backup: "FilesResult", new_backup: "FilesResult", *,
    include_files: bool, include_errors: bool, only_updates: bool,
):
    files_diff = compare_files_diff(old_backup.files, new_backup.files)
    update_files_diff = [diff for diff in files_diff if 0 < diff.status.value]  # not DELETE or not NO_CHANGE

    return model.BackupsCompareResult(
        total_files=len(old_backup.files),
        total_files_size=old_backup.total_files_size,
        error_files=len(old_backup.error_files),
        backup_files_size=old_backup.backup_files_size,
        update_files=len(update_files_diff),
        update_files_size=sum(diff.new_info.size for diff in update_files_diff),
        target_total_files=len(new_backup.files),
        target_total_files_size=new_backup.total_files_size,
        target_error_files=len(new_backup.error_files),
        target_backup_files_size=new_backup.backup_files_size,
        files=[
            model.BackupFileDifference.create(diff) for diff in files_diff
            if not only_updates or diff in update_files_diff
        ] if include_files else None,
        errors=old_backup.error_files if include_errors else None,
        target_errors=new_backup.error_files if include_errors else None,
    )


def create_backup_preview_result(
    old_files: dict[str, FileInfo] | None, new_result: "FilesResult", snapshot_source: UUID, *,
    include_files: bool, include_errors: bool, only_updates: bool,
):
    files_diff = compare_files_diff(old_files, new_result.files)
    update_files_diff = [diff for diff in files_diff if 0 < diff.status.value]  # not DELETE or not NO_CHANGE

    return model.BackupPreviewResult(
        total_files=len(new_result.files),
        total_files_size=new_result.total_files_size,
        error_files=len(new_result.error_files),
        backup_files_size=new_result.backup_files_size,
        update_files=len(update_files_diff),
        update_files_size=sum(diff.new_info.size for diff in update_files_diff),
        files=[
            model.BackupFileDifference.create(diff) for diff in files_diff
            if not only_updates or diff in update_files_diff
        ] if include_files else None,
        errors=new_result.error_files if include_errors else None,
        snapshot_source=snapshot_source,
    )


async def get_server_files(server_dir: Path):
    _size = [0]

    def check(p: Path):
        try:
            _size[0] += p.stat().st_size
        except OSError:
            pass
        return True

    scan_files, scan_errors = await async_scan_files(server_dir, check=check)
    return FilesResult(
        files=scan_files,
        total_files_size=_size[0],
        error_files=[model.BackupFilePathErrorInfo(
                path=p,
                error_type=BackupFileErrorType.SCAN,
                error_message=str(e),
            ) for p, e in scan_errors.items()],
        backup_files_size=None,
    )


class FilesResult(NamedTuple):
    files: dict[str, FileInfo]
    total_files_size: int
    error_files: list[model.BackupFilePathErrorInfo]
    backup_files_size: int | None


@api.get(
    "/backups",
    summary="バックアップID一覧",
)
async def _get_backups() -> list[model.BackupId]:
    _servers = {
        s.get_source_id(generate=False): s_id
        for s_id, s in servers.items() if s
    }
    return [
        model.BackupId(id=backup_id, source=source_id, server=_servers.get(source_id.hex))
        for backup_id, source_id in await db.get_backup_ids()
    ]


@api.get(
    "/backup/{backup_id}",
    summary="バックアップの情報",
)
async def _get_backup(backup_id: UUID) -> model.Backup:
    backup = await db.get_backup_or_snapshot(backup_id)
    if not backup:
        raise APIErrorCode.BACKUP_NOT_FOUND.of("Backup not found")

    return model.Backup.create(backup)


@api.delete(
    "/backup/{backup_id}",
    summary="バックアップの削除",
    description="バックアップをファイルとデータベースから削除します。ファイルエラーは無視されます。",
)
async def _delete_backup(backup_id: UUID) -> bool:
    try:
        await backups.delete_backup(None, backup_id)
    except ValueError as e:
        raise APIErrorCode.BACKUP_NOT_FOUND.of(str(e))
    return True


@api.get(
    "/backup/{backup_id}/files",
    summary="ファイル一覧",
    description=(
            "バックアップされたファイルを一覧します"
    ),
)
async def _files_backup(
    backup_id: UUID,
    check_files: bool = Query(False, description="常に実際のファイルをチェックします"),
    include_files: bool = Query(False, description="バックアップ対象のファイル情報を返す"),
    include_errors: bool = Query(False, description="エラーファイルを返す"),
) -> model.BackupFilesResult:
    r = await get_backup_files(backup_id, check_files)
    return model.BackupFilesResult(
        total_files=len(r.files),
        total_files_size=r.total_files_size,
        error_files=len(r.error_files),
        backup_files_size=r.backup_files_size,
        files=[model.BackupFilePathInfo.create(p, i)
               for p, i in r.files.items()] if include_files else None,
        errors=r.error_files if include_errors else None,
    )


@api.get(
    "/backup/{backup_id}/files/compare",
    summary="バックアップファイルの比較",
    description=(
            "`backup_id` に含まれないファイルを新規ファイルとしてマークします"
    ),
)
async def _files_compare_backups(
    backup_id: UUID, target_backup_id: UUID,
    check_files: bool = Query(False, description="常に実際のファイルをチェックします"),
    include_files: bool = Query(False, description="バックアップ対象のファイル情報を返す"),
    include_errors: bool = Query(False, description="エラーファイルを返す"),
    only_updates: bool = Query(True, description="異なるファイルのみ `files` に含める"),
) -> model.BackupsCompareResult:
    source_backup = await get_backup_files(backup_id, check_files)
    target_backup = await get_backup_files(target_backup_id, check_files)
    return create_backups_compare_result(
        source_backup, target_backup,
        include_files=include_files, include_errors=include_errors, only_updates=only_updates,
    )


@api.get(
    "/server/{server_id}/backups",
    summary="バックアップ一覧",
)
async def _get_server_backups(server: "ServerProcess" = Depends(getserver)) -> list[model.Backup]:
    return [
        model.Backup.create(b)
        for b in await db.get_backups_or_snapshots(UUID(server.get_source_id()))
    ]


@api.get(
    "/server/{server_id}/backup",
    summary="実行中のバックアップタスクを取得",
)
def _get_server_backup_running(server: "ServerProcess" = Depends(getserver)) -> model.BackupTask | None:
    task = backups.get_running_task_by_server(server)
    return task and model.BackupTask.create(task) or None


@api.post(
    "/server/{server_id}/backup",
    summary="バックアップを開始",
    description="サーバーのバックアップを開始します。他のバックアップタスクと同時実行できません。"
)
async def _post_server_backup(
    server: "ServerProcess" = Depends(getserver),
    comments: str | None = None,
    snapshot: bool = False,
) -> model.BackupTask:
    if backups.get_running_task_by_server(server):
        raise APIErrorCode.BACKUP_ALREADY_RUNNING.of("Already running")

    if snapshot:
        task = await backups.create_snapshot(server, comments)
    else:
        task = await backups.create_full_backup(server, comments)
    return model.BackupTask.create(task)


@api.get(
    "/server/{server_id}/backup/preview",
    summary="バックアップのプレビュー",
    description="`snapshot` が true の場合は、リンク可能な最終スナップショットをチェック/比較します。",
)
async def _preview_server_backup(
    server: "ServerProcess" = Depends(getserver),
    snapshot: bool = False,
    check_files: bool = Query(False, description="常に実際のファイルをチェックします"),
    include_files: bool = Query(False, description="バックアップ対象のファイル情報を返す"),
    include_errors: bool = Query(False, description="エラーファイルを返す"),
    only_updates: bool = Query(True, description="異なるファイルのみ `files` に含める"),
) -> model.BackupPreviewResult:
    source_id = server.get_source_id()
    old_result = last_snapshot = None

    if b_id := server.config.last_backup_id:
        if snapshot:
            if last_snapshot := await db.get_last_snapshot(UUID(source_id), UUID(b_id)):
                old_result = await get_backup_files(last_snapshot.id, check_files)

    result = await get_server_files(server.directory)
    return create_backup_preview_result(
        old_result and old_result.files, result, last_snapshot and last_snapshot.id or None,
        include_files=include_files, include_errors=include_errors, only_updates=only_updates,
    )


@api.post(
    "/server/{server_id}/backup/{backup_id}/restore",
    summary="バックアップリストア",
    description=(
            "バックアップされたデータを展開して復元します。(サーバーディレクトリにある既存のデータが全て削除されます)\n\n"
            "実行前にバックアップ検証を実行し、変更をプレビューすることを推奨します。\n\n"
            "他のバックアップタスクと同時実行できません。"
    ),
)
async def _restore_server_backup(
    backup_id: UUID, server: "ServerProcess" = Depends(getserver),
) -> model.BackupTask:
    try:
        task = await backups.restore_backup(server, backup_id)
    except ValueError as e:
        raise APIErrorCode.BACKUP_NOT_FOUND.of(str(e))
    except NotImplementedError:
        raise

    return model.BackupTask.create(task)


@api.get(
    "/server/{server_id}/backup/{backup_id}/verify",
    summary="バックアップの検証",
    description=(
            "バックアップデータとサーバーデータのファイルを比較します\n\n"
            "`backup_id` に含まれないファイルを新規ファイルとしてマークします\n"
            "`/server/{server_id}/backup/{backup_id}/files/compare?check_files=true` のエイリアスです。将来的に変更されるかもしれません。"
    )
)
async def _verify_server_backup(
    backup_id: UUID, server: "ServerProcess" = Depends(getserver),
    include_files: bool = Query(False, description="バックアップ対象のファイル情報を返す"),
    include_errors: bool = Query(False, description="エラーファイルを返す"),
    only_updates: bool = Query(True, description="異なるファイルのみ `files` に含める"),
) -> model.BackupsCompareResult:
    return await _files_compare_server_backups(
        backup_id, server, True, include_files, include_errors, only_updates,
    )


@api.get(
    "/server/{server_id}/backup/{backup_id}/files/compare",
    summary="バックアップファイルの比較",
    description=(
            "バックアップとサーバーデータのファイルを比較します\n\n"
            "`backup_id` に含まれないファイルを新規ファイルとしてマークします"
    ),
)
async def _files_compare_server_backups(
    backup_id: UUID, server: "ServerProcess" = Depends(getserver),
    check_files: bool = Query(False, description="常に実際のファイルをチェックします"),
    include_files: bool = Query(False, description="バックアップ対象のファイル情報を返す"),
    include_errors: bool = Query(False, description="エラーファイルを返す"),
    only_updates: bool = Query(True, description="異なるファイルのみ `files` に含める"),
) -> model.BackupsCompareResult:
    if not server.directory.is_dir():
        raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Not a directory or not exists")
    source_backup = await get_backup_files(backup_id, check_files)
    target_data = await get_server_files(server.directory)
    return create_backups_compare_result(
        source_backup, target_data,
        include_files=include_files, include_errors=include_errors, only_updates=only_updates,
    )


@api.get(
    "/server/{server_id}/backup/{backup_id}/file",
    summary="ファイルデータの取得",
    description="バックアップに格納されたファイルを返します",
)
async def _get_server_backup_file(backup_id: UUID, path: str, server: "ServerProcess" = Depends(getserver)):
    try:
        path = files.resolvepath(path)
    except ValueError as e:
        raise APIErrorCode.NOT_ALLOWED_PATH.of(f"{e}: {path}")
    path = path[path.startswith("/"):]

    if not (backup := await db.get_backup_or_snapshot(backup_id)):
        raise APIErrorCode.BACKUP_NOT_FOUND.of(f"Backup not found: {backup_id}")

    backup_path = backups.backups_dir / backup.path  # type: Path

    if BackupType.SNAPSHOT == backup.type:
        target_path = backup_path / path
        if not target_path.is_file():
            raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: 'path'", 404)
        return FileResponse(target_path, filename=target_path.name)

    elif BackupType.FULL == backup.type:
        if not backup_path.is_file():
            raise APIErrorCode.INVALID_BACKUP.of("Backup file not exists")

        try:
            _files = await files.list_archive(backup_path)
        except NoArchiveHelperError:
            raise
        try:
            dir_name, _files = backups.find_server_directory_archive(_files)
        except ValueError as e:
            raise APIErrorCode.INVALID_BACKUP.of(str(e))

        helper = files.find_archive_helper(backup_path)
        if not helper:
            raise NoArchiveHelperError

        target_file = None  # type: ArchiveFile | None
        for child in _files:
            if child.filename == path:
                target_file = child
                break
        else:
            raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: 'path'", 404)

        async def _processing():
            _target_filename = dir_name + "/" + target_file.filename
            try:
                # noinspection PyTypeChecker
                async for chunk in helper.extract_archived_file(backup_path, _target_filename):
                    yield chunk

            except FileNotFoundError:
                raise APIErrorCode.NOT_EXISTS_FILE.of("File not found in archive")

        return StreamingResponse(_processing(), Path(target_file.filename).name)

    else:
        raise NotImplementedError(f"Unknown backup type: {backup.type}")


@api.get(
    "/server/{server_id}/backup/file/history",
    summary="ファイルデータの履歴一覧",
    description=(
            "指定されたファイルがバックアップのリストを作成順で返します\n\n"
            "変更がないとマークされているバックアップはリストから除外されます (スナップショットのみ)\n\n"
            "※ 現在はスナップショットのみサポートしています"
    ),
)
async def _get_server_backup_file_history(
    path: str, server: "ServerProcess" = Depends(getserver),
) -> list[model.BackupFileHistoryEntry]:
    try:
        path = files.resolvepath(path)
    except ValueError as e:
        raise APIErrorCode.NOT_ALLOWED_PATH.of(f"{e}: {path}")
    path = path[path.startswith("/"):]

    source = server.get_source_id()
    _files, _backups = await db.get_backups_files(UUID(source), path)

    return [model.BackupFileHistoryEntry(
        backup=model.Backup.create(backup),
        info=model.BackupFileInfo(
            size=file.size,
            modify_time=file.modified,
            is_dir=file.type.value == 1,
        ) if SnapshotStatus.DELETE != file.status else None,
        status=file.status,
    ) for file, backup in zip(_files, _backups) if SnapshotStatus.NO_CHANGE != file.status]

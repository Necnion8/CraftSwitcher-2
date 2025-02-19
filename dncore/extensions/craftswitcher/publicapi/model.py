import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from dncore.extensions.craftswitcher import abc
from dncore.extensions.craftswitcher.fileback import abc as fbabc
from dncore.extensions.craftswitcher.files import abc as fabc
from dncore.extensions.craftswitcher.files.abc import BackupType
from dncore.extensions.craftswitcher.files.archive import abc as aabc
from dncore.extensions.craftswitcher.jardl import ServerBuildStatus

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess
    from dncore.extensions.craftswitcher.ext import ExtensionInfo, EditableFile
    from dncore.extensions.craftswitcher.database import model as db


class SwitcherConfig(BaseModel):
    servers_location: str | None = Field(None, description="サーバーの保管に使うパス")
    max_console_lines_in_memory: int = Field(10_000, description="コンソールログをメモリに保持する行数 (サーバーごと)")


class ServerStatusInfo(BaseModel):
    class Process(BaseModel):
        cpu_usage: float = Field(description="CPU使用率 (%)")
        mem_used: int = Field(description="メモリ使用量 (bytes)")
        mem_virtual_used: int = Field(description="メモリ使用量 (仮想メモリを含む) (bytes)")

    class JVM(BaseModel):
        cpu_usage: float | None = Field(description="CPU使用率 (%)")
        mem_used: int | None = Field(description="メモリ使用量 (bytes)")
        mem_total: int | None = Field(description="メモリ合計 (bytes)")

    class Game(BaseModel):
        class Player(BaseModel):
            uuid: str
            name: str

        ticks: float | None = Field(description="1秒あたりのゲームティック数")
        max_players: int | None = Field(description="最大プレイヤー数")
        online_players: int | None = Field(description="ログインしているプレイヤー数 (今のところ .players と同じ数です)")
        players: list[Player] | None = Field(description="ログインしているプレイヤー")

    id: str = Field(description="サーバーID")
    process: Process | None = Field(description="Switcherがプロセスを見失っている時に null")
    jvm: JVM | None = Field(description="連携が無効かアクティブでない時に null")
    game: Game | None = Field(description="連携が無効かアクティブでない、または非対応サーバーの時に null")


class Server(BaseModel):
    id: str = Field(description="サーバーID 小文字のみ")
    name: str | None = Field(description="表示名")
    type: abc.ServerType = Field(description="サーバータイプ")
    state: abc.ServerState = Field(description="状態")
    directory: str | None = Field(description="サーバーがある場所のパス。rootDirに属さないサーバーは null")
    is_loaded: bool = Field(description="サーバー設定がロードされているか")
    build_status: ServerBuildStatus | None = Field(description="ビルドステータス")
    status: ServerStatusInfo | None = Field(description="サーバーとプロセスの情報")

    @classmethod
    def create(cls, server: "ServerProcess", directory: str | None, include_status: bool):
        return cls(
            id=server.id,
            name=server.config.name,
            type=server.config.type,
            state=server.state,
            directory=directory,
            is_loaded=True,
            build_status=server.build_status,
            status=server.get_status_info() if include_status else None,
        )

    @classmethod
    def create_no_data(cls, server_id: str, directory: str):
        return cls(
            id=server_id,
            name=None,
            type=abc.ServerType.UNKNOWN,
            state=abc.ServerState.UNKNOWN,
            directory=directory,
            is_loaded=False,
            build_status=None,
            status=None,
        )


class ServerOperationResult(BaseModel):
    result: bool
    server_id: str

    @classmethod
    def success(cls, server: "str | ServerProcess"):
        return cls(result=True, server_id=server if isinstance(server, str) else server.id)

    @classmethod
    def failed(cls, server: "str | ServerProcess"):
        return cls(result=False, server_id=server if isinstance(server, str) else server.id)


class CreateServerParam(BaseModel):
    class LaunchOption(BaseModel):
        java_preset: str | None
        java_executable: str | None
        java_options: str | None
        jar_file: str
        server_options: str | None
        max_heap_memory: int | None
        min_heap_memory: int | None
        enable_free_memory_check: bool | None
        enable_reporter_agent: bool | None
        enable_screen: bool | None

    name: str | None
    directory: str
    type: abc.ServerType
    launch_option: LaunchOption
    enable_launch_command: bool = False
    launch_command: str = ""
    stop_command: str | None
    shutdown_timeout: int | None


class AddServerParam(BaseModel):
    directory: str


class ServerConfig(BaseModel):
    name: str | None = Field(None, description="表示名")
    type: abc.ServerType = Field(None, description="サーバーの種類")
    launch_option__java_preset: str | None = Field(None, description="Javaプリセット名")
    launch_option__java_executable: str | None = Field(None, description="Javaコマンド、もしくはパス")
    launch_option__java_options: str | None = Field(None, description="Java オプション")
    launch_option__jar_file: str = Field(None, description="Jarファイルパス")
    launch_option__server_options: str | None = Field(None, description="サーバーオプション")
    launch_option__max_heap_memory: int | None = Field(None, description="メモリ割り当て量 (単位: MB)")
    launch_option__min_heap_memory: int | None = Field(None, description="メモリ割り当て量 (単位: MB)")
    launch_option__enable_free_memory_check: bool | None = Field(None, description="起動時に空きメモリを確認する")
    launch_option__enable_reporter_agent: bool | None = Field(None, description="サーバーと連携するエージェントを使う")
    launch_option__enable_screen: bool | None = Field(None, description="GNU Screen を使って起動する")
    enable_launch_command: bool | None = Field(None, description="起動オプションを使わず、カスタムコマンドで起動する")
    launch_command: str = Field(None, description="置換される変数: "
                                                  "$JAVA_EXE, $JAVA_MEM_ARGS, $JAVA_ARGS, $JAVA_ARGS, "
                                                  "$SERVER_ID, $SERVER_JAR, $SERVER_ARGS")
    stop_command: str | None = Field(None, description="停止コマンド")
    shutdown_timeout: int | None = Field(None, description="停止処理の最大待ち時間 (単位: 秒)")
    created_at: datetime.datetime | None = Field(None, description="作成された日付")
    last_launch_at: datetime.datetime | None = Field(None, description="最後に起動した日付")
    last_backup_at: datetime.datetime | None = Field(None, description="最後にバックアップした日付")
    last_backup_id: str | None = Field(None, description="最終バックアップのID")
    source_id: str | None = Field(None, description="サーバーデータID")
    installer__type: abc.ServerType | None = Field(None, description="インストールされたサーバーの種類")
    installer__version: str | None = Field(None, description="インストールされたサーバーバージョン")
    installer__build: str | None = Field(None, description="インストールされたサーバービルド")
    installer__require_build: bool | None = Field(None, description="ビルドが必要なインストーラー")

    class Config:
        @staticmethod
        def alias_generator(key: str):
            return key.replace("__", ".")


class ServerGlobalConfig(BaseModel):
    launch_option__java_preset: str = Field("default", description="Javaプリセット名")
    launch_option__java_executable: str | None = Field(None, description="Javaコマンド、もしくはパス")
    launch_option__java_options: str = Field("-Dfile.encoding=UTF-8", description="Java オプション")
    launch_option__server_options: str = Field("nogui", description="サーバーオプション")
    launch_option__max_heap_memory: int = Field(2048, description="メモリ割り当て量 (単位: MB)")
    launch_option__min_heap_memory: int = Field(2048, description="メモリ割り当て量 (単位: MB)")
    launch_option__enable_free_memory_check: bool = Field(True, description="起動時に空きメモリを確認する")
    launch_option__enable_reporter_agent: bool = Field(True, description="サーバーと連携するエージェントを使う")
    launch_option__enable_screen: bool = Field(False, description="GNU Screen を使って起動する")
    shutdown_timeout: int = Field(30, description="停止処理の最大待ち時間 (単位: 秒)")

    class Config:
        @staticmethod
        def alias_generator(key: str):
            return key.replace("__", ".")


class FileInfo(BaseModel):
    name: str = Field(description="拡張子を含むファイル名")
    path: str = Field(description="ディレクトリパス")
    is_dir: bool = Field(description="ディレクトリ？")
    size: int = Field(description="ファイルサイズ。ディレクトリなら -1")
    modify_time: int = Field(description="変更日時")
    create_time: int = Field(description="作成日時")
    is_server_dir: bool = Field(description="サーバーディレクトリ？")
    registered_server_id: str | None = Field(description="登録されているサーバーID")


class FileDirectoryInfo(BaseModel):
    name: str = Field(description="ディレクトリ名")
    path: str = Field(description="ディレクトリパス")
    children: list[FileInfo] = Field(description="含まれるファイル")


class FileOperationResult(BaseModel):
    result: fabc.FileTaskResult
    task_id: int | None
    file: FileInfo | None

    @classmethod
    def success(cls, task_id: int | None, file: FileInfo | None):
        return cls(result=fabc.FileTaskResult.SUCCESS, task_id=task_id, file=file)

    @classmethod
    def pending(cls, task_id: int | None, file: FileInfo = None):
        return cls(result=fabc.FileTaskResult.PENDING, task_id=task_id, file=file)

    @classmethod
    def failed(cls, task_id: int | None, file: FileInfo = None):
        return cls(result=fabc.FileTaskResult.FAILED, task_id=task_id, file=file)


class FileTask(BaseModel):
    id: int = Field(description="タスクID")
    type: fabc.FileEventType = Field(description="タスクタイプ")
    progress: float | None = Field(description="進行度。対応しない場合は null を返す。")
    result: fabc.FileTaskResult = Field(description="タスクの結果")
    src: str | None = Field(description="元ファイルのパス")
    dst: str | None = Field(description="送り先または処理後のファイルパス")
    server: str | None = Field(description="対象のサーバー。値がある場合、xxx_path はサーバーディレクトリからの相対パス。")

    @classmethod
    def create(cls, task: "fabc.FileTask | fabc.BackupTask"):
        if isinstance(task, fabc.BackupTask):
            return BackupTask.create(task)
        return cls(
            id=task.id,
            type=task.type,
            progress=task.progress,
            result=task.result,
            src=task.src_swi_path,
            dst=task.dst_swi_path,
            server=task.server.id if task.server else None,
        )


class BackupTask(FileTask):
    comments: str | None = Field(description="バックアップメモ")
    backup_type: BackupType
    backup_id: UUID = Field(description="バックアップID")

    @classmethod
    def create(cls, task: "fabc.BackupTask"):
        return cls(
            id=task.id,
            type=task.type,
            progress=task.progress,
            result=task.result,
            src=task.src_swi_path,
            dst=task.dst_swi_path,
            server=task.server.id if task.server else None,
            comments=task.comments,
            backup_type=task.backup_type,
            backup_id=task.backup_id,
        )


class ArchiveFile(BaseModel):
    filename: str = Field(description="パスを含むファイル名")
    is_dir: bool = Field(description="フォルダなら true")
    size: int | None = Field(description="展開後のサイズ")
    compressed_size: int | None = Field(description="圧縮後のサイズ")
    modified_datetime: datetime.datetime | None = Field(description="更新日時")

    @classmethod
    def create(cls, archive_file: "aabc.ArchiveFile"):
        return cls(
            filename=archive_file.filename,
            is_dir=archive_file.is_dir,
            size=archive_file.size,
            compressed_size=archive_file.compressed_size,
            modified_datetime=archive_file.modified_datetime,
        )


class StorageInfo(BaseModel):
    total_size: int
    used_size: int
    free_size: int


class User(BaseModel):
    id: int
    name: str
    last_login: datetime.datetime | None
    last_address: str | None
    permission: int

    @classmethod
    def create(cls, user: "db.User"):
        return cls(
            id=user.id,
            name=user.name,
            last_login=user.last_login,
            last_address=user.last_address,
            permission=user.permission,
        )


class UserOperationResult(BaseModel):
    result: bool
    user_id: int

    @classmethod
    def success(cls, user_id: int):
        return cls(result=True, user_id=user_id)

    @classmethod
    def failed(cls, user_id: int):
        return cls(result=False, user_id=user_id)


class JarDLVersionInfo(BaseModel):
    version: str = Field(description="対応バージョン。通常は Minecraft バージョンです。")
    build_count: int | None


class JarDLBuildInfo(BaseModel):
    build: str
    download_url: str | None = Field(description="サーバーJarのダウンロードURL。一部はインストーラーURLとして利用されます。")
    java_major_version: int | None
    require_jdk: bool | None
    updated_datetime: datetime.datetime | None
    recommended: bool
    is_require_build: bool
    is_loaded_info: bool


class PluginEditableFile(BaseModel):
    key: str
    label: str | None = Field(description="表示名")


class PluginInfo(BaseModel):
    name: str
    version: str
    description: str | None = Field(description="説明文。複数行になることもある？")
    authors: list[str]
    #
    editable_files: list[PluginEditableFile]

    @classmethod
    def create(cls, info: "ExtensionInfo", editable_files: "list[EditableFile]"):
        return cls(
            name=info.name,
            version=info.version,
            description=info.description,
            authors=info.authors,
            editable_files=[
                PluginEditableFile(key=file.key, label=file.label)
                for file in editable_files
            ],
        )


class PluginMessageResponse(BaseModel):
    caption: str | None
    content: str = Field(description="メッセージ内容。複数行")
    errors: bool = Field(description="エラーメッセージか")


class JavaExecutableInfo(BaseModel):
    path: Path
    runtime_version: str
    java_home_path: str | None
    java_major_version: int
    specification_version: str | None = None
    class_version: int | None = None
    vendor: str | None = None
    vendor_version: str | None = None
    is_jdk: bool = False

    @classmethod
    def create(cls, info: abc.JavaExecutableInfo):
        return cls(
            path=info.path,
            runtime_version=info.runtime_version,
            java_home_path=info.java_home_path,
            java_major_version=info.java_major_version,
            specification_version=info.specification_version,
            class_version=info.class_version,
            vendor=info.vendor,
            vendor_version=info.vendor_version,
            is_jdk=info.is_jdk,
        )


class JavaPreset(BaseModel):
    name: str = Field(description="Javaプリセット名")
    executable: str = Field(description="実行可能ファイルまたはコマンド")
    info: JavaExecutableInfo | None = Field(description="Java 情報")
    available: bool = Field(False, description="利用可能")
    registered: bool = Field(False, description="登録されている")
    recommended: int | None = Field(None, description="リクエストによって推奨される度合い\n\n値が高ければより推奨され、0 または -1 は評価されないか推奨されません。")


class BackupId(BaseModel):
    id: UUID
    source: UUID
    server: str | None = Field(description="ソースIDに紐づくサーバー")


class Backup(BaseModel):
    id: UUID
    type: BackupType
    source: UUID
    created: datetime.datetime
    previous_backup: UUID | None
    path: str
    comments: str | None
    total_files: int
    total_files_size: int
    error_files: int
    final_size: int | None = Field(description="バックアップ後のサイズ。スナップショットでは null になります。")

    @classmethod
    def create(cls, backup: "db.Backup"):
        return cls(
            id=backup.id,
            type=backup.type,
            source=backup.source,
            created=backup.created,
            previous_backup=backup.previous_backup,
            path=backup.path,
            comments=backup.comments,
            total_files=backup.total_files,
            total_files_size=backup.total_files_size,
            error_files=backup.error_files,
            final_size=backup.final_size,
        )


class BackupFileInfo(BaseModel):
    size: int
    modify_time: datetime.datetime
    is_dir: bool

    @classmethod
    def create(cls, info: fbabc.FileInfo):
        return cls(
            size=info.size,
            modify_time=info.modified_datetime,
            is_dir=info.is_dir,
        )


class BackupFileDifference(BaseModel):
    path: str
    old_info: BackupFileInfo | None
    new_info: BackupFileInfo | None
    status: fbabc.SnapshotStatus

    @classmethod
    def create(cls, diff: fbabc.FileDifference):
        return cls(
            path=diff.path,
            old_info=BackupFileInfo.create(i) if (i := diff.old_info) else None,
            new_info=BackupFileInfo.create(i) if (i := diff.new_info) else None,
            status=diff.status,
        )


class BackupFilePathInfo(BaseModel):
    path: str
    is_dir: bool
    size: int
    modify_time: datetime.datetime

    @classmethod
    def create(cls, path: str, info: fbabc.FileInfo):
        return cls(
            size=info.size,
            modify_time=info.modified_datetime,
            is_dir=info.is_dir,
            path=path,
        )


class BackupFilePathErrorInfo(BaseModel):
    path: str
    error_type: fbabc.BackupFileErrorType
    error_message: str | None


class BackupFilesResult(BaseModel):
    total_files: int = Field(description="ファイル数")
    total_files_size: int = Field(description="ファイルの合計サイズ")
    error_files: int = Field(description="エラーファイル件数")
    backup_files_size: int | None = Field(description="バックアップのサイズ (節約済みのファイルを除く)")

    files: list[BackupFilePathInfo] | None
    errors: list[BackupFilePathErrorInfo] | None


class BackupsCompareResult(BackupFilesResult):
    update_files: int = Field(description="変更があるファイル数")
    update_files_size: int = Field(description="変更があるファイルの合計サイズ")

    target_total_files: int = Field(description="比較対象先のファイル数")
    target_total_files_size: int = Field(description="比較対象先のファイルの合計サイズ")
    target_error_files: int = Field(description="比較対象先のエラーファイル件数")
    target_backup_files_size: int | None = Field(description="比較対象先のバックアップのサイズ (節約済みのファイルを除く)")

    files: list[BackupFileDifference] | None
    errors: list[BackupFilePathErrorInfo] | None
    target_errors: list[BackupFilePathErrorInfo] | None


class BackupPreviewResult(BaseModel):
    total_files: int = Field(description="対象のファイル数")
    total_files_size: int = Field(description="対象のファイルの合計サイズ")
    error_files: int = Field(description="エラーファイル件数")
    update_files: int = Field(description="変更があるファイル数")
    update_files_size: int = Field(description="変更があるファイルの合計サイズ")
    backup_files_size: int | None = Field(description="バックアップのサイズ (節約済みのファイルを除く)")

    snapshot_source: UUID | None = Field(description="ソース元のスナップショットバックアップID")

    files: list[BackupFileDifference] | None
    errors: list[BackupFilePathErrorInfo] | None


class BackupFileHistoryEntry(BaseModel):
    backup: Backup
    info: BackupFileInfo | None
    status: fbabc.SnapshotStatus | None

import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dncore.extensions.craftswitcher import abc
from dncore.extensions.craftswitcher.files import abc as fabc
from dncore.extensions.craftswitcher.files.archive import abc as aabc

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess
    from dncore.extensions.craftswitcher.database import model as db


class Server(BaseModel):
    id: str = Field(description="サーバーID 小文字のみ")
    name: str | None = Field(description="表示名")
    type: abc.ServerType = Field(description="サーバータイプ")
    state: abc.ServerState = Field(description="状態")
    directory: str | None = Field(description="サーバーがある場所のパス。rootDirに属さないサーバーは null")
    is_loaded: bool = Field(description="サーバー設定がロードされているか")

    @classmethod
    def create(cls, server: "ServerProcess", directory: str | None):
        return cls(
            id=server.id,
            name=server.config.name,
            type=server.config.type,
            state=server.state,
            directory=directory,
            is_loaded=True,
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
        )


class ServerOperationResult(BaseModel):
    result: bool
    server_id: str

    @classmethod
    def success(cls, server: "str | ServerProcess"):
        return cls(result=True, server_id=server if isinstance(server, str) else server.id)


class CreateServerParam(BaseModel):
    class LaunchOption(BaseModel):
        java_executable: str | None
        java_options: str | None
        jar_file: str
        server_options: str | None
        max_heap_memory: int | None
        min_heap_memory: int | None
        enable_free_memory_check: bool | None
        enable_reporter_agent: bool | None

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
    launch_option__java_executable: str | None = Field(None, description="Javaコマンド、もしくはパス")
    launch_option__java_options: str | None = Field(None, description="Java オプション")
    launch_option__jar_file: str = Field(None, description="Jarファイルパス")
    launch_option__server_options: str | None = Field(None, description="サーバーオプション")
    launch_option__max_heap_memory: int | None = Field(None, description="メモリ割り当て量 (単位: MB)")
    launch_option__min_heap_memory: int | None = Field(None, description="メモリ割り当て量 (単位: MB)")
    launch_option__enable_free_memory_check: bool | None = Field(None, description="起動時に空きメモリを確認する")
    launch_option__enable_reporter_agent: bool | None = Field(None, description="サーバーと連携するエージェントを使う")
    enable_launch_command: bool | None = Field(None, description="起動オプションを使わず、カスタムコマンドで起動する")
    launch_command: str = None
    stop_command: str | None = Field(None, description="停止コマンド")
    shutdown_timeout: int | None = Field(None, description="停止処理の最大待ち時間 (単位: 秒)")
    created_at: datetime.datetime | None = Field(None, description="作成された日付")
    last_launch_at: datetime.datetime | None = Field(None, description="最後に起動した日付")
    last_backup_at: datetime.datetime | None = Field(None, description="最後にバックアップした日付")

    class Config:
        @staticmethod
        def alias_generator(key: str):
            return key.replace("__", ".")


class ServerGlobalConfig(BaseModel):
    launch_option__java_executable: str = Field("java", description="Javaコマンド、もしくはパス")
    launch_option__java_options: str = Field("-Dfile.encoding=UTF-8", description="Java オプション")
    launch_option__server_options: str = Field("--nogui", description="サーバーオプション")
    launch_option__max_heap_memory: int = Field(2048, description="メモリ割り当て量 (単位: MB)")
    launch_option__min_heap_memory: int = Field(2048, description="メモリ割り当て量 (単位: MB)")
    launch_option__enable_free_memory_check: bool = Field(True, description="起動時に空きメモリを確認する")
    launch_option__enable_reporter_agent: bool = Field(True, description="サーバーと連携するエージェントを使う")
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
    progress: float = Field(description="進行度。対応しない場合は常に 0.0 を返す。")
    result: fabc.FileTaskResult = Field(description="タスクの結果")
    src: str | None = Field(description="元ファイルのパス")
    dst: str | None = Field(description="送り先または処理後のファイルパス")
    server: str | None = Field(description="対象のサーバー。値がある場合、xxx_path はサーバーディレクトリからの相対パス。")

    @classmethod
    def create(cls, task: "fabc.FileTask"):
        return cls(
            id=task.id,
            type=task.type,
            progress=task.progress,
            result=task.result,
            src=task.src_swi_path,
            dst=task.dst_swi_path,
            server=task.server.id if task.server else None,
        )


class ArchiveFile(BaseModel):
    filename: str = Field(description="パスを含むファイル名")
    size: int | None = Field(description="展開後のサイズ")
    compressed_size: int | None = Field(description="圧縮後のサイズ")

    @classmethod
    def create(cls, archive_file: "aabc.ArchiveFile"):
        return cls(
            filename=archive_file.filename,
            size=archive_file.size,
            compressed_size=archive_file.compressed_size,
        )


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
    updated_datetime: datetime.datetime | None
    recommended: bool
    is_require_build: bool
    is_loaded_info: bool

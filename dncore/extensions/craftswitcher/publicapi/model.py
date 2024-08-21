import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dncore.extensions.craftswitcher import abc

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess


class Server(BaseModel):
    id: str = Field(description="サーバーID 小文字のみ")
    name: str | None = Field(description="表示名")
    type: abc.ServerType = Field(description="サーバータイプ")
    state: abc.ServerState = Field(description="状態")
    directory: str = Field(description="場所")
    is_loaded: bool = Field(description="サーバー設定がロードされているか")

    @classmethod
    def create(cls, server: "ServerProcess"):
        return cls(
            id=server.id,
            name=server.config.name,
            type=server.config.type,
            state=server.state,
            directory=str(server.directory),
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

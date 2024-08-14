import datetime

from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues
from dncore.extensions.craftswitcher.abc import ServerType


class LaunchOption(ConfigValues):
    # Javaコマンド、もしくはパス
    java_executable: str | None
    # Java オプション
    java_options: str | None
    # Jarファイルパス
    jar_file: str
    # サーバーオプション
    server_options: str | None
    # メモリ割り当て量 (単位: MB)
    max_heap_memory: int | None
    min_heap_memory: int | None
    # 起動時に空きメモリを確認する
    enable_free_memory_check: bool | None
    # サーバーと連携するエージェントを使う
    enable_reporter_agent: bool | None


class ServerConfig(FileConfigValues):
    # 表示名
    name: str | None

    # サーバーの種類
    type: ServerType = ServerType.UNKNOWN

    # # 作業ディレクトリ
    # directory: str
    # 起動オプション
    launch_option: LaunchOption
    # 起動オプションを使わず、カスタムコマンドで起動する
    enable_launch_command = False
    launch_command = ""

    # 停止コマンド
    # ※ null の場合は、サーバータイプに基づくコマンドを使用。もしくは 'stop' を実行します。
    stop_command: str | None
    # 停止処理の最大待ち時間 (単位: 秒)
    shutdown_timeout: int | None

    # 作成された日付
    created_at: datetime.datetime | None
    # 最後に起動した日付
    last_launch_at: datetime.datetime | None
    # 最後にバックアップした日付
    last_backup_at: datetime.datetime | None


class LaunchGlobalOption(ConfigValues):
    # Javaコマンド、もしくはパス
    java_executable = "java"
    # Java オプション
    java_options = "-Dfile.encoding=UTF-8"
    # サーバーオプション
    server_options = "--nogui"
    # メモリ割り当て量 (単位: MB)
    max_heap_memory = 2048
    min_heap_memory = 2048
    # 起動時に空きメモリを確認する
    enable_free_memory_check = True
    # サーバーと連携するエージェントを使う
    enable_reporter_agent = True


class ServerGlobalConfig(ConfigValues):
    # 起動オプション
    launch_option: LaunchGlobalOption
    # 停止処理の最大待ち時間 (単位: 秒)
    shutdown_timeout = 30


class JavaExecutable(ConfigValues):
    name: str
    executable: str


class SwitcherConfig(FileConfigValues):
    # サーバーリスト (key: サーバーID、val: サーバー場所)
    servers: dict[str, str]

    # グローバル設定
    server_defaults: ServerGlobalConfig

    # Java リスト
    java_executables: list[JavaExecutable]

    # Javaを自動検出するディレクトリ
    java_auto_detect_locations: list[str] = [
        "/usr/lib/jvm",
        "C:\\Program Files\\Java",
    ]

    # コンソールログをメモリに保持する行数 (サーバーごと)
    max_console_lines_in_memory = 10_000


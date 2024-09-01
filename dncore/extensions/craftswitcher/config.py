import datetime

from dncore.abc.serializables import ActivitySetting
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


class PublicApiServer(ConfigValues):
    enable = True
    bind_host = "0.0.0.0"
    bind_port = 8080


class DiscordActivity(ConfigValues):
    # ステータスを参照するサーバー
    target_server = "ALL"

    # 指定されたサーバーが存在しない
    no_server: ActivitySetting | None = None
    no_server_priority = -1
    # サーバー状態: 停止している
    stopped: ActivitySetting | None = ActivitySetting("dnd", "💤 停止中")
    stopped_priority = 100
    # サーバー状態: 起動中
    starting: ActivitySetting | None = ActivitySetting("idle", "♻ 処理中")
    starting_priority = 150
    # サーバー状態: 停止中
    stopping: ActivitySetting | None = ActivitySetting("idle", "♻ 処理中")
    stopping_priority = 150
    # サーバー状態: 起動済み
    started: ActivitySetting | None = ActivitySetting("online", "🔹 サーバー運営中！")
    started_priority = 100
    # サーバー状態: 起動済みかつ、参加者がいる
    started_joined: ActivitySetting | None = ActivitySetting("online", "🔹 {players}人が参加中！")
    started_joined_priority = 150


class Discord(ConfigValues):
    # ボットのアクティビティステータス
    #   利用できる値は
    #     {players}  - 参加人数
    #     {servers}  - 選択サーバーの数
    #     {servers_online}  - 起動済みの選択サーバーの数
    #
    # xxx_priority の値について
    #   ボットに表示されるアクティビティの優先度を決定します (50=弱い通知, 100=標準, 150=注意, 200=警告)
    #   他プラグインのアクティビティと競合する場合に、より高い優先度に変更できます
    activities: DiscordActivity


class SwitcherConfig(FileConfigValues):
    # サーバーリスト (key: サーバーID、val: サーバー場所)
    servers: dict[str, str]

    # グローバル設定
    server_defaults: ServerGlobalConfig

    # ルートとして扱うシステム上のディレクトリパス
    root_directory = "./minecraft_servers"

    # サーバーの保管に使うパス (※ 通常は変更する必要はありません)
    servers_location: str = "/"

    # Java リスト
    java_executables: list[JavaExecutable]

    # Javaを自動検出するディレクトリ
    java_auto_detect_locations: list[str] = [
        "/usr/lib/jvm",
        "C:\\Program Files\\Java",
    ]

    # コンソールログをメモリに保持する行数 (サーバーごと)
    max_console_lines_in_memory = 10_000

    # APIサーバー
    api_server: PublicApiServer

    # Discordボットの設定
    discord: Discord

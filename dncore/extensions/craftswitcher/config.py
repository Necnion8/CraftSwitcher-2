import datetime
from typing import TYPE_CHECKING, Literal

from dncore.abc import ObjectSerializable, Cloneable
from dncore.abc.serializables import ActivitySetting
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues
from dncore.extensions.craftswitcher.abc import ServerType

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher.serverprocess import ServerProcess

SERVER_SELECT_TYPE = Literal["ALL", "PROXY", "NOT_PROXY", "SELECT", ]


class ServerSelector(ObjectSerializable, Cloneable):
    def __init__(self, type_: SERVER_SELECT_TYPE, ids: list[int] = None):
        self.type = type_
        self.ids = ids

    def is_target(self, server: "ServerProcess"):
        if self.type == "ALL":
            return True
        elif self.type == "PROXY":
            return server.config.type.spec.is_proxy
        elif self.type == "NOT_PROXY":
            return not server.config.type.spec.is_proxy
        elif not self.ids:
            return False
        return server.id in self.ids if isinstance(self.ids, list) else server.id == self.ids

    def serialize(self):
        if self.type in ("ALL", "PROXY", "NOT_PROXY", ):
            return self.type
        else:
            return self.ids or []

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, str):
            if value.upper() in ("ALL", "PROXY", "NOT_PROXY", ):
                # noinspection PyTypeChecker
                return cls(value.upper())
            return cls("SELECT")
        return cls("SELECT", list(value) or [])

    def clone(self):
        return ServerSelector(self.type, self.ids)


class LaunchOption(ConfigValues):
    # Javaプリセット名
    # ※ java_executable が指定されている場合はそちらが優先されます
    java_preset: str | None
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
    # GNU Screen を使って起動する
    enable_screen: bool | None


class ServerInstallerInfo(ConfigValues):
    type: ServerType | None = None
    version: str | None = None
    build: str | None = None
    require_build: bool | None = None


class ServerConfig(FileConfigValues):
    # 表示名
    name: str | None

    # サーバーの種類
    type: ServerType = ServerType.UNKNOWN

    # 起動オプション
    launch_option: LaunchOption
    # 起動オプションを使わず、カスタムコマンドで起動する
    # 置換される変数:
    #   $JAVA_EXE       --> java_executable で設定された値
    #   $JAVA_MEM_ARGS  --> min_heap_memory, max_heap_memory で設定された値 (eg. '-Xms2048M -Xmx2048M')
    #   $JAVA_ARGS      --> java_options で設定された値
    #   $SERVER_ID      --> eg. 'lobby'
    #   $SERVER_JAR     --> jar_file で設定された値
    #   $SERVER_ARGS    --> server_options で設定された値
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

    # 使用したサーバーインストーラー
    installer: ServerInstallerInfo

    # ファイル識別用
    source_id: str | None
    last_backup_id: str | None


class LaunchGlobalOption(ConfigValues):
    # Javaプリセット名
    # ※ java_executable が指定されている場合はそちらが優先されます
    java_preset = "default"
    # Javaコマンド、もしくはパス
    java_executable: str | None = None
    # Java オプション
    java_options = "-Dfile.encoding=UTF-8"
    # サーバーオプション
    server_options = "nogui"
    # メモリ割り当て量 (単位: MB)
    max_heap_memory = 2048
    min_heap_memory = 2048
    # 起動時に空きメモリを確認する
    enable_free_memory_check = True
    # サーバーと連携するエージェントを使う
    enable_reporter_agent = True
    # GNU Screen を使って起動する
    enable_screen = False


class ServerGlobalConfig(ConfigValues):
    # 起動オプション
    launch_option: LaunchGlobalOption
    # 停止処理の最大待ち時間 (単位: 秒)
    shutdown_timeout = 30


class ReportModule(ConfigValues):
    # Java Agent ファイルのパス
    agent_file = "./CraftSwitcherReportModule-1.1.3_libs.jar"


class JavaPresetConfig(ConfigValues):
    name: str
    executable: str


class JavaConfigSection(ConfigValues):
    # 実行可能なJavaのパスリスト。システムパスで指定してください。
    presets: list[JavaPresetConfig]

    # Javaを自動検出するディレクトリ。システムパスで指定してください。
    auto_detection_paths: list[str] = [
        "/usr/lib/jvm",
        "C:\\Program Files\\Java",
    ]


class Screen(ConfigValues):
    # セッション名の接頭辞
    # ※ 他のセッション名と被らないようにする必要があります
    session_name_prefix = "swi-"

    # CraftSwitcherが停止する時にサーバーを停止させません
    enable_keep_server_on_shutdown = True


class PublicApiServer(ConfigValues):
    enable = True
    bind_host = "0.0.0.0"
    bind_port = 8080
    # SSLキーファイルのパス
    ssl_keyfile: str | None = None
    ssl_certfile: str | None = None


class DiscordActivity(ConfigValues):
    # ステータスを参照するサーバー
    target_server: ServerSelector = ServerSelector("ALL")

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


class Backup(ConfigValues):
    # スナップショット機能を使用するか
    enable_snapshots = True

    # フルバックアップとスナップショットのデータを格納します。システムパスで指定してください。
    # このディレクトリはサーバーディレクトリと別のドライブに配置することを推奨します。
    # ※ スナップショットを利用する場合、このディレクトリのファイルシステムでハードリンク機能が利用できる必要があります。
    backups_directory = "./data_backups"

    # バックアップに使用する圧縮ファイル拡張子
    # 使用できる拡張子を順に選択します
    suffixes: list[str] = ["7z", "zip"]


class SwitcherConfig(FileConfigValues):
    # サーバーリスト (key: サーバーID、val: サーバー場所)
    servers: dict[str, str]

    # グローバル設定
    server_defaults: ServerGlobalConfig

    # ルートとして扱うシステム上のディレクトリパス
    root_directory = "./minecraft_servers"

    # サーバーの保管に使うパス (※ 通常は変更する必要はありません)
    servers_location: str = "/"

    # サーバー連携モジュール設定
    repomo: ReportModule

    # Java 設定
    java: JavaConfigSection

    # GNU Screen 設定
    # ※ 利用できない場合は無視し、通常通りサーバーを直接起動させます。
    screen: Screen

    # コンソールログをメモリに保持する行数 (サーバーごと)
    max_console_lines_in_memory = 10_000

    # APIサーバー
    api_server: PublicApiServer

    # Discordボットの設定
    discord: Discord

    # サーバーバックアップ設定
    backup: Backup

from dncore.abc.serializables import Color, Reaction, Emoji, Embed, ActivitySetting
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues


class LoggingSection(ConfigValues):
    print_level = "info"
    file_level = "info"
    # モジュールのログレベル
    # dnCoreプラグインは dncore.extensions.(pluginId) で指定できます
    modules_level: dict[str, str]


class ActivitySection(ConfigValues):
    # 接続中のとき
    connecting: ActivitySetting | None = ActivitySetting("dnd", "接続待機中･･･")
    # 接続済みのとき
    ready: ActivitySetting | None = ActivitySetting("online", "{prefix}help")


class EmbedSection(ConfigValues):
    color_info = Color(0x5869EA)
    color_warn = Color(0xFF7800)
    color_error = Color(0xFF0000)


class CleanSection(ConfigValues):
    # 実行メッセージを自動的に削除するまでの時間 (秒)
    auto_clean_delay: int | None = 120
    # 実行メッセージを自動的に削除するまでの時間 (秒) (実行エラー時)
    auto_clean_delay_with_error: int | None = 30
    # 実行メッセージを自動的に削除するまでの時間 (秒) (不明なコマンド)
    auto_clean_delay_with_unknown_command: int | None = 30
    # 実行した送信者メッセージを自動削除する
    delete_request = True
    # コマンドメッセージを自動削除する
    delete_response = True


class DiscordSection(ConfigValues):
    # Discordボットトークン
    # ※ 接続しないで使用する場合は、debug.no_connect を true に設定してください
    token: str | None
    # APIに要求するインテント
    #   利用可能な値については以下のページを参照してください。
    #   カンマで区切って複数を指定できます。
    # https://discordpy.readthedocs.io/ja/latest/api.html#discord.Intents
    force_intents = "messages,message_content,guilds"
    # ボット所有者のユーザーID
    owner_id: int | None
    # コマンドプレフィックス
    command_prefix = "!"
    # ボットステータス
    activities: ActivitySection
    # Embedテンプレート
    embeds: EmbedSection
    # 実行メッセージの自動削除設定
    auto_clean: CleanSection
    # デバッグ用チャンネルID設定
    debug_channels: list[int]


class PluginSection(ConfigValues):
    # 起動時にロードしないプラグインの名前のリスト
    disabled_plugins: list[str]


class DebugSection(ConfigValues):
    # これが有効のとき、起動してもDiscordに接続しません
    no_connect = False
    # コマンド実行エラーが発生したら、ボットオーナーに通知する
    report_error_to_owners = True


class CleanCommandSection(ConfigValues):
    search_range_invalid = Embed(":grey_exclamation: 無効な値です。件数を数値で指定してください。")
    no_perm_read_history = Embed(":exclamation: メッセージ履歴を参照する権限がありません。")
    error = Embed(":exclamation: Discordエラー: {message}")
    deleted = Embed(":ok_hand: {count}件のメッセージを削除しました。")


class HelpCommandSection(ConfigValues):
    unknown_command = Embed(":grey_exclamation: コマンドが見つかりません。")
    no_usage = Embed(":grey_exclamation: コマンド使用法情報がありません。")
    no_commands = Embed(":grey_exclamation: 実行できるコマンドはありません･･･。")
    list = Embed(
        description="{lines}", title=":paperclip: コマンド一覧 :paperclip:").set_footer(
        text="»  dnCore v{version.numbers}",
        icon_url="https://i.imgur.com/18ampI3.png")
    line = ":white_small_square: **{category}**\n`{commands}`"
    split = "`, `"
    usage_format = Embed("{usage}")
    enable_usage_format = False


class DebugCommandSection(ConfigValues):
    specify_code = Embed(":grey_exclamation: デバッグコードを入力してください")


class ShutdownCommandSection(ConfigValues):
    shutdown = Embed(":zzz: ボットを停止します")
    restarting = Embed(":recycle: 再起動しています･･･")
    restarted = Embed(":+1: 再起動が完了しました！")
    task_pending = Embed(":warning: 以下のタスクが実行中です\n\n"
                         "{tasks}\n\n"
                         "続行するには **`Y`** を送信してください。")
    task_pending_format = "- {plugin} ･･･ {message}"
    task_pending_format_split = "\n"


class Messages(ConfigValues):
    command_empty_name = Reaction(Emoji(name="👀"))
    command_usage_error = Reaction(Embed(":grey_exclamation: 引数が正しくありません。`{prefix}help {execute_name}` を参照してください。"))
    command_unknown_error = Reaction(Embed(":grey_exclamation: 不明なコマンドです。`{prefix}help` で確認してみてください。"))
    command_permission_error = Reaction(Embed(":exclamation: 実行する権限がありません"))
    command_disallow_channel_error = Reaction(Embed(":exclamation: このチャンネルで実行することはできません"))
    command_interactive_running_error = Reaction(Emoji(name="🚫"))
    command_cancel_error = Reaction(Embed(":exclamation: 管理者によって中止されました"))
    command_internal_error = Reaction(Embed(":exclamation: 内部エラーが発生しました"))

    help: HelpCommandSection
    clean: CleanCommandSection
    debug: DebugCommandSection
    shutdown: ShutdownCommandSection


class AppConfig(FileConfigValues):
    logging: LoggingSection
    discord: DiscordSection
    plugin: PluginSection
    debug: DebugSection
    messages: Messages

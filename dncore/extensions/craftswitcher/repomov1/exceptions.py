

class ExceptionLocalized(Exception):
    def __init__(self, text: str = None, localized: str = None):
        self.message = text or getattr(self, "message", None)
        self.localized = localized or getattr(self, "localized", None)

    def __str__(self):
        return self.message or "none message"


class ServerProcessError(Exception):
    pass


class AlreadyRunningError(ServerProcessError, ExceptionLocalized):
    message = "Already running"
    localized = "既に実行しています"


class NotFoundJarFileError(ServerProcessError, ExceptionLocalized):
    message = "Jar file not found"
    localized = "Jarファイルが見つかりません"


class OutOfMemoryError(ServerProcessError, ExceptionLocalized):
    message = "Out of memory"
    localized = "空きメモリが不足しています"


class NotRunningError(ServerProcessError, ExceptionLocalized):
    message = "Not running"
    localized = "起動していません"


class InvalidSettingError(ServerProcessError, ExceptionLocalized):  # add: v1.1.0
    message = "Invalid setting"
    localized = "起動に必要な設定が無効です"


class ScriptCallError(ServerProcessError, ExceptionLocalized):
    message = "Failed to call start script"
    localized = "起動スクリプトの実行に失敗しました"


class ServerProcessingError(ServerProcessError, ExceptionLocalized):
    message = "Server process is in process"
    localized = "サーバーは処理中です"


def localize(exc: Exception):
    return (exc.localized or exc.message) if isinstance(exc, ExceptionLocalized) else str(exc)


class TCPClientError(Exception):
    pass


class ResponseError(TCPClientError):
    pass


class ClosedError(TCPClientError):
    pass

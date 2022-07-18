import asyncio
import traceback
from enum import Enum
from pathlib import Path

from dncore.configuration import ConfigValues
from dncore.configuration.configuration import ValueNotSet
from dncore.configuration.file import ConfigFileDriver, ParseError
from dncore.configuration.file.yaml import YamlFileDriver

__all__ = ["FileConfigValues", "CnfErr", "ConfigurationValueError"]


class CnfErr(Enum):
    NOT_SET = "not_set"
    """
    必須値が設定されてない場合に処理エラーを発生させる
    処理エラーを無視し、デフォルト値を代入する
    """

    IGNORE = "ignore"
    """
    全ての処理エラーを無視し、デフォルト値を代入する
    """

    RAISE = "raise"
    """処理エラーを直ちに発生させる"""


class ConfigurationValueError(ValueError):
    def __init__(self, stacks: list[ParseError], *args):
        self.stacks = stacks
        ValueError.__init__(self, *args)


class FileConfigValues(ConfigValues):
    def __init__(self, path: Path, *,
                 driver: type[ConfigFileDriver] = YamlFileDriver, errors=CnfErr.NOT_SET,
                 delay_save_minutes: int = None):
        CnfErr(errors)  # value check
        self.__driver = driver(path)
        self.__errors = errors
        self.__delay_save_minutes = max(delay_save_minutes, 0) if delay_save_minutes else None
        self.__delay_save_timer = None  # type: asyncio.Task | None
        ConfigValues.__init__(self)

    def get_driver(self):
        return self.__driver

    def load(self, save_defaults=True):
        if save_defaults and not self.__driver.path.is_file():
            self.save(force=True)

        self.cancel_save_timer(save=False)
        errors = self.__driver.load_to(self)
        if errors:
            self.on_deserialize_error(errors)

    def save(self, *, force=False):
        if force or not self.__delay_save_minutes:
            self.cancel_save_timer()
            errors = self.__driver.save_from(self)
            if errors:
                self.on_serialize_error(errors)
        else:
            if not self._schedule_save_timer():
                self.save(force=True)

    def cancel_save_timer(self, *, save=True):
        if self.__delay_save_timer and not self.__delay_save_timer.done():
            self.__delay_save_timer.cancel()
            self.__delay_save_timer = None
            if save:
                self.save(force=True)

    def _schedule_save_timer(self):
        if self.__delay_save_timer and not self.__delay_save_timer.done() or not self.__delay_save_minutes:
            return False
        loop = asyncio.get_running_loop()
        if loop is None:
            return False

        self.__delay_save_timer = loop.create_task(asyncio.sleep(self.__delay_save_minutes * 60))
        self.__delay_save_timer.add_done_callback(lambda f: None if f.cancelled() else self.save(force=True))
        return True

    # noinspection PyMethodMayBeStatic
    def on_deserialize_error(self, stacks: list[ParseError]):
        if self.__errors is CnfErr.IGNORE:
            for stack in stacks:
                stack.entry.value = stack.entry.default
            return

        if self.__errors is CnfErr.NOT_SET and not sum(isinstance(s.error, ValueNotSet) for s in stacks):
            for stack in stacks:
                stack.entry.value = stack.entry.default
            return

        # RAISE
        errors = []
        for stack in stacks:
            errors.append(f"{stack.key} -> {str(stack.error) or type(stack.error).__name__}")
            errors.append("".join(traceback.format_exception(stack.error)))
        raise ConfigurationValueError(stacks, "Deserializing Failed\n" + "\n".join(errors))

    # noinspection PyMethodMayBeStatic
    def on_serialize_error(self, stacks: list[ParseError]):
        # RAISE
        errors = "\n".join(f"{s.key} -> {str(s.error) or type(s.error).__name__}" for s in stacks)
        raise ConfigurationValueError(stacks, "Serializing Failed\n" + errors)

    def __del__(self):
        self.cancel_save_timer()

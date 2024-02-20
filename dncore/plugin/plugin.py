import asyncio
import importlib.machinery
import logging
import re
import sys
import zipfile
import zipimport
from collections import defaultdict
from pathlib import Path
from typing import Optional, Iterable, Callable

import discord
import ruamel.yaml

from dncore.abc import Version
from dncore.discord.status import Activity
from dncore.event import EventListener
from dncore.util.discord import get_intent_names
from dncore.util.instance import get_core, call_event
from dncore.util.module import import_module_from_file_location
from .errors import *
from .events import *

log = logging.getLogger(__name__)
yaml = ruamel.yaml.YAML()
__all__ = ["PluginInfo", "Plugin",
           "PluginLoader", "PluginModuleLoader", "PluginZipFileLoader",
           "PluginContainer", "PluginManager", "sorted_plugins", "all_iter"]


def all_iter(path: Path, *, check: Callable[[Path], bool]):
    for child in path.iterdir():
        if check(child):
            if child.is_dir():
                yield from all_iter(child, check=check)
            else:
                yield child


def sorted_plugins(ls: list["PluginInfo"]):
    entries = defaultdict(list)  # type: dict[str, list[PluginInfo]]
    for info in ls:
        entries[info.name].append(info)

    complete = []  # type: list[PluginInfo]
    for name, es in entries.items():
        # es.sort(key=lambda i: (i.version, not i.version.beta), reverse=True)
        es.sort(key=lambda i: i.version, reverse=True)
        complete.append(es[0])
    return complete


class PluginInfo:
    EXTENSIONS_ROOT = Path("dncore/extensions")
    # PACKAGES = {}
    ALLOW_NAME = re.compile(r"^[a-zA-Z0-9_]+$")

    def __init__(self, name, *, main, version, loader, plugin_data_dir):
        """
        :type name: str
        :type main: str
        :type version: Version
        :type loader: PluginLoader
        :type plugin_data_dir: Path
        """
        if PluginInfo.ALLOW_NAME.fullmatch(name) is None:
            raise ValueError(f"Invalid plugin name: {name}")

        self.name = name
        self.main = main
        self.version = version
        self.authors: list[str] = []
        self.depends: list[str] = []
        self.libraries: list[str] = []
        self.target_dncore: Optional[Version] = None
        self.resource_files: list[str] = []
        self.description = None  # type: str | None
        self.changelog = None  # type: dict[str, str] | None

        self.instance: Optional[Plugin] = None
        self.enabled = False
        self.loader = loader
        self.data_dir = plugin_data_dir
        self.load_exception: Optional[Exception] = None

    def is_reloadable(self):
        if self.instance:
            return getattr(self.instance, "reloadable", False)
        return True

    def load(self):
        if self.instance:
            return
        # self.get_logger().addFilter(PluginInfo.PluginNameFilter(self.name))

        try:
            main_class = self.loader.load_main_class(self, PluginInfo.EXTENSIONS_ROOT)  # type: type[Plugin]
            if not issubclass(main_class, Plugin):
                raise ValueError(f"クラス {main_class!r} は Plugin を継承していません。")
            main_class._info = self
            self.instance = main_class()
        except Exception:
            try:
                self.loader.unload_module()
            except (Exception,):
                pass
            raise
        return self.instance

    def __repr__(self):
        try:
            module_name = self.loader.get_module_name()
        except AttributeError:
            module_name = None
        return f"<PluginInfo name={self.name!r} loader={type(self.loader).__name__} module={module_name!r}>"

    def serialize(self):
        serialized = dict(
            main=self.main,
            name=self.name,
            version=str(self.version),
        )

        if len(self.authors) == 1:
            serialized["author"] = self.authors[0]
        elif self.authors:
            serialized["authors"] = self.authors

        if self.depends:
            serialized["depends"] = self.depends

        if self.libraries:
            serialized["libraries"] = self.libraries

        if self.target_dncore:
            serialized["dncore"] = self.target_dncore

        if self.description:
            serialized["description"] = self.description

        if self.changelog:
            serialized["changelog"] = self.changelog

        return serialized

    @classmethod
    def deserialize(cls, data: dict, loader: "PluginLoader", data_dir: Path):
        try:
            main: str = data["main"]
            version = Version.parse(str(data["version"]))
            data_dir = data_dir / data["name"]
            info = PluginInfo(name=data["name"], main=main, version=version, loader=loader, plugin_data_dir=data_dir)
            authors = data.get("authors", [])
            if "author" in data:
                authors.insert(0, data["author"])
            info.authors = [author for author in authors if isinstance(author, str)]
            info.depends = [depend for depend in data.get("depends", []) if isinstance(depend, str)]
            # info.loader = PluginModuleLoader(PluginInfo.EXTENSIONS_ROOT, info, extension_dir)
            if "libraries" in data:
                info.libraries = data["libraries"]
            if "dncore" in data:
                info.target_dncore = Version.parse(data["dncore"])

            info.resource_files = [e for e in data.get("resource_files", []) if isinstance(e, str)]

            if isinstance(data.get("description"), str):
                info.description = data["description"]

            if isinstance(data.get("changelog"), dict):
                info.changelog = data["changelog"]

        except KeyError as e:
            raise InvalidPluginInfo(f"Invalid info, not exists '{e}' key")
        return info


class Plugin(EventListener):
    _info: PluginInfo
    _use_intents = 0
    reloadable = True

    def __repr__(self):
        return f"<Plugin name={self.info.name!r} enabled={self.enabled!r} version={str(self.info.version)!r} >"

    @property
    def loop(self):
        return asyncio.get_running_loop()

    @property
    def enabled(self):
        return self._info.enabled

    @property
    def info(self):
        return self._info

    @property
    def data_dir(self) -> Path:
        return self._info.data_dir

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_cleanup(self):
        pass

    def register_activity(self, activity: Activity):
        return get_core().activity_manager.register_activity(self, activity)

    def unregister_activity(self, activity: Activity = None):
        return get_core().activity_manager.unregister_activity(owner=self, activity=activity)

    def register_listener(self, listener: EventListener):
        return get_core().events.register_listener(self, listener)

    def unregister_listener(self, listener: EventListener = None):
        if listener is None:
            return get_core().events.unregister_listeners(self)
        else:
            get_core().events.unregister_listener(listener)

    def register_commands(self, clazz):
        return get_core().commands.register_class(self, clazz)

    def register_command(self, command):
        """
        :type command: dncore.commands.CommandHandler
        """
        get_core().commands.register(self, command)

    def unregister_commands(self):
        get_core().commands.unregister_handlers(self)

    async def extract_resources(self):
        if isinstance(self.info.loader, PluginZipFileLoader):
            loader = self.info.loader
            return await get_core().loop.run_in_executor(
                None, lambda: loader.extract_resource_files(self.info))

    async def _enable(self):
        await self.on_enable()
        self.register_listener(self)
        self.register_commands(self)

    async def _disable(self):
        try:
            await self.on_disable()
        finally:
            if isinstance(self, EventListener):
                # noinspection PyUnresolvedReferences
                self.unregister_listener(self)
            self.unregister_commands()
            self.unregister_activity(None)

    @property
    def use_intents(self) -> int:
        return self._use_intents

    @use_intents.setter
    def use_intents(self, intents: tuple[discord.flags.flag_value] | discord.flags.flag_value):
        if not isinstance(intents, Iterable):
            intents = (intents,)
        value = 0
        for intent in intents:
            if intent.flag not in discord.Intents.VALID_FLAGS.values():
                raise ValueError(f"Invalid intent: {intent}")
            value |= intent.flag
        self._use_intents = value

        if get_core().client:
            requires = value & ~ get_core().client.intents.value
            if requires:
                req_names = ", ".join(get_intent_names(requires))
                log.warning(f"Unable to enable intents until reconnected: {req_names} by {self.info.name}")


class PluginLoader:
    def create_info(self) -> PluginInfo:
        raise NotImplementedError

    def load_main_class(self, info: PluginInfo, modules_root_path: Path) -> type[Plugin]:
        raise NotImplementedError

    def get_module_name(self) -> str:
        raise NotImplementedError

    def get_module_prefix(self) -> str:
        raise NotImplementedError

    def get_import_name(self) -> str:
        raise NotImplementedError

    def unload_module(self):
        mod = self.get_import_name()
        if mod:
            [sys.modules.pop(m) for m in list(sys.modules.keys()) if m.startswith(mod)]


class PluginModuleLoader(PluginLoader):
    def __init__(self, module_directory: Path, data_dir: Path):
        if not module_directory.is_dir():
            raise ValueError("module_directory is not directory")

        self.info_file = info_file = module_directory / "plugin.yml"
        if not info_file.is_file():
            raise ValueError("module_directory does not contains plugin.yml file")

        self.module_directory = module_directory
        self.data_dir = data_dir
        self._module_name = None  # type: Optional[str]
        self._import_module_name = None

    def create_info(self):
        with self.info_file.open("r", encoding="utf8") as file:
            return PluginInfo.deserialize(yaml.load(file), self, self.data_dir)

    def load_main_class(self, info: PluginInfo, modules_root_path: Path):
        if info.target_dncore:
            core_ver = get_core().version
            if info.target_dncore > core_ver:
                raise PluginRequirementsError(f"非対応バージョンです (v{info.target_dncore}] <= v{core_ver.numbers})")

        # packageとmodule単語の使い方が逆。いつか直す
        main = info.main
        package = main[:main.rindex(".")]
        clazz = main[main.rindex(".") + 1:]
        modules_root = ".".join(modules_root_path.parts)

        module = package.split(".")
        while module and not (modules_root_path / "/".join(module)).is_dir():
            module.pop()
        module = ".".join(module)

        _import_module = modules_root + "." + (module if module else package)
        _import_package = modules_root + "." + package
        self._module_name = module if module else package
        self._import_module_name = _import_module
        # self._import_module_name = _import_package

        author = info.authors[0] if info.authors else "unknown"
        log.debug("Loading %s v%s by %s (module: %s)", info.name, info.version, author, self._module_name)

        # load module (or package)
        import_module_from_file_location(_import_module, self.module_directory)
        # load package
        mod = importlib.import_module(_import_package)
        return getattr(mod, clazz)

    def get_module_name(self):
        return getattr(self, "_module_name")

    def get_module_prefix(self):
        return self.get_module_name().split(".", 1)[0]

    def get_import_name(self):
        return self._import_module_name

    async def pack_to_plugin_file(self, plugins_dir: Path, *, info: PluginInfo = None, extra_name: str = None):
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.pack_to_plugin_file_(plugins_dir, info=info, extra_name=extra_name))

    def pack_to_plugin_file_(self, plugins_dir: Path, *, info: PluginInfo = None, extra_name: str = None):
        if info is None:
            info = self.create_info()

        _name = info.name
        _ver = str(info.version).replace("/", "-")
        _extra = f"_{extra_name}" if extra_name else ""
        out_name = f"{_name}-{_ver}{_extra}.dcp"

        if (plugins_dir / out_name).is_file():
            raise FileExistsError(f"already exists: {plugins_dir / out_name}")

        log.info("Plugin Packing: %s", self.module_directory)
        try:
            # search module files
            files = []  # type: list[Path]
            module_dir = self.module_directory
            info_path = None
            for child in all_iter(module_dir, check=lambda p: not p.is_dir() or p.name != "__pycache__"):
                if child.name == "plugin.yml":
                    info_path = child
                    continue
                files.append(child)

            # search target resources
            resource_files = []  # type: list[Path]
            plugin_data_dir = self.data_dir / info.name
            if plugin_data_dir.is_dir():
                for child in all_iter(plugin_data_dir, check=lambda p: True):
                    for allow in info.resource_files:
                        if child.relative_to(plugin_data_dir).as_posix().startswith(allow):
                            resource_files.append(child)

            # create
            with zipfile.ZipFile(plugins_dir / out_name, "w", compression=zipfile.ZIP_DEFLATED) as arc:
                for file in files:
                    log.info("- %s", file)
                    arc.write(file, arcname=Path(module_dir.name / file.relative_to(module_dir)).as_posix())
                for file in resource_files:
                    log.info("- %s", file)
                    arc.write(file, arcname=file.relative_to(plugin_data_dir).as_posix())

                if info_path is None:
                    log.warning("Not contains plugin.yml! new writing...")
                    arc.writestr("plugin.yml", yaml.dump(info.serialize()))
                else:
                    log.info("- %s", info_path)
                    arc.write(info_path, arcname="plugin.yml")

            log.info("Pack completed!")
            return plugins_dir / out_name

        except Exception as e:
            log.error("Pack Failed: %s", str(e))
            raise

    def __repr__(self):
        return "<{} modPath='{}'>".format(type(self).__name__, self.module_directory)

    def unload_module(self):
        if self.module_directory:
            name = str(self.module_directory.absolute())
            [sys.path_importer_cache.pop(mod)
             for mod in list(sys.path_importer_cache.keys()) if mod.startswith(name)]

        super().unload_module()


class PluginZipFileLoader(PluginLoader):
    def __init__(self, plugin_file: Path, data_dir: Path):
        if not plugin_file.is_file():
            raise ValueError("plugin_file is not file")

        self.data_dir = data_dir

        with zipfile.ZipFile(plugin_file) as pl_file:
            if "plugin.yml" not in pl_file.namelist():
                raise ValueError("not contains plugin.yml file")

        self.plugin_file = plugin_file
        self._module_name = None  # type: Optional[str]
        self._import_module_name = None
        self._importer = None  # type: zipimport.zipimporter | None
        try:
            # noinspection PyUnresolvedReferences
            self.__zip_directory_cache = zipimport._zip_directory_cache
        except AttributeError:  # これができないとZipからキャッシュを消せない
            self.__zip_directory_cache = None
            log.warning("Cannot access zipimport._zip_directory_cache")

    def create_info(self) -> PluginInfo:
        with zipfile.ZipFile(self.plugin_file) as pl_file:
            with pl_file.open("plugin.yml", "r") as info_file:
                return PluginInfo.deserialize(yaml.load(info_file), self, self.data_dir)

    def load_main_class(self, info: PluginInfo, modules_root_path: Path):
        if info.target_dncore:
            core_ver = get_core().version
            if info.target_dncore > core_ver:
                raise PluginRequirementsError(f"非対応バージョンです (v{info.target_dncore}] <= v{core_ver.numbers})")

        # packageとmodule単語の使い方が逆。いつか直す
        main = info.main  # testplugin.testplugin.TestPlugin
        package = main[:main.rindex(".")]  # testplugin.testplugin
        clazz = main[main.rindex(".")+1:]  # TestPlugin
        modules_root = ".".join(modules_root_path.parts)  # dncore.extensions

        self._importer = zipimport.zipimporter(self.plugin_file)

        _sp = package.count(".")
        for i in range(_sp + 1):
            module = ".".join(package.split(".")[: i or None])
            mod_spec = self._importer.find_spec(module)
            if mod_spec:
                break
        else:
            raise Exception(f"Cannot find module: {package}")

        _import_package = modules_root + "." + package
        _import_module = modules_root + "." + module
        self._module_name = module if module else package
        self._import_module_name = _import_module

        author = info.authors[0] if info.authors else "unknown"
        log.debug("Loading %s v%s by %s (module: %s)", info.name, info.version, author, self._module_name)

        # load module (or package)
        mod = self._importer.load_module(_import_module)  # import testplugin
        if _import_module != _import_package:
            mod = importlib.import_module(_import_package)  # import testplugin.main
        return getattr(mod, clazz)

    def get_module_name(self):
        return getattr(self, "_module_name")

    def get_module_prefix(self):
        return self.get_module_name().split(".", 1)[0]

    def get_import_name(self):
        return self._import_module_name

    async def unpack_to_extension_module(self, extensions_dir: Path, *, info: PluginInfo = None, extract_resources=False):
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.unpack_to_extension_module_(extensions_dir, info=info, extract_resources=extract_resources))

    def unpack_to_extension_module_(self, extensions_dir: Path, *, info: PluginInfo = None, extract_resources=False):
        if info is None:
            info = self.create_info()

        mod_name = info.main.split(".")[0]
        plugin_data_dir = info.data_dir

        try:
            next((extensions_dir / mod_name).iterdir())
        except (FileNotFoundError, StopIteration):
            pass
        else:
            raise FileExistsError(f"not empty directory: {extensions_dir / mod_name}")

        log.info("Plugin Unpacking: %s", self.plugin_file)
        try:
            exported_info_file = False
            with zipfile.ZipFile(self.plugin_file, "r") as arc:
                for entry in arc.infolist():
                    if entry.filename.startswith(mod_name):
                        p = extensions_dir / entry.filename
                        try:
                            p.absolute().relative_to(extensions_dir.absolute())
                        except ValueError:
                            log.warning("- %s", p)
                            log.warning("unsafe path, ignored it!")
                        else:
                            log.info("- %s", p)
                            arc.extract(entry, path=extensions_dir)

                    elif entry.filename == "plugin.yml":
                        exported_info_file = True
                        p = extensions_dir / mod_name / entry.filename
                        log.info("- %s", p)
                        arc.extract(entry, path=extensions_dir / mod_name)

                    if not info.resource_files or not extract_resources:
                        continue

                    if info.resource_files and not plugin_data_dir.exists():
                        plugin_data_dir.mkdir(exist_ok=True)
                    for file in info.resource_files:
                        # if PurePath(entry.filename).match(file):
                        if entry.filename.startswith(file):
                            p = plugin_data_dir / entry.filename
                            try:
                                p.absolute().relative_to(plugin_data_dir.absolute())
                            except ValueError:
                                log.warning("- %s", p)
                                log.warning("unsafe path, ignored it!")
                            else:
                                if (plugin_data_dir / entry.filename).exists():
                                    log.info("- (IGN) %s", p)
                                else:
                                    log.info("- %s", p)
                                    arc.extract(entry, path=plugin_data_dir)

            if not exported_info_file:
                log.warning("Not contains plugin.yml! new writing...")
                with open(extensions_dir / mod_name / "plugin.yml", "w", encoding="utf8") as file:
                    yaml.dump(file, info.serialize())

            log.info("Unpack completed!")
            return extensions_dir / mod_name

        except Exception as e:
            log.error("Unpack Failed: %s", str(e))
            raise

    def extract_resource_files(self, info: PluginInfo):
        if not info.resource_files:
            return

        plugin_data_dir = info.data_dir
        log.info("Unpacking plugin resource files: %s", self.plugin_file)
        try:
            file_count = 0
            file_size = 0
            with zipfile.ZipFile(self.plugin_file, "r") as arc:
                for entry in arc.infolist():
                    for file in info.resource_files:
                        if entry.filename.startswith(file):
                            p = plugin_data_dir / entry.filename
                            try:
                                p.absolute().relative_to(plugin_data_dir.absolute())
                            except ValueError:
                                log.warning("ignored unsafe path: %s", p)
                            else:
                                if (plugin_data_dir / entry.filename).exists():
                                    log.warning("ignored already exists: %s", p)
                                else:
                                    file_count += 1
                                    file_size += entry.file_size
                                    arc.extract(entry, path=plugin_data_dir)

        except Exception as e:
            log.error("Unpack Failed: %s", str(e))
            raise
        else:
            log.info("Unpack resources completed! (%s files, %s MB)",
                     file_count, round(file_size / 1024 / 1024, 1))

    def __repr__(self):
        return "<{} pluginFile='{}'>".format(type(self).__name__, self.plugin_file)

    def unload_module(self):
        if self.plugin_file:
            name = str(self.plugin_file)
            [sys.path_importer_cache.pop(mod)
             for mod in list(sys.path_importer_cache.keys()) if mod.startswith(name)]

        try:
            if self._importer:
                if self.__zip_directory_cache is not None:
                    # clear cache
                    self.__zip_directory_cache.pop(self._importer.archive, None)
                else:
                    self._importer.invalidate_caches()

        finally:
            super().unload_module()


class PluginContainer(dict[str, PluginInfo]):
    def remove(self, plugin: Plugin | PluginInfo):
        info = plugin if isinstance(plugin, PluginInfo) else plugin.info

        for name, pi in self.items():
            if info is pi:
                return self.pop(name)

    @property
    def instances(self):
        return [p.instance for p in self.values() if p.enabled and p.instance]


class PluginManager(object):
    def __init__(self, loop: asyncio.AbstractEventLoop, plugins_directory: Path, *, data_dir: Path = None):
        self.loop = loop
        self.extensions_directory = Path("dncore/extensions")
        self.plugins_directory = plugins_directory
        self.plugins = PluginContainer()

        self.plugin_data_dir = plugins_directory if data_dir is None else data_dir

    def get_plugin(self, name: str):
        info = self.plugins.get(name.lower())
        if info:
            return info.instance

    def get_plugin_info(self, name: str):
        return self.plugins.get(name.lower())

    def _load_plugins(self):
        if self.plugins:
            raise PluginOperationError("Already loaded plugins")

        # select extension files
        if self.extensions_directory.is_dir():
            def check(c: Path):
                if not c.is_dir():
                    return False
                if not (c / "plugin.yml").is_file():
                    return False
                if c.name.startswith("_") or c.name.endswith(".bak"):
                    return False
                return True
            extension_dirs = [child for child in sorted(self.extensions_directory.iterdir()) if check(child)]
        else:
            extension_dirs = []

        # load extension info
        _extensions = []
        for extension_dir in extension_dirs:
            try:
                info = PluginModuleLoader(extension_dir, self.plugin_data_dir).create_info()

            except (KeyError, ValueError, ImportError, InvalidPluginInfo) as e:
                log.warning(f"{extension_dir} は無効なプラグインです: {type(e).__name__}: {str(e)}")
                continue
            except (Exception,):
                log.warning(f"{extension_dir} のロードに失敗しました。", exc_info=True)
                continue

            _extensions.append(info)
        extensions = {i.name: i for i in sorted_plugins(_extensions)}  # type: dict[str, PluginInfo]

        # select plugin files
        plugins_path = self.plugins_directory
        plugins_path.mkdir(parents=True, exist_ok=True)
        plugin_files = [child for child in sorted(plugins_path.iterdir())
                        if child.is_file() and child.name.endswith(".dcp")]

        # load plugin info
        _plugins = []
        for plugin_file in plugin_files:
            try:
                info = PluginZipFileLoader(plugin_file, self.plugin_data_dir).create_info()

            except (KeyError, ValueError, ImportError, OSError) as e:
                log.warning(f"{plugin_file} は無効なプラグインです: {type(e).__name__}: {str(e)}")
                continue
            except (Exception,):
                log.warning(f"{plugin_file} のロードに失敗しました。", exc_info=True)
                continue

            _plugins.append(info)
        plugins = {i.name: i for i in sorted_plugins(_plugins)}  # type: dict[str, PluginInfo]

        # select extension vs plugin
        selected = list(extensions.values())
        selected.extend(i for i in plugins.values() if i.name not in extensions)
        selected.sort(key=lambda i: i.name)

        # depends priority
        _selected = {i.name: i for i in selected}
        _checks = list(selected)
        while _checks:
            target = _checks.pop(0)
            if target.depends:
                _p_entries = [selected.index(_selected[depend_name])
                              for depend_name in target.depends if depend_name in _selected]
                if not _p_entries:
                    continue

                priority_index = min(_p_entries)
                if selected.index(target) < priority_index + 1:
                    selected.remove(target)
                    selected.insert(priority_index + 1, target)

        return selected

    def load_plugins(self, *, ignore_names: list[str] = None):
        self.plugins.clear()
        _ignore_names = [n.lower() for n in ignore_names] if ignore_names else []
        ignored = []  # type: list[PluginInfo]

        for info in self._load_plugins():
            if info.name.lower() in _ignore_names:
                ignored.append(info)
                continue

            self.plugins[info.name.lower()] = info
            try:
                info.load()
            except PluginException as e:
                log.error(f"プラグイン {info.name} を初期化できません: {e}")
                info.load_exception = e
            except Exception as e:
                log.exception(f"プラグイン {info.name} を初期化できません。")
                info.load_exception = e

        log.debug("Loaded %s plugins (%s disabled)", len(self.plugins), len(ignored))

    async def enable_plugins(self):
        results = ([], [])
        for pi in list(self.plugins.values()):
            r = pi.enabled
            if not pi.enabled and pi.instance:
                r = await self.enable_plugin(pi)
            results[not r].append(pi)

        log.info("プラグイン %s個を有効化しました。%s", len(results[0]), f" (エラー: {len(results[1])})" if results[1] else "")
        return results

    async def disable_plugins(self):
        log.debug("Disabling plugins")

        for pi in reversed(list(self.plugins.values())):
            if pi.enabled:
                try:
                    await self.disable_plugin(pi)
                except (Exception,):
                    log.exception(f"Exception in disable {pi.name} plugin", exc_info=True)

    # enable/disable

    async def enable_plugin(self, plugin: PluginInfo | Plugin):
        info = plugin if isinstance(plugin, PluginInfo) else plugin.info

        if info not in self.plugins.values():
            raise PluginException("Not loaded in plugin manager")
        if not info.instance:
            raise PluginOperationError("Not initialized")
        if info.enabled:
            raise PluginOperationError("Already enabled")

        try:
            # noinspection PyProtectedMember
            await info.instance._enable()

        except (BaseException,):
            log.error(f"{info.name}プラグインの起動エラーが発生しました", exc_info=True)

            try:
                # noinspection PyProtectedMember
                await info.instance._disable()
            except (BaseException,):
                pass
            try:
                await info.instance.on_cleanup()
            except (BaseException,):
                pass

            return False

        log.debug("Enabled %s v%s", info.name, info.version)
        info.enabled = True

        await call_event(PluginEnableEvent(info))

        return True

    # noinspection PyMethodMayBeStatic
    async def disable_plugin(self, plugin: PluginInfo | Plugin):
        info = plugin if isinstance(plugin, PluginInfo) else plugin.info

        if info.enabled:
            depends = [pi.name for pi in self.plugins.values() if info.name in pi.depends and pi.enabled]
            if depends:
                raise PluginOperationError("depends: " + ", ".join(depends))

            log.debug(f"Disabling {info.name} v{info.version}")

            try:
                # noinspection PyProtectedMember
                await info.instance._disable()

            except (BaseException,):
                log.error(f"{info.name}プラグインの停止エラーが発生しました", exc_info=True)
                return False

            finally:
                info.enabled = False
                try:
                    await info.instance.on_cleanup()
                except (BaseException,):
                    log.warning(f"{info.name}プラグインのアンロードエラーが発生しました", exc_info=True)

            await call_event(PluginDisableEvent(info))

        return True

    async def reload_plugin(self, plugin: PluginInfo | Plugin):
        info = plugin if isinstance(plugin, PluginInfo) else plugin.info

        if not info.is_reloadable():
            raise PluginOperationError("Not reloadable plugin")

        if info.enabled:
            await self.disable_plugin(info)

        await self.unload_plugin(info)
        new_info = await self.load_plugin(info.loader, None)

        if new_info:
            await self.enable_plugin(new_info)

        return new_info

    # load/unload

    async def load_plugin(self, loader: PluginLoader, info: PluginInfo | None):
        if info is None:
            info = loader.create_info()

        if info.name.lower() in self.plugins:
            raise PluginOperationError(f"Already exists plugin name: {info.name}")

        try:
            info.load()
        except PluginException as e:
            log.error(f"プラグイン {info.name} を初期化できません: {e}")
            info.load_exception = e
            return

        except Exception as e:
            log.exception(f"プラグイン {info.name} を初期化できません。")
            info.load_exception = e
            return

        self.plugins[info.name.lower()] = info
        return info

    async def unload_plugin(self, info: PluginInfo):
        if info.enabled:
            raise PluginOperationError("Enabled Plugin")

        if info.instance:
            try:
                await info.instance.on_cleanup()
            except (BaseException,):
                log.warning(f"{info.name}プラグインのアンロードエラーが発生しました", exc_info=True)

        info.instance = None
        self.plugins.remove(info)
        info.loader.unload_module()

        return True

    # packages

    async def pack_to_plugin_file(self, mod_dir: Path, extra_name: str = None):
        loader = PluginModuleLoader(module_directory=mod_dir, data_dir=self.plugin_data_dir)
        return await loader.pack_to_plugin_file(self.plugins_directory, extra_name=extra_name)

    async def unpack_to_extension_module(self, dcp_file: Path, extract_resources=False):
        loader = PluginZipFileLoader(plugin_file=dcp_file, data_dir=self.plugin_data_dir)
        return await loader.unpack_to_extension_module(self.extensions_directory, extract_resources=extract_resources)

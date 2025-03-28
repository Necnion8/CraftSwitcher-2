import sys


def main():
    if len(sys.argv) <= 1:
        return run_app()

    action = sys.argv[1].lower()

    if action in ("-v", "--version"):
        from dncore import version_info
        print(version_info)

    elif action in ("--pack-plugin",):
        try:
            mod_name = sys.argv[2]
        except IndexError:
            print("Please specify extension module directory", file=sys.stderr)
            sys.exit(1)
        _args = list(sys.argv)
        file_override = _args and _args[-1] == "-f" and _args.pop(-1) or False
        try:
            extra_name = _args[3]
        except IndexError:
            extra_name = None

        from pathlib import Path
        import logging
        from dncore.plugin import PluginModuleLoader

        mod_dir = Path("dncore/extensions/") / mod_name
        plugins_dir = Path("plugins")
        if not mod_dir.is_dir():
            print(f"{mod_dir} not exists or file", file=sys.stderr)
            sys.exit(1)

        logging.basicConfig(format="{message}", style="{", level=logging.DEBUG)
        loader = PluginModuleLoader(module_directory=mod_dir, data_dir=plugins_dir)
        try:
            packed = loader.pack_to_plugin_file_(plugins_dir, extra_name=extra_name, force_override=file_override)

        except FileExistsError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

        print(f"Source: {mod_dir}")
        print(f"Packed: {packed}")

    elif action in ("--unpack-plugin",):
        try:
            file_name = sys.argv[2]
        except IndexError:
            print("Please specify plugin file name", file=sys.stderr)
            sys.exit(1)

        from pathlib import Path
        import logging
        from dncore.plugin import PluginZipFileLoader

        ext_dir = Path("dncore/extensions")
        plugins_dir = Path("plugins")
        plugin_file = plugins_dir / file_name
        if not plugin_file.is_file():
            print(f"{plugin_file} not exists or directory", file=sys.stderr)
            sys.exit(1)

        logging.basicConfig(format="{message}", style="{", level=logging.DEBUG)
        loader = PluginZipFileLoader(plugin_file=plugin_file, data_dir=plugins_dir)
        try:
            unpacked = loader.unpack_to_extension_module_(ext_dir, extract_resources=False)

        except FileExistsError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

        print(f"Source: {plugin_file}")
        print(f"Packed: {unpacked}")

    elif action in ("--list-plugins",):
        print("Loading")
        import asyncio
        import logging
        from pathlib import Path
        from dncore.plugin import PluginManager, PluginModuleLoader, PluginZipFileLoader
        logging.basicConfig(format="ERR: {message}", style="{", level=logging.ERROR)
        mgr = PluginManager(asyncio.new_event_loop(), Path("plugins"))
        plugins = mgr._load_plugins()
        print()
        print("[All Plugin]")
        print(" " * 5 + "-" * 55)
        for p in plugins:
            fp = loader = None
            if isinstance(p.loader, PluginModuleLoader):
                fp = p.loader.module_directory
                loader = type(p.loader).__name__
            elif isinstance(p.loader, PluginZipFileLoader):
                fp = p.loader.plugin_file
                loader = type(p.loader).__name__

            print(f" {p.name:20} | {str(p.version):16} | {fp or ''}")

        print("-" * 60)
        print()
        print("[Required libraries]")
        print(" " * 20 + "-" * 40)
        for p in plugins:
            if not p.libraries:
                continue
            print(f" {p.name:20} |", ", ".join(p.libraries))
        print("-" * 60)
        print()
        print(f"Total {len(plugins)} plugins")

    else:
        print()
        print("  dnCore Discord Bot Client  by Necnion8")
        print()
        print("Usage:")
        print("  -v, --version      - Show version")
        print("  --list-plugins     - Show plugin list")
        print("  --pack-plugin (extensionModuleName) [pluginExtraName]  - Pack extension module to plugin file")
        print("  --unpack-plugin (pluginFileName)                       - Unpack plugin file to extension module")
        print()


def run_app():
    ignored_modules = list(m for m in sys.modules.keys() if not m.startswith("dncore"))

    while True:
        from dncore.dncore import DNCore
        from dncore.errors import RestartRequest

        try:
            sys.exit(DNCore().run())

        except RestartRequest:
            ref = sum(bool(sys.modules.pop(m, None))
                      for m in list(sys.modules.keys())
                      if m not in ignored_modules)
            print("Unloaded", ref, "modules")
            continue


if __name__ == '__main__':
    main()

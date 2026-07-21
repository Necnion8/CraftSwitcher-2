__all__ = ["get_version", ]
__version__ = "2.0.0"


def _set_version(plugin_info):
    global __version__
    import logging
    __version__ = str(i.version.numbers) if (i := plugin_info) else __version__
    log = logging.getLogger(__name__)
    log.info(f"INIT VER {__version__}")


def get_version():
    return __version__

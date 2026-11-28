import sys
from importlib import import_module
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_file_location
from inspect import isfunction
from typing import Callable
from zipimport import zipimporter

__all__ = [
    "import_module_from_file_location",
    "VirtualZipImporter",
]


class NameSpecFinder(MetaPathFinder):
    def __init__(self, name: str, spec: ModuleSpec | Callable[[], ModuleSpec]):
        self.name = name
        if isfunction(spec):
            self.spec = spec
        else:
            self.spec = lambda: spec

    def find_spec(self, fullname, *_):
        return self.spec() if fullname == self.name else None


def import_module_from_file_location(name, location):
    """
    https://qiita.com/kzm4269/items/e7e67ab6c1dd278c3d16
    """
    finder = NameSpecFinder(name, lambda: spec_from_file_location(name, location))
    sys.meta_path.insert(0, finder)
    try:
        return import_module(name)
    finally:
        sys.meta_path.remove(finder)


class VirtualZipImporter(MetaPathFinder):
    def __init__(self, zip_loader: zipimporter, mod_prefix: str):
        self.zip_loader = zip_loader
        self.mod_prefix = mod_prefix

    def find_spec(self, fullname, path, target=None):
        prefix_dot = self.mod_prefix + "."

        if fullname == self.mod_prefix:
            return ModuleSpec(fullname, None, is_package=True)

        if fullname.startswith(prefix_dot):
            real_mod_name = fullname[len(prefix_dot):]
            spec = self.zip_loader.find_spec(real_mod_name, target)

            if spec is not None:
                spec.name = fullname
                return spec

        return None

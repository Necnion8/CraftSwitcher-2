from dncore.plugin import Plugin


class CraftSwitcherPlugin(Plugin):
    _inst: "CraftSwitcherPlugin"
    pass


def getinst() -> "CraftSwitcherPlugin":
    inst = CraftSwitcherPlugin._inst
    if inst and inst.enabled:
        return inst
    raise RuntimeError("CraftSwitcher is not instanced or enabled!")

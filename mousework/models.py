"""The supported mice and where they differ.

References such as "survey C.1" point to sections of the clean-room model
survey in ../spec/SURVEY.md. Everything not listed there works as in SPEC.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    key: str  # stable identifier, also used in logs
    name: str  # for display
    product_id: int  # receiver, vendor 0x1038
    bootloader_id: int
    lighting: bool  # wheel lighting (spec 3.4)
    smart_illumination: bool  # the movement-saving byte of the power command (spec 3.3)
    debounce: bool  # debounce read-back (spec 3.8)
    # True when the mouse has no high efficiency mode of its own: the host
    # keeps the switch and forces 125 Hz polling instead (survey C.1).
    host_high_efficiency: bool
    xy_cpi: bool  # one-byte X/Y CPI table, opcodes 0x2C/0xAC (survey C.1)
    charge_status: bool  # battery reply byte 2 is a charge status (spec 5; survey S2)
    # Seconds after a link-up during which battery levels are not trusted,
    # because alkaline cells read low until they recover (survey C.1).
    battery_settle_s: float
    # Built from the specification alone and never tested on the real mouse.
    untested: bool


RIVAL_3_WIRELESS = Model(
    key="rival-3-wireless", name="SteelSeries Rival 3 Wireless",
    product_id=0x1830, bootloader_id=0x1831,
    lighting=True, smart_illumination=True, debounce=True,
    host_high_efficiency=False, xy_cpi=False, charge_status=True,
    battery_settle_s=0.0, untested=False)

RIVAL_3_WIRELESS_GEN_2 = Model(
    key="rival-3-wireless-gen-2", name="SteelSeries Rival 3 Wireless Gen 2",
    product_id=0x1872, bootloader_id=0x1873,
    lighting=False, smart_illumination=False, debounce=False,
    host_high_efficiency=True, xy_cpi=True, charge_status=False,
    battery_settle_s=10.0, untested=True)

MODELS = (RIVAL_3_WIRELESS, RIVAL_3_WIRELESS_GEN_2)
BY_PRODUCT_ID = {m.product_id: m for m in MODELS}
DEFAULT = RIVAL_3_WIRELESS


def of(mouse):
    """The model of a device.Mouse, or the default for objects without one."""
    model = getattr(mouse, "model", None)
    return model if isinstance(model, Model) else DEFAULT

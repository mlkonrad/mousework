"""Wire protocol for the SteelSeries Rival 3 Wireless (1038:1830) and its Gen 2.

Pure encoding and decoding with no I/O. References such as "spec 3.1" point to
sections of the clean-room specification in ../spec/SPEC.md, and "survey C.1"
to the model survey in ../spec/SURVEY.md. models.py says which model uses what.
"""

from dataclasses import dataclass, field

VENDOR_ID = 0x1038
PRODUCT_ID = 0x1830
BOOTLOADER_PRODUCT_ID = 0x1831

COMMAND_USAGE = (0xFFC0, 0x0001)  # spec 1.2, interface 3
EVENT_USAGE = (0xFF00, 0x0001)  # spec 1.2, interface 2

REPORT_LEN = 64

# Opcode bits (spec 2.2)
READ = 0x80
RECEIVER = 0x40

# Opcodes
OP_RESET = 0x01
OP_BUFFER_WRITE = 0x03
OP_BUFFER_COMMIT = 0x05
OP_SAVE_FLASH = 0x09
OP_DIRECT_COLOR = 0x13
OP_POLLING = 0x17
OP_RESTART_LIGHTING = 0x18
OP_BUTTONS = 0x19
OP_WHEEL = 0x1A
OP_PROFILE_RESET = 0x1B
OP_ELEMENT_INFO = 0x1C
OP_DEBOUNCE = 0x1E
OP_CPI_TABLE = 0x20
OP_POWER = 0x2B
OP_CPI_ACTIVE = 0x16
OP_BATTERY = 0xAA
OP_VERSION = 0x10
OP_RADIO_STATUS = 0x28
OP_PAIR = 0x31
OP_WIRELESS_RESET = 0x33

# Event-channel codes (spec 2.4)
EVENT_CPI_CHANGED = 0x16
EVENT_LINK = 0x28
EVENT_BATTERY = 0x2A

# Radio status (spec 1.4)
RADIO_UNLINKED = (0, 1)
RADIO_LINKED = 4
RADIO_BLUETOOTH = 5

BATTERY_UNKNOWN = 101

LIGHTING_SLOT = 0xFF10
EFFECT_RECORD_LEN = 92
BUFFER_CHUNK = 48


def command(opcode, *data):
    """Build a 64-byte command payload, zero-padded (spec 2.1)."""
    payload = bytes([opcode]) + bytes(data)
    if len(payload) > REPORT_LEN:
        raise ValueError("command longer than one report")
    return payload.ljust(REPORT_LEN, b"\0")


def u16(value):
    return value.to_bytes(2, "little")


def u32(value, signed=False):
    return value.to_bytes(4, "little", signed=signed)


def le16(data, offset):
    return int.from_bytes(data[offset:offset + 2], "little")


# --- CPI (spec 3.1) ---

CPI_MIN = 100
CPI_MAX = 18000
CPI_STEP = 100
CPI_MAX_PRESETS = 5

# Table 3.1-A: index i holds the sensor code for (i + 1) * 100 CPI.
_CPI_CODES = (
    0x00, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x09, 0x0A, 0x0B, 0x0C, 0x0D,
    0x0E, 0x10, 0x11, 0x12, 0x13, 0x14, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B,
    0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x23, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A,
    0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x32, 0x33, 0x34, 0x35, 0x36, 0x38, 0x39,
    0x3A, 0x3B, 0x3C, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x44, 0x45, 0x46, 0x47,
    0x48, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x50, 0x51, 0x52, 0x53, 0x54, 0x56,
    0x57, 0x58, 0x59, 0x5A, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x62, 0x63, 0x64,
    0x65, 0x66, 0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6E, 0x6F, 0x70, 0x71, 0x72,
    0x74, 0x75, 0x76, 0x77, 0x78, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x80, 0x81,
    0x82, 0x83, 0x84, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8C, 0x8D, 0x8E, 0x8F,
    0x90, 0x92, 0x93, 0x94, 0x95, 0x96, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9E,
    0x9F, 0xA0, 0xA1, 0xA2, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xAA, 0xAB, 0xAC,
    0xAD, 0xAE, 0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9,
    0xBA, 0xBB, 0xBC, 0xBD, 0xBF, 0xC0, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3, 0xD5, 0xD6,
)
_CODE_TO_CPI = {code: (i + 1) * CPI_STEP for i, code in enumerate(_CPI_CODES)}


def cpi_to_code(cpi):
    if cpi % CPI_STEP or not CPI_MIN <= cpi <= CPI_MAX:
        raise ValueError(f"CPI must be {CPI_MIN}..{CPI_MAX} in steps of {CPI_STEP}")
    return _CPI_CODES[cpi // CPI_STEP - 1]


def code_to_cpi(code):
    if code in _CODE_TO_CPI:
        return _CODE_TO_CPI[code]
    return max(CPI_MIN, CPI_STEP * int(code * 0.8))


@dataclass
class CpiTable:
    presets: list  # CPI values, ascending
    active: int  # 1-based index into presets

    @property
    def active_cpi(self):
        return self.presets[self.active - 1]


def make_cpi_table(presets, active_cpi):
    """Normalise presets the way GG does: distinct, sorted ascending (spec 3.1)."""
    values = sorted(set(presets))
    if not 1 <= len(values) <= CPI_MAX_PRESETS:
        raise ValueError(f"need 1..{CPI_MAX_PRESETS} distinct CPI presets")
    for value in values:
        cpi_to_code(value)
    if active_cpi not in values:
        raise ValueError("active CPI must be one of the presets")
    return CpiTable(values, values.index(active_cpi) + 1)


def encode_cpi_table(table):
    data = [len(table.presets), table.active]
    codes = [cpi_to_code(cpi) for cpi in table.presets]
    codes += [0] * (CPI_MAX_PRESETS - len(codes))
    payload = bytes(data) + b"".join(u16(code) for code in codes)
    return command(OP_CPI_TABLE, *payload)


def decode_cpi_table(r):
    count, active = r[0], r[1]
    if count == 0 or active == 0 or le16(r, 2) == 0:
        raise ValueError("invalid CPI table response")
    count = min(count, CPI_MAX_PRESETS)
    presets = [code_to_cpi(le16(r, 2 + 2 * i)) for i in range(count)]
    return CpiTable(presets, min(active, count))


# --- CPI with X/Y codes, Rival 3 Wireless Gen 2 (survey C.1) ---

OP_CPI_TABLE_XY = 0x2C


def encode_cpi_table_xy(table):
    """[0x2C, count, active, X codes x5, Y codes x5], one byte per code.

    Mousework has one value per preset, so X and Y are always equal. Unused
    slots are 0, as for the Rival 3 Wireless (survey S3 leaves this open).
    """
    codes = [cpi_to_code(cpi) for cpi in table.presets]
    codes += [0] * (CPI_MAX_PRESETS - len(codes))
    return command(OP_CPI_TABLE_XY, len(table.presets), table.active, *codes, *codes)


def decode_cpi_table_xy(r):
    """R[0] count, R[1] active (1-based), R[2..6] X codes, R[7..11] Y codes.

    A preset set elsewhere with different X and Y is reported by its X value.
    """
    count, active = r[0], r[1]
    if count == 0 or active == 0:
        raise ValueError("invalid CPI table response")
    count = min(count, CPI_MAX_PRESETS)
    presets = [code_to_cpi(r[2 + i]) for i in range(count)]
    return CpiTable(presets, min(active, count))


# --- Polling rate (spec 3.2) ---

POLLING_LEVELS = {0: 1000, 1: 500, 2: 250, 3: 125}
POLLING_HZ = {hz: level for level, hz in POLLING_LEVELS.items()}


def encode_polling(hz):
    if hz not in POLLING_HZ:
        raise ValueError("polling rate must be one of 125, 250, 500, 1000")
    return command(OP_POLLING, POLLING_HZ[hz])


# --- Power management (spec 3.3) ---

SLEEP_MIN_S = 60
SLEEP_MAX_S = 1200
SMART_ILLUMINATION_ON = 100


@dataclass
class PowerSettings:
    high_efficiency: bool = False
    movement_saving: int = 50
    idle_lighting_s: int = 300
    idle_sleep_s: int = 300

    @property
    def smart_illumination(self):
        return self.movement_saving != 0


def encode_power(p):
    if not SLEEP_MIN_S <= p.idle_sleep_s <= SLEEP_MAX_S:
        raise ValueError("sleep timer must be 1..20 minutes")
    return command(OP_POWER, int(p.high_efficiency), p.movement_saving,
                   *u16(p.idle_lighting_s), *u16(p.idle_sleep_s))


def decode_power(r):
    return PowerSettings(bool(r[0]), r[1], le16(r, 2), le16(r, 4))


# --- Battery and versions (spec 5, spec 6.1) ---

@dataclass
class Battery:
    level: int  # percent, or BATTERY_UNKNOWN
    status: int  # 0 discharging, 1 charging, 2 charged

    @property
    def known(self):
        return self.level != BATTERY_UNKNOWN


def decode_battery(r):
    return Battery(le16(r, 0), r[2])


def decode_version(r):
    return f"{r[0]}.{r[1]:02d}"


# --- Buttons (spec 3.5) ---

BUTTON_NAMES = ("left", "right", "middle", "back", "forward", "cpi")
WHEEL_NAMES = ("wheel-up", "wheel-down")
BUTTON_SLOTS = 7

FN_DISABLED = 0x00
FN_CPI_CYCLE = 0x30
FN_WHEEL_UP = 0x31
FN_WHEEL_DOWN = 0x32
FN_KEYBOARD = 0x51
FN_MEDIA = 0x61

MOUSE_BUTTON_ACTIONS = {
    "left": 0x01, "right": 0x02, "middle": 0x03,
    "back": 0x04, "forward": 0x05, "button6": 0x06,
}

MEDIA_KEYS = {
    "mute": 0xE2, "next": 0xB5, "previous": 0xB6,
    "play-pause": 0xCD, "volume-up": 0xE9, "volume-down": 0xEA,
}

# USB HID keyboard page usages (public HID Usage Tables)
MODIFIER_KEYS = {
    "ctrl": 0xE0, "shift": 0xE1, "alt": 0xE2, "super": 0xE3,
    "rctrl": 0xE4, "rshift": 0xE5, "ralt": 0xE6, "rsuper": 0xE7,
}
KEYS = {chr(ord("a") + i): 0x04 + i for i in range(26)}
KEYS.update({str((i + 1) % 10): 0x1E + i for i in range(10)})
KEYS.update({f"f{i + 1}": 0x3A + i for i in range(12)})
KEYS.update({
    "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "equal": 0x2E, "leftbracket": 0x2F, "rightbracket": 0x30,
    "backslash": 0x31, "semicolon": 0x33, "apostrophe": 0x34, "grave": 0x35,
    "comma": 0x36, "period": 0x37, "slash": 0x38, "capslock": 0x39,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49,
    "home": 0x4A, "pageup": 0x4B, "delete": 0x4C, "end": 0x4D,
    "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
})
KEYS.update({f"f{i + 13}": 0x68 + i for i in range(12)})
_USAGE_TO_KEY = {v: k for k, v in {**KEYS, **MODIFIER_KEYS}.items()}


@dataclass(frozen=True)
class Binding:
    function: int
    keys: tuple = (0, 0, 0, 0)

    def encode(self):
        return bytes([self.function, *self.keys])


DISABLED = Binding(FN_DISABLED)

DEFAULT_BUTTONS = {
    "left": Binding(0x01), "right": Binding(0x02), "middle": Binding(0x03),
    "back": Binding(0x04), "forward": Binding(0x05), "cpi": Binding(FN_CPI_CYCLE),
}
DEFAULT_WHEEL = {"wheel-up": Binding(FN_WHEEL_UP), "wheel-down": Binding(FN_WHEEL_DOWN)}


def parse_action(text):
    """Parse an action string such as 'back', 'cpi', 'key:ctrl+c', 'media:mute'."""
    text = text.strip().lower()
    if text in ("disabled", "none", "off"):
        return DISABLED
    if text in MOUSE_BUTTON_ACTIONS:
        return Binding(MOUSE_BUTTON_ACTIONS[text])
    if text in ("cpi", "cpi-cycle"):
        return Binding(FN_CPI_CYCLE)
    if text == "wheel-up":
        return Binding(FN_WHEEL_UP)
    if text == "wheel-down":
        return Binding(FN_WHEEL_DOWN)
    if text.startswith("media:"):
        name = text[6:]
        if name not in MEDIA_KEYS:
            raise ValueError(f"unknown media key {name!r}")
        return Binding(FN_MEDIA, (MEDIA_KEYS[name], 0, 0, 0))
    if text.startswith("key:"):
        parts = [p for p in text[4:].split("+") if p]
        mods = [MODIFIER_KEYS[p] for p in parts if p in MODIFIER_KEYS]
        keys = [KEYS[p] for p in parts if p in KEYS and p not in MODIFIER_KEYS]
        unknown = [p for p in parts if p not in KEYS and p not in MODIFIER_KEYS]
        if unknown:
            raise ValueError(f"unknown key {unknown[0]!r}")
        if len(keys) > 1 or len(mods) > 3 or not parts:
            raise ValueError("a key binding is up to 3 modifiers plus 1 key")
        # Modifiers first (spec 3.5 marks this order as inferred).
        usages = mods + keys
        return Binding(FN_KEYBOARD, tuple(usages + [0] * (4 - len(usages))))
    raise ValueError(f"unknown action {text!r}")


def format_action(binding):
    fn = binding.function
    if fn == FN_DISABLED:
        return "disabled"
    for name, code in MOUSE_BUTTON_ACTIONS.items():
        if fn == code:
            return name
    if fn == FN_CPI_CYCLE:
        return "cpi"
    if fn == FN_WHEEL_UP:
        return "wheel-up"
    if fn == FN_WHEEL_DOWN:
        return "wheel-down"
    if fn == FN_MEDIA:
        for name, code in MEDIA_KEYS.items():
            if binding.keys[0] == code:
                return f"media:{name}"
    if fn == FN_KEYBOARD:
        names = [_USAGE_TO_KEY.get(u, f"0x{u:02x}") for u in binding.keys if u]
        return "key:" + "+".join(names)
    return f"raw:0x{fn:02x}"


def encode_buttons(buttons):
    slots = [buttons.get(name, DEFAULT_BUTTONS[name]) for name in BUTTON_NAMES]
    slots += [DISABLED] * (BUTTON_SLOTS - len(slots))
    return command(OP_BUTTONS, *b"".join(b.encode() for b in slots))


def encode_wheel(wheel):
    slots = [wheel.get(name, DEFAULT_WHEEL[name]) for name in WHEEL_NAMES]
    return command(OP_WHEEL, *b"".join(b.encode() for b in slots))


# --- Lighting (spec 3.4) ---

EFFECT_STEADY = "steady"
EFFECT_SHIFT = "shift"
EFFECT_BREATHE = "breathe"
EFFECT_REACTIVE = "reactive"
EFFECT_OFF = "off"
MAX_COLOR_STOPS = 14
MAX_SECTIONS = 16

OVERFLOW_WRAP = 0
OVERFLOW_HOLD = 1


@dataclass
class ColorStop:
    color: tuple  # (r, g, b)
    position: int  # 0..100 percent


@dataclass
class Lighting:
    effect: str = EFFECT_SHIFT
    stops: list = field(default_factory=lambda: [
        ColorStop((255, 55, 0), 0), ColorStop((0, 0, 0), 50), ColorStop((255, 55, 0), 99),
    ])
    speed: int = 1000
    steady_color: tuple = (255, 55, 0)
    reactive_color: tuple = (255, 255, 255)
    reactive_time: int = 500
    trigger_mask: int = 7


def _section_len(delta):
    """spec 3.4.3 R0: truncate, do not round (so 100 % gives 254)."""
    return max(0, min(255, int(delta * 2.55)))


def _min_speed(stops):
    return 66 * len(stops)  # spec 3.4.3 R1


def _sections(lighting):
    """Return (start_colour, sections, overflow, duration, trigger_mask)."""
    if lighting.effect == EFFECT_OFF:
        black = (0, 0, 0)
        return black, [(black, 0)], OVERFLOW_HOLD, lighting.speed * 10, 0
    if lighting.effect == EFFECT_STEADY:
        c = lighting.steady_color
        return c, [(c, 0)], OVERFLOW_HOLD, lighting.speed * 10, 0
    if lighting.effect == EFFECT_REACTIVE:
        sections = [(lighting.reactive_color, 0), (lighting.steady_color, 255)]
        return (lighting.reactive_color, sections, OVERFLOW_HOLD,
                lighting.reactive_time * 10, lighting.trigger_mask)

    stops = sorted(lighting.stops, key=lambda s: s.position)
    if not 1 <= len(stops) <= MAX_COLOR_STOPS:
        raise ValueError(f"need 1..{MAX_COLOR_STOPS} colour stops")
    if lighting.effect == EFFECT_SHIFT:
        speed = max(lighting.speed, _min_speed(stops))
        sections, prev = [], 0
        for stop in stops:
            sections.append((stop.color, _section_len(stop.position - prev)))
            prev = stop.position
        sections.append((stops[0].color, _section_len(100 - prev)))
        return stops[0].color, sections, OVERFLOW_WRAP, speed * 10, 0
    if lighting.effect == EFFECT_BREATHE:
        # spec 3.4.3: colour/black pairs, gaps halved with integer division (R0b)
        speed = max(lighting.speed, _min_speed(stops))
        positions = [s.position for s in stops]
        sections, prev = [], 0
        for i, stop in enumerate(stops):
            nxt = positions[i + 1] if i + 1 < len(stops) else 100
            sections.append((stop.color, _section_len(stop.position - (prev + (stop.position - prev) // 2))))
            sections.append(((0, 0, 0), _section_len((nxt - stop.position) // 2)))
            prev = stop.position
        last = positions[-1]
        sections.append((stops[0].color, _section_len(100 - (last + (100 - last) // 2))))
        if len(sections) > MAX_SECTIONS:
            raise ValueError("breathe supports at most 7 colours")
        return stops[0].color, sections, OVERFLOW_WRAP, speed * 10, 0
    raise ValueError(f"unknown effect {lighting.effect!r}")


def encode_effect_record(lighting):
    """Build the 92-byte stored-effect record (spec 3.4.2). Waves are not used."""
    start, sections, overflow, duration, mask = _sections(lighting)
    if len(sections) > MAX_SECTIONS:
        raise ValueError("too many lighting sections")
    record = bytearray(EFFECT_RECORD_LEN)
    record[0:4] = u32(duration)
    record[16] = overflow
    record[20:24] = u32(mask)
    record[24] = len(sections)
    record[25:28] = bytes(start)
    for i, (color, length) in enumerate(sections):
        record[28 + 4 * i:32 + 4 * i] = bytes([*color, length])
    return bytes(record)


def encode_effect_upload(record):
    """Commands to upload and commit an effect record, then bind it (spec 3.4.1)."""
    cmds = []
    for offset in range(0, len(record), BUFFER_CHUNK):
        chunk = record[offset:offset + BUFFER_CHUNK]
        cmds.append(command(OP_BUFFER_WRITE, 0, *u16(offset), *u16(len(chunk)), *chunk))
    cmds.append(command(OP_BUFFER_COMMIT, 0, *u16(LIGHTING_SLOT), *u32(0), *u16(len(record))))
    cmds.append(command(OP_ELEMENT_INFO, 0, *u16(85), *u16(270), 1))
    return cmds


def encode_direct_color(rgb):
    return command(OP_DIRECT_COLOR, 0x01, *rgb)

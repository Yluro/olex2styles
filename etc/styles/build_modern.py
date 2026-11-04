"""Generate the modern and Flexoki Olex2 3D styles and GUI skins from light_g."""
# Olex2 ships a 3D drawing style called light_g (light_g.glds, plus its scene
# file light_g.glsp). This script reads that pair as a template and writes:
#
#   etc/styles  modern, modern_dark, flexoki_light, flexoki_dark   (.glds + .glsp)
#   etc/skins   modern*, moderndark*, flexokilight*, flexokidark*  (.phil, 20 skins)
#
# What changes against light_g:
#   - Atom colours. C, H, N, O, F, Cl and S keep their light_g colour; the
#     d-block, lanthanide and main-group metals get a new palette, designed in
#     OKLCH so metals stay apart from each other and from the ligand atoms.
#   - Materials. One finish for every atom (satin, matte or glossy); a few
#     metals look polished and iridium iridescent.
#   - Background, overlay text, console colours and label fonts follow the theme.
#
# The generated files are the deliverable: edit the palettes here and re-run,
# never the .glds/.glsp/.phil by hand. Standard library only.
#
#   python build_modern.py                  write every style and skin
#   python build_modern.py --finish matte   other sphere finish (satin, matte, glossy)
#   python build_modern.py --rims neutral   other rim colouring (dark, neutral, keep)
#   python build_modern.py --report         print palette checks, write nothing
#
# The Flexoki themes use Steph Ango's Flexoki palette (stephango.com/flexoki).
import argparse
import math
import os
import re

# Folder of this script (etc/styles). Inputs are read from and outputs are
# written to here; the skins go to the sibling folder etc/skins.
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- XL format --
# Olex2 stores styles in a small XML-like format of its own ("XL"). An item
# opens with "<Name", lists fields and child items, and closes with ">":
#
#     <Name key="value" "unnamed value" bare.ref <Child ...> ... >
#
# Fields are kept as raw text (quotes included) so that a file read and written
# back out without changes comes out the same.


class Item:
    """One <Name ...> element of an XL file."""

    def __init__(self, name, fields=None, children=None):
        self.name = name
        # list of (key, raw) pairs; key is None for an unnamed value, and raw
        # is the text exactly as in the file, quotes included
        self.fields = fields or []
        self.children = children or []

    def get(self, key, default=None):
        """Value of the named field, without quotes."""
        for k, v in self.fields:
            if k == key:
                return unquote(v)
        return default

    def set(self, key, value):
        """Set (or add) a named field; the value is written in double quotes."""
        raw = '"%s"' % value
        for i, (k, _) in enumerate(self.fields):
            if k == key:
                self.fields[i] = (k, raw)
                return
        self.fields.append((key, raw))

    @property
    def value(self):
        """The first unnamed value, without quotes (e.g. a material string)."""
        for k, v in self.fields:
            if k is None:
                return unquote(v)
        return None

    def child(self, name):
        """First child item with this name, or None."""
        for c in self.children:
            if c.name == name:
                return c
        return None


def unquote(raw):
    """Strip one pair of matching single or double quotes, if present."""
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def parse_xl(text):
    """Parse XL text into a list of top-level Items."""
    pos = 0
    n = len(text)

    def skip_ws():
        nonlocal pos
        # "﻿" is the UTF-8 byte order mark some Olex2 files start with
        while pos < n and text[pos] in " \t\r\n﻿":
            pos += 1

    def read_quoted():
        # returns the quoted string with its quotes; backslash escapes the
        # next character
        nonlocal pos
        q = text[pos]
        start = pos
        pos += 1
        while pos < n and text[pos] != q:
            pos += 2 if text[pos] == "\\" else 1
        pos += 1
        return text[start:pos]

    def read_token():
        # a bare word: a name, a key or an unquoted value
        nonlocal pos
        start = pos
        while pos < n and text[pos] not in " \t\r\n<>=\"'":
            pos += 1
        return text[start:pos]

    def read_item():
        nonlocal pos
        assert text[pos] == "<", text[pos:pos + 40]
        pos += 1
        it = Item(read_token())
        while True:
            skip_ws()
            c = text[pos]
            if c == ">":                      # end of this item
                pos += 1
                return it
            if c == "<":                      # nested child item
                it.children.append(read_item())
            elif c in "\"'":                  # unnamed quoted value
                it.fields.append((None, read_quoted()))
            else:                             # key=value, or a bare word
                key = read_token()
                skip_ws()
                if pos < n and text[pos] == "=":
                    pos += 1
                    skip_ws()
                    val = read_quoted() if text[pos] in "\"'" else read_token()
                    it.fields.append((key, val))
                else:
                    it.fields.append((None, key))

    items = []
    skip_ws()
    while pos < n:
        items.append(read_item())
        skip_ws()
    return items


def write_xl(item, indent=0):
    """Serialise an Item back to XL text, one child per line, indented by one space."""
    pad = " " * indent
    head = pad + "<" + item.name + "".join(
        " " + (v if k is None else "%s=%s" % (k, v)) for k, v in item.fields)
    if not item.children:
        return head + ">"
    body = "\n".join(write_xl(c, indent + 1) for c in item.children)
    return head + "\n" + body + "\n" + pad + ">"


# ------------------------------------------------------------------ colours --
# Colours are handled as (r, g, b) tuples of floats in 0..1 (sRGB).
# Olex2 packs a colour into one uint32 as 0xAABBGGRR: red in the low byte,
# alpha in the high byte. These numbers are what appear in the material strings.

def pack(rgb, a=1.0):
    """(r, g, b) floats and alpha -> Olex2 uint32 colour."""
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb)
    return r | (g << 8) | (b << 16) | (max(0, min(255, round(a * 255))) << 24)


def unpack(v):
    """Olex2 uint32 colour (int or decimal string) -> (r, g, b) floats; alpha is dropped."""
    v = int(v)
    return (v & 255) / 255, ((v >> 8) & 255) / 255, ((v >> 16) & 255) / 255


def hex_rgb(h):
    """'#RRGGBB' -> (r, g, b) floats."""
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_hex(rgb):
    """(r, g, b) floats -> '#RRGGBB'."""
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


# OKLab / OKLCH (Björn Ottosson, https://bottosson.github.io/posts/oklab/) is a
# perceptual colour space: equal steps in L (lightness), C (chroma) and h (hue
# angle in degrees) look about equally large. The palettes below are written in
# it so lightness and saturation can be balanced across elements by eye.

def _lin(c):
    """sRGB channel -> linear light."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    """Linear light -> sRGB channel."""
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def oklab(rgb):
    """sRGB (r, g, b) -> OKLab (L, a, b)."""
    r, g, b = (_lin(c) for c in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklch_raw(L, C, h):
    """OKLCH -> linear RGB, unclipped (may fall outside 0..1)."""
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def oklch(L, C, h):
    """OKLCH -> sRGB, reducing chroma until the colour is in gamut."""
    def in_gamut(c):
        return all(-1e-6 <= v <= 1 + 1e-6 for v in _oklch_raw(L, c, h))
    if not in_gamut(C):
        # bisect for the highest chroma that still fits, keeping L and h
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if in_gamut(mid) else (lo, mid)
        C = lo
    return tuple(_gam(max(0.0, min(1.0, v))) for v in _oklch_raw(L, C, h))


def de_ok(c1, c2):
    """Perceptual distance of two sRGB colours (Euclidean in OKLab)."""
    return math.dist(oklab(c1), oklab(c2))


def scale(rgb, k):
    """Multiply every channel by k (darken for k < 1)."""
    return tuple(c * k for c in rgb)


def mix(c1, c2, t):
    """Linear blend: t = 0 gives c1, t = 1 gives c2."""
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))


# ------------------------------------------------------------------ palette --
# Atom colours, by element symbol. Values are "#RRGGBB" or (L, C, h) in OKLCH:
# L lightness 0..1, C chroma (0 = grey, ~0.2 = vivid), h hue angle in degrees.
# Elements in none of these tables keep their light_g colour.

# d-block and main-group values were tuned so that metals stay apart from each
# other, from the lanthanides and from the ligand atoms (N, O, P, Cl, C ...)
D_BLOCK = {
    # 3d: mid lightness, vivid; anchors Fe/Co/Ni/Cu kept chemist-familiar
    "Sc": (0.62, 0.113, 223), "Ti": (0.58, 0.012, 243), "V": (0.59, 0.166, 310),
    "Cr": (0.61, 0.123, 169), "Mn": (0.58, 0.169, 349), "Fe": (0.49, 0.137, 34),
    "Co": (0.55, 0.183, 265), "Ni": (0.63, 0.180, 135), "Cu": (0.70, 0.100, 52),
    "Zn": (0.66, 0.087, 291),
    # 4d: light pastels; Ag and Pd cool silvers, Ru the "ruthenium red" stain,
    # Cd vivid cadmium-pigment orange
    "Y": (0.82, 0.109, 203), "Zr": (0.80, 0.085, 250), "Nb": (0.76, 0.112, 303),
    "Mo": (0.74, 0.100, 178), "Tc": (0.76, 0.115, 345), "Ru": (0.48, 0.170, 10),
    "Rh": (0.72, 0.097, 264), "Pd": (0.75, 0.025, 240), "Ag": (0.86, 0.032, 246),
    "Cd": (0.68, 0.200, 45),
    # 5d: deep tones; Ta and W blackish gunmetal, Pt warm silver, Au gold,
    # Hg dark liquid metal (a light silver reads as C next to methyls), Os silvery blue
    "Hf": (0.47, 0.050, 245), "Ta": (0.34, 0.040, 280), "W": (0.37, 0.020, 200),
    "Re": (0.47, 0.130, 355), "Os": (0.70, 0.070, 245), "Ir": (0.40, 0.130, 265),
    "Pt": (0.77, 0.015, 90), "Au": (0.75, 0.150, 76), "Hg": (0.54, 0.015, 220),
}

LANTHANIDES = ["La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
               "Ho", "Er", "Tm", "Yb", "Lu"]
# each colour follows a salt, mineral, name or property of the element
LN_PALETTE = {
    "La": (0.78, 0.06, 65),    # La2O3 white, "lanthanein" = to lie hidden: pearl
    "Ce": (0.68, 0.17, 62),    # ceric ammonium nitrate / Ce(IV) orange
    "Pr": (0.62, 0.11, 122),   # Pr3+ salts, "prasios" = leek green
    "Nd": (0.72, 0.11, 318),   # Nd3+ salts lilac in daylight
    "Pm": (0.80, 0.09, 5),     # Pm3+ salts pink
    "Sm": (0.42, 0.15, 285),   # SmI2 (Kagan's reagent) indigo
    "Eu": (0.64, 0.19, 32),    # Eu3+ red emission (~612 nm)
    "Gd": (0.66, 0.11, 198),   # Gd(III) MRI contrast agents: clinical teal
    "Tb": (0.80, 0.19, 130),   # Tb3+ green emission (~545 nm)
    "Dy": (0.86, 0.07, 88),    # Dy2O3 light sand yellow
    "Ho": (0.50, 0.13, 245),   # Holmia = Stockholm: Stockholm blue
    "Er": (0.68, 0.14, 355),   # Er2O3 / Er3+ salts rose
    "Tm": (0.68, 0.14, 240),   # Tm3+ blue emission (~480 nm), with Eu/Tb the RGB trio
    "Yb": (0.70, 0.14, 25),    # Yb3+ near-IR emission: salmon-red
    "Lu": (0.62, 0.06, 248),   # Lutetia = Paris: zinc-roof grey-blue
}

MAIN_GROUP_METALS = {
    "Al": (0.80, 0.093, 9), "Ga": (0.66, 0.084, 69), "In": (0.58, 0.080, 10),
    "Tl": (0.56, 0.034, 103), "Ge": (0.66, 0.060, 160), "Sn": (0.55, 0.052, 236),
    "Pb": (0.42, 0.030, 265), "Sb": (0.66, 0.081, 346), "Bi": (0.48, 0.130, 325),
}

# s-block metals recoloured; the rest of the s-block keeps its light_g colour
S_BLOCK = {
    "Be": (0.85, 0.120, 140),  # soft green like Mg and Ca, instead of light_g's He cyan
}

# every reworked metal colour in one lookup
PALETTE = {**D_BLOCK, **LN_PALETTE, **MAIN_GROUP_METALS, **S_BLOCK}

# light_g materials copied unchanged: the organic and ligand atoms everyone
# already recognises
KEEP = {"C", "H", "N", "O", "F", "Cl", "S"}
# brightness factor for kept spheres: C a touch greyer so H stands out
KEEP_SHADE = {"C": 0.82}
# OKLCH hue shift (degrees) for kept spheres: F a tad greener so it parts from S
KEEP_HUE = {"F": 10}

# non-metals recoloured away from their light_g hue (otherwise light_g's is used)
NONMETALS = {
    "Br": (0.40, 0.14, 22),    # liquid Br2 deep red, instead of light_g brown
    "I": (0.40, 0.16, 322),    # iodine-vapour violet, instead of light_g's dark magenta
    "Si": (0.80, 0.07, 70),    # light beige, instead of light_g olive
}


def keep_tint(name, c):
    """Apply KEEP_SHADE and KEEP_HUE to a colour of a kept element."""
    c = scale(c, KEEP_SHADE.get(name, 1.0))
    dh = KEEP_HUE.get(name, 0)
    if dh:
        L, a, b = oklab(c)
        c = oklch(L, math.hypot(a, b), math.degrees(math.atan2(b, a)) + dh)
    return c

# metals rendered with the glossier metallic recipe
METALLIC = {"Cu", "Ag", "Au", "Pt", "Pd", "Rh", "Ir", "Os", "Ru", "Hg", "Re",
            "Ta", "W"}

# fake thin-film sheen: GL adds the terms in sRGB, so the shaded limb shows
# ~0.34*ambient, the lit centre ~0.34*ambient + 0.92*diffuse and the highlight
# adds specular on top; three hues then drift across the sphere.
# (ambient, diffuse, specular, shininess) - Ir: violet limb, teal body, gold glint
IRIDESCENT = {
    "Ir": ("#D95EFF", "#008F5E", "#FF9900", 40),
}

# s-block metals (alkali and alkaline earth) and actinides keep their light_g
# colour; they are listed only so METALS knows they get a coordination polyhedron
ALKALI = {"Li", "Na", "K", "Rb", "Cs", "Fr", "Be", "Mg", "Ca", "Sr", "Ba", "Ra"}
ACTINIDES = {"Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es",
             "Fm", "Md", "No", "Lr"}
# elements that get a translucent "Polyhedron" material
METALS = set(D_BLOCK) | set(LANTHANIDES) | set(MAIN_GROUP_METALS) | ALKALI | ACTINIDES

# element style entries; any other style entry (Labels, Background, ...) is an
# overlay or scene object. D is deuterium.
ELEMENTS = set("""H D He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V
Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn
Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir
Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No
Lr""".split())

# --------------------------------------------------------------- materials --
# An Olex2 material is a ";"-separated string of decimal numbers:
#
#     Flags;AmbF;AmbB;DifF;DifB;SpcF;SpcB;ShnF;ShnB;EmsF;EmsB
#
# F/B = front/back face. Only the fields whose flag bit is set are present, in
# this order. Flag bits:
#
#     0x001 / 0x002  ambient   front / back      0x100 / 0x200  emission
#     0x004 / 0x008  diffuse   front / back      0x400          transparent
#     0x010 / 0x020  specular  front / back      0x800          identity draw
#     0x040 / 0x080  shininess front / back                     (overlays, no transform)
#
# So 85 = 0x55 is a plain front-lit material, 1109 = 85 + transparent.
# Colours are packed uint32 (see pack); shininess is a plain number.
WHITE = (1.0, 1.0, 1.0)


def mat(amb, dif, spc, shn, alpha=1.0, transparent=False):
    """Front material string from ambient, diffuse and specular colours and a shininess."""
    flags = 0x55 | (0x400 if transparent else 0)
    # transparency is carried by the diffuse alpha
    return "%d;%d;%d;%d;%d" % (flags, pack(amb), pack(dif, alpha), pack(spc), shn)


# Sphere finishes for --finish. The ambient and diffuse factors darken the
# element colour; the specular highlight is a grey, so it never tints the atom.
FINISHES = {
    # (ambient k, diffuse k, specular grey, shininess)
    "satin": (0.85, 0.90, 0.30, 16),
    "matte": (0.88, 0.92, 0.04, 4),
    "glossy": (0.82, 0.85, 0.75, 80),
}


def sphere_mat(c, metallic, finish):
    """Atom sphere material for colour c."""
    ka, kd, ks, shn = FINISHES[finish]
    if metallic and finish != "matte":
        # tinted, tighter highlight reads as polished metal
        spc = mix(c, WHITE, 0.55)
        return mat(scale(c, 0.75), scale(c, 0.82), spc, 48)
    return mat(scale(c, ka), scale(c, kd), (ks,) * 3, shn)


def rim_mat(c, rims):
    """Material of the rings drawn around an atom sphere (--rims dark or neutral)."""
    if rims == "neutral":
        # dark grey on light atoms, light grey on dark ones
        g = (0.23, 0.24, 0.26) if oklab(c)[0] > 0.55 else (0.80, 0.81, 0.83)
        return mat(g, g, (0.0,) * 3, 1)
    # "dark": a deeper shade of the atom's own colour
    return mat(scale(c, 0.45), scale(c, 0.40), (0.05,) * 3, 4)


def poly_mat(c, finish):
    """Translucent coordination polyhedron material for a metal of colour c."""
    ka, kd, ks, shn = FINISHES[finish]
    return mat(scale(c, ka), scale(c, kd), (ks,) * 3, shn, alpha=0.55,
               transparent=True)


def iridescent_mat(spec, alpha=1.0):
    """Material from an IRIDESCENT entry; alpha < 1 makes it a translucent polyhedron."""
    amb, dif, spc, shn = spec
    return mat(hex_rgb(amb), hex_rgb(dif), hex_rgb(spc), shn, alpha=alpha,
               transparent=alpha < 1)


def retint(m, f):
    """Map the front ambient and diffuse colours of a material through f, keeping alpha."""
    t = m.split(";")
    flags = int(t[0])
    # field positions: front ambient is t[1] when present; front diffuse comes
    # after however many ambient fields (front, back) are present
    idx = ([1] if flags & 0x1 else []) + (
        [1 + bool(flags & 0x1) + bool(flags & 0x2)] if flags & 0x4 else [])
    for i in idx:
        v = int(t[i])
        # new RGB, original alpha byte
        t[i] = str(pack(f(unpack(v))) & 0xFFFFFF | v & 0xFF000000)
    return ";".join(t)


def recolour(m, c):
    """Set the front ambient and diffuse colours of a material, fully opaque."""
    t = m.split(";")
    flags = int(t[0])
    # same field positions as in retint
    if flags & 0x1:
        t[1] = str(pack(c))
    if flags & 0x4:  # text is drawn with the diffuse colour
        t[1 + bool(flags & 0x1) + bool(flags & 0x2)] = str(pack(c))
    return ";".join(t)


# One entry per 3D style written (the key is the file name). Fields:
#   bg                 flat background, the .glsp LightModel ClearColor
#   bg_top, bg_bottom  background gradient corners (the "Background" style entry)
#   text               atom labels
#   text_mid           secondary overlay text (legends, grid labels, help)
#   console            console text and cursor
#   pivot              OKLab L below which atoms are lifted on dark themes (lift_shift);
#                      None = no lift
#   messages           console message colours, by message kind
#   overrides          per-element exceptions to the lift (dark themes only)
THEMES = {
    "modern": dict(bg="#E4E5E8", bg_top="#EEEFF2", bg_bottom="#DADCE0",
                   text="#262B33", text_mid="#4A505A", console="#3B5378", pivot=None,
                   messages=dict(Error="#B8362B", Exception="#B8362B", Warning="#A86A00",
                                 Info="#2B5EA8", Help_cmd="#7A6200", Help_txt="#00737A",
                                 Exec="#3B5378")),
    # charcoal like a dark-mode code editor; same as the moderndark panel
    "modern_dark": dict(bg="#2B2D31", bg_top="#313337", bg_bottom="#26282B",
                        text="#D4D7DD", text_mid="#A3A9B3", console="#8DB3E2", pivot=0.58,
                        messages=dict(Error="#FF7A6B", Exception="#FF7A6B", Warning="#F0B44C",
                                      Info="#7FB2FF", Help_cmd="#F2D35B", Help_txt="#5CD6D6",
                                      Exec="#8DB3E2"),
                        # None = no lift; otherwise the OKLCH colour to use
                        overrides={
                            "O": None,                  # stays apart from Eu red
                            "Hg": (0.50, 0.020, 220),   # lifted it reads as C
                            "Hf": (0.54, 0.060, 245),   # lifted it reads as C / Os
                            "Br": (0.52, 0.170, 15),    # apart from Fe, O and Yb
                            "Rh": (0.80, 0.080, 255),   # apart from the lifted N
                        }),
    # Flexoki (stephango.com/flexoki) behind the modern atoms: base-100, gradient
    # base-50 to base-150, text tx / base-700 / base-800; messages in 600 shades
    # (orange is Flexoki's warning colour, yellow-700 for contrast)
    "flexoki_light": dict(bg="#E6E4D9", bg_top="#F2F0E5", bg_bottom="#DAD8CE",
                          text="#100F0F", text_mid="#575653", console="#403E3C",
                          pivot=None,
                          messages=dict(Error="#AF3029", Exception="#AF3029",
                                        Warning="#BC5215", Info="#205EA6",
                                        Help_cmd="#8E6B01", Help_txt="#24837B",
                                        Exec="#403E3C")),
}
# behind the modern_dark atoms: base-900, gradient base-850 to base-950, text tx /
# base-300; messages in 300 shades, since 400 read dim on base-900
THEMES["flexoki_dark"] = dict(bg="#282726", bg_top="#343331", bg_bottom="#1C1B1A",
                              text="#CECDC3", text_mid="#B7B5AC", console="#B7B5AC",
                              pivot=THEMES["modern_dark"]["pivot"],
                              messages=dict(Error="#E8705F", Exception="#E8705F",
                                            Warning="#EC8B49", Info="#66A0C8",
                                            Help_cmd="#DFB431", Help_txt="#5ABDAC",
                                            Exec="#B7B5AC"),
                              overrides=THEMES["modern_dark"]["overrides"])


def overlays(t):
    """Overlay text colours of a theme, keyed by (style, primitive)."""
    text, mid, console = hex_rgb(t["text"]), hex_rgb(t["text_mid"]), hex_rgb(t["console"])
    return {
        ("Labels", "Text"): text,
        ("Console", "Text"): console,
        ("Cursor", "On"): console,
        ("Cursor", "Text"): console,
        ("AtomLegend", "Text"): mid,
        ("PLabels", "Text"): mid,
        ("XGrid_Label", "Text"): mid,
        ("db_label", "Text"): mid,
        ("duc_label", "Text"): mid,
        ("HelpWindow", "Text"): mid,
        ("symmlegend", "Text"): mid,
    }


def emissive_text(c):
    """Text material for bitmap labels: GL lights the raster colour, so ambient
    would arrive at only ~0.34x; emission shows the colour as is."""
    # ambient (black) + diffuse + emission, transparent, drawn as an overlay
    flags = 0x1 | 0x4 | 0x100 | 0x400 | 0x800
    return "%d;%d;%d;%d" % (flags, pack((0, 0, 0)), pack(c), pack(c))


def lift_shift(c, t, name=None):
    """OKLab L shift that reflects colours darker than the theme pivot."""
    # On a dark background, dark atoms (Ta, W, Pb ...) would vanish. A colour
    # at lightness L below the pivot moves to pivot + 0.9 * (pivot - L): it is
    # mirrored about the pivot, so dark atoms stay in the same order, just lighter.
    if name in t.get("overrides", {}):
        return 0.0
    pivot = t["pivot"]
    L = oklab(c)[0]
    if pivot is None or L >= pivot:
        return 0.0
    return pivot + (pivot - L) * 0.9 - L


def shift_l(c, dL):
    """Add dL to the OKLab lightness of c, keeping chroma and hue (capped at L 0.97)."""
    if not dL:
        return c
    L, a, b = oklab(c)
    return oklch(min(0.97, L + dL), math.hypot(a, b), math.degrees(math.atan2(b, a)))

# --------------------------------------------------------------- the build --


def build(src, finish, rims, theme):
    """Read the light_g style at src and return it restyled for one theme."""
    # A .glds file is one <style> item with two parts:
    #   Materials  a table of material strings, <Prop0 "...">, <Prop1 "..."> ...
    #   Root       style entries (one per element, plus Labels, Background ...),
    #              each listing its primitives (Sphere, Rims, Polyhedron, Text ...)
    #              and pointing at a material as "style.Materials.PropN"
    t = THEMES[theme]
    with open(src, encoding="utf-8-sig") as f:
        style = parse_xl(f.read())[0]
    props = {p.name: p.value for p in style.child("Materials").children}
    root = style.child("Root").child("SubStyles")

    def mat_of(entry, pname):
        """Material string of the primitive pname in a style entry."""
        for p in entry.children:
            if p.get("PName") == pname:
                ref = p.child("Material").value
                return props[ref.split(".")[-1]]
        return None

    def base_colour(entry):
        """light_g sphere colour of an element (its front ambient)."""
        m = mat_of(entry, "Sphere")
        return unpack(m.split(";")[1]) if m else (0.5, 0.5, 0.5)

    kept = []
    for e in root.children:
        name = e.get("Name")
        if name not in ELEMENTS and re.fullmatch(r"[A-Z][a-z]?\d+\w*", name or ""):
            continue  # leftover per-atom entry such as "Cu11"
        kept.append(e)
        if name in ELEMENTS:
            # drop per-atom overrides (C1, O5', 2_665 ...) saved from old sessions
            e.children = [c for c in e.children if c.name != "SubStyles"]
            if name in KEEP:
                # spheres stay as in light_g (optionally shaded), rims follow
                # the element colour
                c = keep_tint(name, base_colour(e))
                dL = lift_shift(c, t, name)
                c = shift_l(c, dL)
                tweaked = name in KEEP_SHADE or name in KEEP_HUE or dL
                for p in e.children:
                    m = p.child("Material")
                    if p.get("PName") == "Sphere" and tweaked:
                        m.fields = [(None, retint(props[m.value.split(".")[-1]],
                                                  lambda v: shift_l(keep_tint(name, v), dL)))]
                    elif p.get("PName") == "Rims" and rims != "keep":
                        m.fields = [(None, rim_mat(c, rims))]
                continue
            # every other element: new colour, then fresh materials
            c = PALETTE.get(name) or NONMETALS.get(name)
            c = (hex_rgb(c) if isinstance(c, str) else oklch(*c)) if c else base_colour(e)
            if t.get("overrides", {}).get(name):
                c = oklch(*t["overrides"][name])
            c = shift_l(c, lift_shift(c, t, name))
            # a matte finish has no highlight, so no sheen either
            sheen = IRIDESCENT.get(name) if finish != "matte" else None
            if sheen:
                mats = [("Sphere", iridescent_mat(sheen))]
            else:
                mats = [("Sphere", sphere_mat(c, name in METALLIC, finish))]
            if rims == "keep":
                mats.append(("Rims", mat_of(e, "Rims")))
            else:
                mats.append(("Rims", rim_mat(c, rims)))
            if name in METALS:
                mats.append(("Polyhedron", iridescent_mat(sheen, 0.55) if sheen
                             else poly_mat(c, finish)))
            # replace the entry's primitives; materials are written inline here
            # and moved into the shared table by intern() below
            e.children = [Item("S%d" % i, [("PName", '"%s"' % pn)],
                               [Item("Material", [(None, m)])])
                          for i, (pn, m) in enumerate(mats)]
        else:
            # not an element: overlay text (labels, console, legends ...)
            over = overlays(t)
            for p in e.children:
                key = (name, p.get("PName"))
                m = p.child("Material")
                if key == ("Labels", "Text") and m is not None:
                    m.fields = [(None, emissive_text(over[key]))]
                elif name == "Cursor" and m is not None:
                    # light_g's cursor is ambient-only, so it showed at ~0.34x;
                    # give it the console text's ambient + diffuse
                    c = pack(over[key])
                    m.fields = [(None, "%d;%d;%d" % (0x1 | 0x4 | 0x800, c, c))]
                elif key in over and m is not None:
                    s = props[m.value.split(".")[-1]]
                    m.fields = [(None, recolour(s, over[key]))]
        if name == "Background":
            # gradient corners: A and B at the bottom, C and D at the top
            for k, col in (("A", t["bg_bottom"]), ("B", t["bg_bottom"]),
                           ("C", t["bg_top"]), ("D", t["bg_top"])):
                e.set(k, pack(hex_rgb(col)))
    # entries are named S_0, S_1 ... in order; renumber after the removals
    for i, e in enumerate(kept):
        e.name = "S_%d" % i
    root.children = kept

    # resolve every material to its string, then rebuild a de-duplicated table
    table = {}   # material string -> "PropN"

    def intern(entry):
        """Point every Material under entry at the shared table, adding new strings."""
        for c in entry.children:
            if c.name == "Material":
                v = c.value
                s = props[v.split(".")[-1]] if v.startswith("style.Materials.") else v
                if s not in table:
                    table[s] = "Prop%d" % len(table)
                c.fields = [(None, "style.Materials." + table[s])]
            else:
                intern(c)

    intern(style.child("Root"))
    style.child("Materials").children = [
        Item(pid, [(None, '"%s"' % s)]) for s, pid in table.items()]
    return style


def native_font(pt, face, weight=400):
    """Windows wxNativeFontInfo string (LOGFONT fields)."""
    return "1;%d;%d;0;0;0;%d;0;0;0;0;3;2;1;34;%s" % (
        pt, -round(pt * 96 / 72), weight, face)


def build_scene(src, theme):
    """Read the light_g scene (.glsp: lights, fonts, console colours) and adapt it to a theme."""
    with open(src, encoding="utf-8-sig") as f:
        items = parse_xl(f.read())
    lm = next(i for i in items if i.name == "LightModel")
    lm.set("ClearColor", pack(hex_rgb(THEMES[theme]["bg"])))
    # a weak grey fill light from the lower right, so the shadow side of the
    # atoms is not flat
    fill = lm.child("Light1")
    fill.set("Enabled", "true")
    fill.set("Ambient", pack((0, 0, 0)))
    fill.set("Diffuse", pack((0.22, 0.22, 0.24)))
    fill.set("Specular", pack((0, 0, 0)))
    fill.set("Position", "40.000,-30.000,20.000,0.000")
    # console message colours: the text is lit (ambient arrives at ~0.34x), so
    # split the colour between ambient and emission to show it as is
    msgs = next(i for i in items if i.name == "Materials")
    for name, h in THEMES[theme]["messages"].items():
        c = hex_rgb(h)
        # find the entry, or append a new one and take that
        m = msgs.child(name) or msgs.children.append(Item(name)) or msgs.child(name)
        # ambient + emission, drawn as an overlay
        m.fields = [(None, '"%d;%d;%d"' % (0x1 | 0x100 | 0x800, pack(c), pack(scale(c, 0.66))))]
    fonts = next(i for i in items if i.name == "Fonts")
    face = "Segoe UI Semibold"
    # "Labels" is the font of the labels command (all atom labels at once)
    for name, pt in (("Labels", 16), ("AtomLabels", 16), ("BondLabels", 14),
                     ("AngleLabels", 14)):
        fonts.child(name).fields = [(None, '"%s"' % native_font(pt, face, 600))]
    return items


# ------------------------------------------------------------------ report --
# --report: numbers to check a palette edit by, before looking at it in Olex2.
# dE_ok is the OKLab distance (de_ok); the lower it is, the more alike two colours look.

# atoms that sit next to metals in a typical structure
LIGANDS = ["C", "H", "N", "O", "F", "Cl", "Br", "I", "S", "Se", "P", "As", "B", "Si"]


def ligand_colours():
    """Apparent light_g sphere colour (mean of ambient and diffuse)."""
    with open(os.path.join(HERE, "light_g.glds"), encoding="utf-8-sig") as f:
        style = parse_xl(f.read())[0]
    props = {p.name: p.value for p in style.child("Materials").children}
    out = {}
    for e in style.child("Root").child("SubStyles").children:
        if e.get("Name") in LIGANDS:
            for p in e.children:
                if p.get("PName") == "Sphere":
                    t = props[p.child("Material").value.split(".")[-1]].split(";")
                    f = int(t[0])
                    amb = unpack(t[1])
                    dif = unpack(t[2 + bool(f & 0x2)]) if f & 0x4 else amb
                    out[e.get("Name")] = keep_tint(e.get("Name"), mix(amb, dif, 0.5))
    for name, lch in NONMETALS.items():
        if name in out:
            out[name] = oklch(*lch)
    return out


def report():
    """Print the closest colour pairs within each reworked family."""
    def col(el):
        v = PALETTE[el]
        return hex_rgb(v) if isinstance(v, str) else oklch(*v)

    def worst(names, label, n=6):
        """Print the n most alike pairs among names."""
        pairs = sorted((de_ok(col(a), col(b)), a, b)
                       for i, a in enumerate(names) for b in names[i + 1:])
        print("%s closest pairs (dE_ok):" % label,
              ", ".join("%s/%s %.3f" % (a, b, d) for d, a, b in pairs[:n]))

    worst(list(D_BLOCK), "d-block")
    worst(LANTHANIDES, "lanthanides")
    worst(list(MAIN_GROUP_METALS), "main-group metals")
    worst(list(PALETTE), "all reworked", 10)
    common_3d = ["Mn", "Fe", "Co", "Ni", "Cu", "Zn"]
    worst(common_3d + LANTHANIDES, "3d + Ln", 6)
    bg = hex_rgb(THEMES["modern"]["bg"])
    low = sorted((de_ok(col(e), bg), e) for e in PALETTE)[:5]
    print("closest to background:", ", ".join("%s %.3f" % (e, d) for d, e in low))
    # metals against the donor/ligand atoms kept from light_g
    ligands = ligand_colours()
    pairs = sorted((de_ok(col(m), c), m, l) for m in PALETTE
                   for l, c in ligands.items())
    print("metal vs ligand atoms:",
          ", ".join("%s/%s %.3f" % (m, l, d) for d, m, l in pairs[:10]))
    print()
    # the resulting hex colours, e.g. to paste into a mock-up
    for el in list(D_BLOCK) + LANTHANIDES + list(MAIN_GROUP_METALS):
        print("  %-3s %s" % (el, rgb_hex(col(el))))


# ------------------------------------------------------------------- skins --
# GUI skins (etc/skins/*.phil) to go with the style. A skin change also pushes
# the 3D clear colour, gradient corners and label font (gui.skin.SetMaterials),
# so those come from the style values above. Skin names must not contain "_"
# (Olex2 splits "name_extension"). Generated images keep Olex2's Signika:
# their font table is built at startup, before any skin is read.

def tint_buttons(h, dark=False):
    """Link-button fill and text tinted with the hue of colour h."""
    # returns (fill, text): a pale fill with dark text on light skins, a deep
    # fill with light text on dark ones. Flexoki skins set theirs explicitly.
    L, a, b = oklab(hex_rgb(h))
    C, hue = math.hypot(a, b), math.degrees(math.atan2(b, a))
    if dark:
        return rgb_hex(oklch(0.37, C * 0.35, hue)), rgb_hex(oklch(0.84, C * 0.6, hue))
    return rgb_hex(oklch(0.93, C * 0.2, hue)), rgb_hex(oklch(L - 0.09, C * 0.85, hue))


# Two colours per skin, like the original Olex2 look (blue buttons, orange
# highlights): ui = links, link buttons and action buttons; accent = highlights
# (active tab, open section bar, pressed buttons, notices, graph fit lines).
# Each family makes one skin per accent, <family><accent>, and the plain family
# name for DEFAULT_ACCENT. Accents too close to the blue ui (purple, blue) get
# ui_alt instead. Red, yellow and green would read as result grades, so none.
# title = the sample block (.res; .cif uses green, .oxm warn) with on_accent text.
#
# Palette keys of a family:
#   theme                 the 3D style it pairs with (a THEMES key); dark=True for dark skins
#   panel, card, card_alt, header, field, tab, border
#                         surfaces: panel background, table cards, group headers,
#                         input fields, inactive tabs, outlines
#   text, text_mid, text_soft
#                         text from strongest to weakest
#   title, on_accent      sample block colour, and text drawn on coloured fills
#   good ... worst        result grades 1-5 (the coloured R1, Rint ... cells)
#   good_text, green      "good" text, and the .cif title block (defaults to good)
#   ui, ui_alt, accents   see above
#   buttons               optional {ui: (fill, text)} for link buttons; else tint_buttons
FAMILIES = {
    "modern": dict(    # light: the panel is the 3D grey, cards and tabs near-white
        theme="modern",
        panel="#E4E5E8", card="#F4F5F7", card_alt="#EDEEF1", header="#DADCE0",
        field="#FAFBFC", tab="#F7F8FA", border="#BFC3CA",
        text="#262B33", text_mid="#4A505A", text_soft="#6B717C",
        title="#00838A", on_accent="#FFFFFF", good_text="#2F7D4F",
        good="#3E8E5E", fair="#8FA33A", warn="#C9962B", bad="#B8483B", worst="#7A4A8C",
        # OKLCH: azure (0.54, 0.19, 258); accents L 0.52-0.58, C 0.17-0.21
        ui="#1069DA", ui_alt="#00838A",
        accents=dict(orange="#C65100", magenta="#C2206A", purple="#7640D2",
                     teal="#00838A", blue="#1069DA")),
    "moderndark": dict(    # charcoal; pairs with the modern_dark style
        theme="modern_dark", dark=True,
        panel="#2B2D31", card="#33363B", card_alt="#303237", header="#3A3D43",
        field="#1F2124", tab="#3A3D43", border="#4A4E56",
        text="#E6E7EA", text_mid="#B9BDC6", text_soft="#8D929C",
        title="#4FB3B6", on_accent="#1B1D20", good_text="#6CC08B",
        good="#3E9A62", fair="#8AA236", warn="#C4962E", bad="#C4553F", worst="#8A5A9C",
        # the light hues at OKLCH L 0.72
        ui="#6AA7F4", ui_alt="#4FB3B6",
        accents=dict(orange="#EE8545", magenta="#F275A0", purple="#AB91F2",
                     teal="#4FB3B6", blue="#6AA7F4")),
    # Flexoki (stephango.com/flexoki) greys and accents: 600 shades in light,
    # 400 in dark. Cards are never paper: Olex2 darkens the card colour in HLS
    # for the info icons, and warm paper has HLS saturation 1 (turns yellow).
    # Grades run cyan, green, yellow, red, purple: Flexoki's own green, amber
    # and red were too alike. green = the .cif title, which stays green.
    "flexokilight": dict(
        theme="flexoki_light",
        # panel base-100, cards base-50, header base-150, fields/tabs paper
        panel="#E6E4D9", card="#F2F0E5", card_alt="#ECEADF", header="#DAD8CE",
        field="#FFFCF0", tab="#FFFCF0", border="#B7B5AC",                    # base-300
        text="#100F0F", text_mid="#575653", text_soft="#878580",             # tx, base-700, tx-2
        title="#24837B", on_accent="#FFFCF0", good_text="#66800B", green="#66800B",
        good="#24837B", fair="#66800B", warn="#BE9207", bad="#AF3029", worst="#5E409D",
        ui="#205EA6", ui_alt="#24837B",
        buttons={"#205EA6": ("#C6DDE8", "#1A4F8C"),                          # blue-100 / 700
                 "#24837B": ("#BFE8D9", "#1C6C66")},                         # cyan-100 / 700
        accents=dict(orange="#BC5215", magenta="#A02F6F", purple="#5E409D",
                     cyan="#24837B", blue="#205EA6")),
    "flexokidark": dict(
        theme="flexoki_dark", dark=True,
        # panel base-900, cards base-850, header/tabs base-800, fields base-950
        panel="#282726", card="#343331", card_alt="#2E2D2B", header="#403E3C",
        field="#1C1B1A", tab="#403E3C", border="#575653",                    # base-700
        text="#CECDC3", text_mid="#B7B5AC", text_soft="#878580",             # tx, base-300, tx-2
        title="#3AA99F", on_accent="#1C1B1A", good_text="#879A39", green="#879A39",
        # grade cells keep white text, so 500 shades (purple-400) rather than 400
        good="#2F968D", fair="#768D21", warn="#BE9207", bad="#C03E35", worst="#8B7EC8",
        # links in blue-300: blue-400 is only 3.2:1 on the cards
        ui="#66A0C8", ui_alt="#3AA99F",
        buttons={"#66A0C8": ("#133051", "#92BFDB"),                          # blue-850 / 200
                 "#3AA99F": ("#143F3C", "#87D3C3")},                         # cyan-850 / 200
        accents=dict(orange="#DA702C", magenta="#CE5D97", purple="#8B7EC8",
                     cyan="#3AA99F", blue="#4385BE")),
}
DEFAULT_ACCENT = "orange"   # the user's pick: closest to the original Olex2 look
ALT_UI = {"purple", "blue"}   # accents that take ui_alt, as they would blend with a blue ui


def family_skins():
    """Expand FAMILIES into one palette per skin name."""
    # e.g. "flexokidark" (orange), "flexokidarkmagenta", "flexokidarkcyan" ...
    skins = {}
    for fam, f in FAMILIES.items():
        base = {k: v for k, v in f.items() if k not in ("accents", "ui_alt", "buttons")}
        for colour, accent in f["accents"].items():
            p = dict(base, accent=accent, ui=f["ui_alt"] if colour in ALT_UI else f["ui"])
            if "buttons" in f:
                p["button_bg"], p["button_fg"] = f["buttons"][p["ui"]]
            skins[fam + ("" if colour == DEFAULT_ACCENT else colour)] = p
    return skins


SKINS = family_skins()   # skin name -> palette
# panel text font; a Semibold face would make <b> look the same as normal text,
# so the formula line (plain HTML) is made a size larger instead
SKIN_FONT = "Segoe UI"


def rgb_tuple(h):
    """'#RRGGBB' -> "'(r, g, b)'", the form some .phil colour keys take."""
    return "'(%d, %d, %d)'" % tuple(round(c * 255) for c in hex_rgb(h))


def build_skin(name, p):
    """Return the .phil text of a GUI skin from palette p."""
    # The .phil keys override Olex2's gui.params. The first line marks the file
    # as generated; main() relies on it to delete stale skins, so keep it.
    import colorsys
    t = THEMES[p["theme"]]
    if "button_bg" not in p:
        p = dict(p, **dict(zip(("button_bg", "button_fg"),
                               tint_buttons(p["ui"], p.get("dark", False)))))
    # the space group is html.base_colour with its HLS lightness scaled by sg_L;
    # scale it to the lightness of the title text
    sg_L = (colorsys.rgb_to_hls(*hex_rgb(p["on_accent"]))[1]
            / colorsys.rgb_to_hls(*hex_rgb(p["text_soft"]))[1])
    # info box in the 3D view: materials with 2053 = identity draw + ambient +
    # diffuse; the plane behind the text is the background at 85 % opacity
    console, plane = hex_rgb(t["console"]), hex_rgb(t["bg_top"])
    ident_text = "'2053;%d;%d'" % (pack(console), pack(console))
    ident_plane = "'2053;%d;%d'" % (pack(plane, 0.85), pack(plane, 0.85))
    # generated tab and button images: no gradient, no drop shadow
    flat = "grad_step = 0.01\n      shadow = False"
    return f"""# Generated by etc/styles/build_modern.py - edit the palette there.
gui {{
  base_colour = {p['text_soft']}
  logo_colour = {p['accent']}
  action_colour = {p['ui']}
  blue = {p['ui']}
  light_blue = {p['ui']}
  grey = {p['text_mid']}
  light_grey = {p['card']}
  watermark = {p['text_soft']}
  green = {p.get('green', p['good'])}
  dark_green = {p.get('green', p['good'])}
  green_text = {p['good_text']}
  red = {p['bad']}
  dark_red = {p['bad']}
  orange = {p['warn']}
  dark_yellow = {p['warn']}
  purple = {p['worst']}
  notification_base_colour = {p['good_text']}
  notification_highlight_colour = {p['accent']}
  console_font = #olex2.fnt:frb_12
  labels_font = '{native_font(16, "Segoe UI Semibold", 600)}'
  infobox_text = {ident_text}
  infobox_plane = {ident_plane}
  grad_top_left = {t['bg_top']}
  grad_top_right = {t['bg_top']}
  grad_bottom_left = {t['bg_bottom']}
  grad_bottom_right = {t['bg_bottom']}

  html {{
    base_colour = {p['text_soft']}
    bg_colour = {p['panel']}
    font_colour = {p['text']}
    font_name = "{SKIN_FONT}"
    formula_colour = {p['text']}
    formula_size = 6
    highlight_colour = {p['accent']}
    input_bg_colour = {p['field']}
    link_colour = {p['ui']}
    table_bg_colour = {p['card']}
    table_firstcol_colour = {p['card']}
    table_group_bg_colour = {p['card_alt']}
    table_group_header_colour = {p['header']}
    table_row_bg_colour = {p['card_alt']}
  }}

  skin {{
    name = {name}
    clearcolor = {pack(hex_rgb(t['bg']))}
    icon_border_colour = {p['border']}
    link_button {{
      flat = True
      bgcolor = {p['button_bg']}
      fgcolor = {p['button_fg']}
    }}
    diagnostics {{
      colour_grade1 = {p['good']}
      colour_grade2 = {p['fair']}
      colour_grade3 = {p['warn']}
      colour_grade4 = {p['bad']}
      colour_grade5 = {p['worst']}
    }}
  }}

  timage {{
    base_colour = {p['text_soft']}
    grad_colour = {p['card']}
    font_colour = {p['text']}
    grad_step = 0.01

    snumtitle {{
      base_colour = {p['title']}
      grad_colour = {p['title']}
      font_colour = {rgb_tuple(p['on_accent'])}
      filefullinfo_colour = {rgb_tuple(p['on_accent'])}
      sg_L = {sg_L:.3f}
      {flat}
    }}
    tab {{
      base_colour = {p['tab']}
      grad_colour = {p['tab']}
      font_colour = {p['text_mid']}
      border = 1
      border_colour = {p['border']}
      arrows = "bar:top:4"
      off_L = 1.0
      on_L = 1.0
      hover_L = 1.0
      {flat}
    }}
    cbtn {{
      base_colour = {p['border']}
      grad_colour = {p['card']}
      font_colour = {p['text_mid']}
      off_L = 1.0
      on_L = 1.0
      hover_L = 0.9
      {flat}
    }}
    h1 {{
      base_colour = {p['border']}
      grad_colour = {p['card']}
      font_colour = {p['text']}
      border = 0
      arrows = "bar:left:4"
      off_L = 1.0
      on_L = 1.0
      hover_L = 0.9
      {flat}
    }}
    h3 {{
      base_colour = {p['border']}
      grad_colour = {p['card_alt']}
      font_colour = {p['text_mid']}
      border = 0
      arrows = "bar:left:3"
      off_L = 1.0
      on_L = 1.0
      hover_L = 0.9
      {flat}
    }}
    button {{
      base_colour = {p['border']}
      grad_colour = {p['field']}
      font_colour = {p['text']}
      border = 1
      border_colour = {p['border']}
      buttonmark = None
      {flat}
    }}
    tinybutton {{
      base_colour = {p['text_soft']}
      grad_colour = {p['text_soft']}
      font_colour = {p['on_accent']}
      border_colour = {p['border']}
      {flat}
    }}
  }}

  graph {{
    light_grey = {p['border']}
    grey = {p['text_mid']}
    dark_grey = {p['text']}
    filename_colour = {p['text_soft']}
    title_colour = {p['text_mid']}
    fill_colour = {p['card']}
    outline_colour = {p['text_soft']}
    fitline_colour = {p['accent']}
    page_colour = {p['card']}
    graph_bg_colour = {p['card']}
    axislabel_colour = {p['text_mid']}
  }}
}}
"""


def main():
    """Parse the command line and write every style and skin (or only report)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--finish", choices=sorted(FINISHES), default="satin")
    # dark: a deeper shade of the atom colour; neutral: grey; keep: light_g's rims
    ap.add_argument("--rims", choices=["dark", "neutral", "keep"], default="dark")
    ap.add_argument("--report", action="store_true", help="only print palette checks")
    args = ap.parse_args()
    if args.report:
        report()
        return
    # 3D styles: <theme>.glds (atoms and overlays) + <theme>.glsp (scene),
    # written with Windows line endings like Olex2's own files
    for name in THEMES:
        style = build(os.path.join(HERE, "light_g.glds"), args.finish, args.rims, name)
        style.set("LinkFile", "./etc/styles/%s.glsp" % name)
        with open(os.path.join(HERE, name + ".glds"), "w", encoding="utf-8",
                  newline="\r\n") as f:
            f.write(write_xl(style) + "\n")
        scene = build_scene(os.path.join(HERE, "light_g.glsp"), name)
        with open(os.path.join(HERE, name + ".glsp"), "w", encoding="utf-8",
                  newline="\r\n") as f:
            f.write("\n".join(write_xl(i) for i in scene) + "\n")
    print("wrote styles:", ", ".join(THEMES))
    # GUI skins: one .phil per entry of SKINS
    skins_dir = os.path.join(HERE, "..", "skins")
    for name, palette in SKINS.items():
        with open(os.path.join(skins_dir, name + ".phil"), "w", encoding="utf-8",
                  newline="\r\n") as f:
            f.write(build_skin(name, palette))
    print("wrote skins:", ", ".join(SKINS))
    # drop skins an earlier run generated that are no longer in SKINS
    for fn in sorted(os.listdir(skins_dir)):
        path = os.path.join(skins_dir, fn)
        if fn.endswith(".phil") and fn[:-5] not in SKINS:
            with open(path, encoding="utf-8", errors="replace") as f:
                generated = f.readline().startswith("# Generated by etc/styles/build_modern.py")
            if generated:
                os.remove(path)
                print("removed stale skin:", fn)


if __name__ == "__main__":
    main()

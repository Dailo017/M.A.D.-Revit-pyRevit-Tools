# -*- coding: utf-8 -*-
__title__   = "Walls From\nDWG"
__doc__     = """Version = 1.3
Date    = 14.11.2026
________________________________________________________________
Description:

Creates walls, doors and windows from the layers of a DWG
(linked or imported):
1- Pick the DWG, then the wall type, the height and the width
   used for single lines, the door / window families with their
   height (and sill of the windows), then the role of each layer
   (walls, doors, windows).
2- Two parallel lines of the same layer closer than the max
   width = the two faces of a wall: the wall is placed on their
   center line with the width measured in the DWG (rounded to
   5 mm). Walls drawn with all their layers (boards, core...)
   are read as one wall with their whole width.
3- A line without a parallel partner = the center line of a
   wall with the width chosen in the form.
4- Where both faces stop and lines of a door / window layer are
   drawn in the gap, the wall goes on through the opening and a
   door / window is placed in it, with the width of the gap
   (doors up to 2.5 m, wider gaps stay open). A gap with a door
   and a side window / fixed panel is split using the door arcs.
   Doors are flipped to swing like the arc of the DWG.
5- Missing wall widths and door / window sizes get new types,
   duplicated from the chosen type / family.
6- A wall drawn on two layers is created once (the wider one).
   Short thick blocks that touch no wall (columns) are skipped.
7- Ends are moved to the center line of the wall they run into,
   so that Revit joins the walls (L, T, cross).
________________________________________________________________
How-To:

1. Open a floor plan (everything is created on its level).
2. Click the button and follow the forms.
3. Only straight lines / polylines make walls (no arcs). Give
   the 'Walls' role only to the layers of the wall faces (no
   hatch, axis or furniture).
________________________________________________________________
Last Updates:
- [14.11.2026] v1.3 Layered walls (several parallel lines) and shafts:
                    no thick walls across the void / two walls merged,
                    walls on two layers or crossing inside another one
                    created once, L corners trimmed to the center line,
                    door + side window / panel split, joints < 25 cm
                    are not doors, free-standing blocks (columns) skipped,
                    a door / window needs lines at both jambs of the gap
- [03.11.2026] v1.2 Faces are paired only within the same layer (no
                    thick / overlapping walls between two layers),
                    doors wider than 2.5 m are not placed
- [02.11.2026] v1.1 Doors and windows: the walls go on through the
                    openings + layer roles
- [02.11.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
import bisect
import math
import re

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from pyrevit import forms, script

#.NET Imports
import clr
clr.AddReference('System')
clr.AddReference('PresentationFramework')
from System.Collections.Generic import List
from System.Windows import Thickness, GridLength, Visibility, FontWeights
from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, ComboBox

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

output = script.get_output()
config = script.get_config()

MM = 1 / 304.8           # 1 mm in feet

# Tolerances (feet)
POINT_TOL = 0.003        # ~1 mm, same point
OFF_TOL   = 0.033        # ~1 cm, same line (collinear)
ANG_TOL   = 0.01         # rad (~0.6°), parallel
MIN_SEG   = 0.33         # ~10 cm, shorter walls are not created
SNAP_TOL  = 0.15         # ~4.5 cm, extra reach when an end is moved to the wall it runs into
MIN_JOIN_SIN = 0.17      # ~10°, walls closer to parallel are not joined
PARALLEL_SIN = 0.035     # ~2°, walls this parallel in the same band are the same wall
BLOCK_RATIO = 2.0        # a wall shorter than this x its width that touches no wall is a column / pier
TOL_DIM   = 1e-4         # same width

MIN_WIDTH = 50 * MM      # closer parallel lines draw the same face (double contour)
WIDTH_STEP_MM = 5        # measured widths are rounded to this
SINGLE_FACTOR = 1.5      # with double lines, single lines up to this x max width are end caps / jambs
PATTERN_MIN = 5          # equally spaced parallel lines = hatch / stair / louvers, not walls
WIDTH_TOL = 40 * MM      # same wall measured with a width this different (inner lines missing)

# Openings (gap in a wall where both faces stop)
MAX_OPENING = 16.4       # ~5 m, wider gaps are never bridged
MAX_DOOR    = 8.2        # ~2.5 m, a wider gap is a passage (door lines nearby belong to another door)
JAMB_TOL    = 0.164      # ~5 cm, door / window lines this close to the wall band / jambs count
MIN_OPENING = 0.82       # ~25 cm, a narrower gap with door / window lines is a joint: the wall goes on
SIDE_MIN    = 1.31       # ~40 cm, what is left beside the leaves of a door is another element
DOOR_FRAME  = 0.13       # ~4 cm, frame between the leaf of a door and the element beside it
OPENING_SLACK = 0.15     # door / window lines must reach this close (x gap) to both ends of the gap
WINDOW_BAND = 0.33       # ~10 cm, window lines may stick out of the wall (sills)

CHUNK = 50               # elements per transaction (cancel keeps the finished ones)

ROLE_NONE, ROLE_WALLS, ROLE_DOORS, ROLE_WINDOWS = '--', 'Walls', 'Doors', 'Windows'
ROLES = [ROLE_NONE, ROLE_WALLS, ROLE_DOORS, ROLE_WINDOWS]
# Role guessed from the words of the layer name (a word starts with a key; 'PORTE'
# must be the whole word: 'PORTEURS' = load-bearing walls, not doors)
ROLE_KEYS = [(ROLE_NONE,    (u'MOBIL', u'FURN', u'TRAM', u'HATCH', u'RAYAD', u'HACH', u'COTA', u'COTE',
                             u'DIM', u'TEXT', u'RIDEAU', u'CURTAIN', u'CORTINA', u'HORS=')),
             (ROLE_DOORS,   (u'PUERT', u'DOOR', u'PORTE=', u'PORTES=')),
             (ROLE_WINDOWS, (u'VENTAN', u'WINDOW', u'FENET', u'FEN\xcaT')),
             (ROLE_WALLS,   (u'MUR', u'WALL', u'TABIQ', u'PARED', u'FACHAD', u'CLOIS'))]
NO_FAMILY = '-- None --'

# Door / window dimensions (same parameters as Sync Doors Windows)
BIPS_WIDTH   = [BuiltInParameter.DOOR_WIDTH, BuiltInParameter.WINDOW_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM]
BIPS_HEIGHT  = [BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.WINDOW_HEIGHT, BuiltInParameter.FAMILY_HEIGHT_PARAM]
NAMES_WIDTH  = ["Width", "Ancho", "Anchura"]
NAMES_HEIGHT = ["Height", "Altura", "Alto"]


# ── Geometry (2D, plain tuples, feet) ─────────────
def sub(a, b):      return (a[0] - b[0], a[1] - b[1])
def add(a, b):      return (a[0] + b[0], a[1] + b[1])
def mul(a, k):      return (a[0] * k, a[1] * k)
def dot(a, b):      return a[0] * b[0] + a[1] * b[1]
def cross(a, b):    return a[0] * b[1] - a[1] * b[0]
def dist(a, b):     return math.hypot(a[0] - b[0], a[1] - b[1])
def seg_len(s):     return dist(s[0], s[1])

def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l)

def point_key(pt):
    return (int(round(pt[0] / POINT_TOL)), int(round(pt[1] / POINT_TOL)))

def sign(x):
    return (x > 0) - (x < 0)


def parallel_groups(segs):
    """Groups the segments with the same direction -> [(direction, [seg, ...]), ...]"""
    items = []
    for s in segs:
        v = sub(s[1], s[0])
        a = math.atan2(v[1], v[0]) % math.pi
        if a > math.pi - ANG_TOL:
            a -= math.pi
        items.append((a, s))
    items.sort(key=lambda x: x[0])

    groups = []
    for a, s in items:
        if groups and a - groups[-1][0] <= ANG_TOL:     # vs first angle -> no chaining
            groups[-1][1].append(s)
        else:
            groups.append((a, [s]))
    out = []
    for _, g in groups:
        longest = max(g, key=seg_len)
        d = unit(sub(longest[1], longest[0]))
        if d[1] < 0 or (abs(d[1]) < 1e-12 and d[0] < 0):
            d = mul(d, -1.0)
        out.append((d, g))
    return out


def to_frame(d, s):
    """Segment (p0, p1, layer) -> (offset, t0, t1, layer) in the frame of direction d."""
    n = (-d[1], d[0])
    off = (dot(s[0], n) + dot(s[1], n)) / 2.0
    t0, t1 = sorted((dot(s[0], d), dot(s[1], d)))
    return (off, t0, t1, s[2])


def from_frame(d, off, t0, t1):
    n = (-d[1], d[0])
    return (add(mul(d, t0), mul(n, off)), add(mul(d, t1), mul(n, off)))


def merge_collinear(segs, gap):
    """Joins collinear segments of the same layer that overlap or are separated
    by less than gap (lines broken in pieces, polylines drawn over lines...).
    segs = [(p0, p1, layer)] -> same format."""
    out, by_layer = [], {}
    for s in segs:
        by_layer.setdefault(s[2], []).append(s)
    for layer, layer_segs in by_layer.items():
        for d, group in parallel_groups(layer_segs):
            rows = sorted(to_frame(d, s) for s in group)
            clusters = []
            for r in rows:
                if clusters and r[0] - clusters[-1][0][0] <= OFF_TOL:
                    clusters[-1].append(r)
                else:
                    clusters.append([r])
            for c in clusters:
                c.sort(key=lambda r: r[1])
                off, t0, t1 = c[0][:3]
                for r in c[1:]:
                    if r[1] <= t1 + gap:
                        t1 = max(t1, r[2])
                    else:
                        out.append(from_frame(d, off, t0, t1) + (layer,))
                        t0, t1 = r[1], r[2]
                out.append(from_frame(d, off, t0, t1) + (layer,))
    return out


# ── Doors / windows of the DWG ────────────────────
class PointIndex(object):
    """Grid of the points of the door / window layers: (point, tag, arc ends),
    tag = 'door', 'window' or 'hinge' (center of a door arc, with the two ends
    of the arc)."""
    CELL = 3.0

    def __init__(self):
        self.cells = {}

    def cell(self, v):
        return int(math.floor(v / self.CELL))

    def add(self, pt, tag, ends=None):
        self.cells.setdefault((self.cell(pt[0]), self.cell(pt[1])), []).append((pt, tag, ends))

    def near(self, c, r):
        for i in range(self.cell(c[0] - r), self.cell(c[0] + r) + 1):
            for j in range(self.cell(c[1] - r), self.cell(c[1] + r) + 1):
                for item in self.cells.get((i, j), ()):
                    yield item


def build_index(layers, roles):
    index = PointIndex()
    for name, role in roles.items():
        tag = {ROLE_DOORS: 'door', ROLE_WINDOWS: 'window'}.get(role)
        if tag is None:
            continue
        for a, b in layers[name]['segs']:
            for p in (a, b, mul(add(a, b), 0.5)):
                index.add(p, tag)
        for center, pts in layers[name]['arcs']:
            for p in pts:
                index.add(p, tag)
            if tag == 'door':
                index.add(center, 'hinge', (pts[0], pts[-1]))
    return index


def find_openings(index, d, off, w_mm, ta, tb):
    """Doors / windows drawn in the gap [ta, tb] of the wall (offset off, direction d)
    -> [openings] (the wall goes on through the gap; [] = a joint, nothing to place)
    or None (passage: the gap stays open).
    The arcs of the doors give their leaves (hinge -> end of the arc on the wall).
    Two leaves whose tips meet = one double door, hinges side by side = two doors.
    What is left beside the leaves (>= SIDE_MIN) is another element: a side window,
    a fixed / sliding panel. Without arcs the gap is one door / window."""
    n = (-d[1], d[0])
    half_w, length = w_mm * MM / 2.0, tb - ta
    center = add(mul(d, (ta + tb) / 2.0), mul(n, off))
    doors, windows, swings, leaves, hinge = [], [], [], [], 0
    slack = max(3 * JAMB_TOL, OPENING_SLACK * length)      # how far from a jamb the lines may stop
    before = after = False                                 # lines in the band just past the jambs
    for pt, tag, ends in index.near(center, length / 2.0 + half_w + length + JAMB_TOL):
        t, o = dot(pt, d), dot(pt, n) - off
        if not ta - JAMB_TOL <= t <= tb + JAMB_TOL:
            if tag != 'hinge' and abs(o) <= half_w + JAMB_TOL:
                before = before or ta - slack <= t < ta
                after = after or tb < t <= tb + slack
            continue
        if tag == 'hinge':
            if abs(o) > half_w + JAMB_TOL:
                continue
            tip = min(ends, key=lambda q: abs(dot(q, n) - off))     # closed leaf
            tt = dot(tip, d)
            if (abs(dot(tip, n) - off) <= half_w + JAMB_TOL and ta - JAMB_TOL <= tt <= tb + JAMB_TOL
                    and abs(tt - t) >= MIN_OPENING):
                leaves.append((min(t, tt), max(t, tt), -1 if t < tt else 1))
            elif min(t - ta, tb - t) <= JAMB_TOL:
                hinge = -1 if t - ta < tb - t else 1
        elif tag == 'window' and abs(o) <= half_w + WINDOW_BAND:
            windows.append(t)
        elif tag == 'door':
            if abs(o) <= half_w + JAMB_TOL:
                doors.append(t)
            elif abs(o) <= half_w + length + JAMB_TOL:
                swings.append((t, o))                      # leaf / swing out of the wall
    if length < MIN_OPENING:
        return [] if doors or windows or leaves or hinge else None
    # A door / window is drawn from jamb to jamb: lines at one end only belong to
    # something else that touches the wall there (a glazed partition, another door)
    marks = doors + windows + [t for leaf in leaves for t in leaf[:2]]
    if marks and ((min(marks) - ta > slack and not before) or (tb - max(marks) > slack and not after)):
        return None

    def opening(kind, t0, t1, hinge_side):
        side = sum(o for t, o in swings if t0 <= t <= t1) if kind == 'door' else 0.0
        return {'kind':   kind,
                'center': add(mul(d, (t0 + t1) / 2.0), mul(n, off)),
                'width':  round_width(t1 - t0),
                'dir':    d,
                'swing':  mul(n, sign(side)) if side else None,                           # side of the swing
                'hinge':  mul(d, hinge_side) if kind == 'door' and hinge_side else None}  # hinge jamb from the center

    def whole():
        if len(windows) > len(doors):
            return [opening('window', ta, tb, 0)]
        if (doors or hinge or leaves) and length <= MAX_DOOR:
            return [opening('door', ta, tb, max(leaves, key=lambda l: l[1] - l[0])[2] if leaves else hinge)]
        return None

    # Doors: [start, end, hinge side of the widest leaf, its width, hinge side of the last leaf]
    groups = []
    for s0, s1, side in sorted(set(leaves)):
        g = groups[-1] if groups else None
        if g and s0 < g[1] - (s1 - s0) / 2.0:
            continue                                       # the same leaf drawn twice
        if g and g[4] == -1 and side == 1 and s0 - g[1] <= 2 * JAMB_TOL:
            if s1 - s0 > g[3]:
                g[2], g[3] = side, s1 - s0
            g[1], g[4] = s1, side                          # tips meet: double door
        else:
            groups.append([s0, s1, side, s1 - s0, side])
    if not groups:
        return whole()

    out, cur = [], ta
    for i, g in enumerate(groups):
        g0, g1 = g[0] - DOOR_FRAME, g[1] + DOOR_FRAME
        if g0 - cur >= SIDE_MIN:
            out.append((cur, g0, None))
            cur = g0
        if i + 1 < len(groups):
            nxt = groups[i + 1][0] - DOOR_FRAME
            end = g1 if nxt - g1 >= SIDE_MIN else (g[1] + groups[i + 1][0]) / 2.0
        else:
            end = g1 if tb - g1 >= SIDE_MIN else tb
        out.append((cur, min(end, tb), g))
        cur = min(end, tb)
    if tb - cur >= SIDE_MIN:
        out.append((cur, tb, None))

    found = []
    for t0, t1, g in out:
        if g:
            if t1 - t0 > MAX_DOOR:
                return whole()
            found.append(opening('door', t0, t1, g[2]))
            continue
        nw = sum(1 for t in windows if t0 <= t <= t1)
        nd = sum(1 for t in doors if t0 + JAMB_TOL <= t <= t1 - JAMB_TOL)
        if not nw and not nd:
            return whole()                                 # nothing drawn beside the door: one opening
        found.append(opening('window' if nw > nd else 'door', t0, t1, 0))
    return found


# ── Walls from parallel lines ─────────────────────
def round_width(gap):
    """Measured distance -> mm, rounded."""
    return int(round(gap / MM / WIDTH_STEP_MM)) * WIDTH_STEP_MM


def components(rows, max_w):
    """Union-find of the rows (offset, t0, t1) close enough and overlapping, or
    collinear with a gap that may be an opening (both faces stop at a door):
    each component is solved on its own (fast on big DWG)."""
    parent = list(range(len(rows)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[j][0] - rows[i][0] > max_w:
                break
            overlap = min(rows[i][2], rows[j][2]) - max(rows[i][1], rows[j][1])
            if overlap > 0 or (rows[j][0] - rows[i][0] <= OFF_TOL and -overlap <= MAX_OPENING):
                parent[root(j)] = root(i)
    comps = {}
    for i in range(len(rows)):
        comps.setdefault(root(i), []).append(i)
    return comps.values()


def offset_key(off):
    return int(round(off / OFF_TOL))


def rows_by_offset(rows):
    """{offset key: [rows]} -> the lines along an offset are found without a full scan."""
    out = {}
    for r in rows:
        out.setdefault(offset_key(r[0]), []).append(r)
    return out


def face_spans(by_off, off, t0, t1):
    """True if a line runs along offset off from t0 to t1."""
    k = offset_key(off)
    return any(abs(r[0] - off) <= OFF_TOL and r[1] <= t0 + POINT_TOL and r[2] >= t1 - POINT_TOL
               for key in (k - 1, k, k + 1) for r in by_off.get(key, ()))


def stretches(rows, comp):
    """Sweep along the direction: yields (u, v, [rows present on u-v, by offset]).
    The lines present are updated at each cut instead of scanning them all."""
    cuts = sorted(set(t for i in comp for t in rows[i][1:3]))
    starts = sorted(comp, key=lambda i: rows[i][1])
    ends = sorted(comp, key=lambda i: rows[i][2])
    active, si, ei = [], 0, 0
    for u, v in zip(cuts, cuts[1:]):
        while si < len(starts) and rows[starts[si]][1] <= u:
            bisect.insort(active, starts[si])           # index order = offset order
            si += 1
        while ei < len(ends) and rows[ends[ei]][2] <= u:
            active.remove(ends[ei])
            ei += 1
        if v - u > POINT_TOL:
            yield u, v, active


def pattern_lines(rows, active, max_w):
    """Lines of a regular series on a stretch: PATTERN_MIN or more parallel lines
    equally spaced closer than max_w (hatch, insulation, stair treads, louvers).
    A wall has 2 faces, 2 walls side by side 4 lines with different gaps."""
    out, run = set(), []
    for i in active:
        if run and rows[i][0] - rows[run[-1]][0] <= POINT_TOL:
            continue                                       # same line drawn twice
        if len(run) >= 2:
            gap, last = rows[i][0] - rows[run[-1]][0], rows[run[-1]][0] - rows[run[-2]][0]
            if gap <= max_w and abs(gap - last) <= OFF_TOL:
                run.append(i)
                continue
            if len(run) >= PATTERN_MIN:
                out.update(run)
            run = [run[-1], i] if gap <= max_w else [i]
        elif run and rows[i][0] - rows[run[-1]][0] > max_w:
            run = [i]
        else:
            run.append(i)
    if len(run) >= PATTERN_MIN:
        out.update(run)
    return out


def same_run(r, s):
    """How much two parallel lines run together: the length they share, reduced
    when one goes on much further than the other (x overlap / union of their
    extents). Long for the lines of one wall, ~0 for a line that just passes by."""
    union = max(r[2], s[2]) - min(r[1], s[1])
    overlap = max(0.0, min(r[2], s[2]) - max(r[1], s[1]))
    return overlap * overlap / union if union > 0 else 0.0


def split_walls(rows, lines, max_w):
    """Walls of a stretch. lines = indexes of the rows present, sorted by offset
    -> [(i, j)]: positions in lines of the two outer lines of each wall.
    A wall = lines i..j with a width between MIN_WIDTH and max_w, drawn as:
    - a chain of lines closer than MIN_WIDTH (all its layers: boards, core...), or
    - two faces separated by one gap >= MIN_WIDTH (the core), each face being one
      line or a few lines within MIN_WIDTH (finish / double contour) with no other
      line close behind (the lines left of a chain are not a face: inside of a
      shaft between two layered walls).
    Among all the ways of splitting the lines, the one that explains the most
    lines with lines that run together is kept: a line left over from another
    wall (mitred corner, junction) is not taken as a face, and two walls drawn
    against each other are not merged in a thick one."""
    n = len(lines)
    off = [rows[i][0] for i in lines]
    best = [(0.0, None)] * (n + 1)                         # (score, j of the wall starting at k)
    for k in range(n - 1, -1, -1):
        top = (best[k + 1][0], None)                       # line k is not part of a wall
        core = None                                        # first line after the core gap
        for j in range(k + 1, n):
            if off[j] - off[j - 1] >= MIN_WIDTH:
                if core is not None or off[j - 1] - off[k] >= MIN_WIDTH:
                    break                                  # 2 gaps / the first face is a wall itself
                core = j
            width = off[j] - off[k]
            if width > max_w or (core is not None and off[j] - off[core] >= MIN_WIDTH):
                break
            if width < MIN_WIDTH:
                continue
            if core is not None and ((k > 0 and off[k] - off[k - 1] < MIN_WIDTH) or
                                     (j < n - 1 and off[j + 1] - off[j] < MIN_WIDTH)):
                continue                                   # a face = all its lines, not the rest of a chain
            score = (j - k + 1) * same_run(rows[lines[k]], rows[lines[j]]) - 1e-6 * width + best[j + 1][0]
            if score > top[0]:
                top = (score, j)
        best[k] = top
    out, k = [], 0
    while k < n:
        j = best[k][1]
        if j is None:
            k += 1
        else:
            out.append((k, j))
            k = j + 1
    return out


def normalize_bands(pieces):
    """Pieces of one wall measured with a slightly different width (a line of the
    inner layers is missing on a stretch: jambs, door frames...) get the offset /
    width of the longest of them, so that they make one wall. Same wall = the band
    of one is inside the band of the other (widths differ <= WIDTH_TOL) and they
    overlap or are separated by less than an opening."""
    n = len(pieces)
    order = sorted(range(n), key=lambda i: pieces[i][0])
    parent = list(range(n))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for x, i in enumerate(order):
        for j in order[x + 1:]:
            pi, pj = pieces[i], pieces[j]
            if pj[0] - pi[0] > WIDTH_TOL:
                break
            dw = abs(pi[3] - pj[3]) * MM
            if (dw <= WIDTH_TOL and pj[0] - pi[0] <= dw / 2.0 + OFF_TOL and
                    max(pi[1], pj[1]) - min(pi[2], pj[2]) <= MAX_OPENING):
                parent[root(j)] = root(i)
    clusters = {}
    for i in range(n):
        clusters.setdefault(root(i), []).append(i)
    out = list(pieces)
    for members in clusters.values():
        if len(members) < 2:
            continue
        length = {}
        for i in members:
            key = (offset_key(pieces[i][0]), pieces[i][3])
            length[key] = length.get(key, 0.0) + pieces[i][2] - pieces[i][1]
        best = max(length, key=lambda k: length[k])
        ref = [pieces[i] for i in members if (offset_key(pieces[i][0]), pieces[i][3]) == best][0]
        for i in members:
            out[i] = (ref[0], pieces[i][1], pieces[i][2], ref[3])
    return out


def absorb_ends(pieces):
    """Layered walls are mitred at the corners: the inner lines stop before the
    outer ones, so the last bit of the wall is measured narrower. A short run of
    pieces (not longer than the width of the wall) that touches a wider and longer
    run and lies in its band gets its offset / width."""
    order = sorted(range(len(pieces)), key=lambda i: (pieces[i][3], offset_key(pieces[i][0]), pieces[i][1]))
    runs = []                                              # [off, t0, t1, w, [pieces]]
    for i in order:
        p = pieces[i]
        if runs and runs[-1][3] == p[3] and abs(runs[-1][0] - p[0]) <= OFF_TOL and p[1] - runs[-1][2] <= POINT_TOL:
            runs[-1][2] = max(runs[-1][2], p[2])
            runs[-1][4].append(i)
        else:
            runs.append([p[0], p[1], p[2], p[3], [i]])
    out = list(pieces)
    for r in runs:
        wall = None
        for q in runs:
            if (q[3] > r[3] and r[2] - r[1] <= q[3] * MM and q[2] - q[1] > r[2] - r[1]
                    and (abs(q[1] - r[2]) <= POINT_TOL or abs(r[1] - q[2]) <= POINT_TOL)
                    and abs(q[0] - r[0]) <= (q[3] - r[3]) * MM / 2.0 + OFF_TOL
                    and (wall is None or q[3] > wall[3])):
                wall = q
        if wall:
            for i in r[4]:
                out[i] = (wall[0], pieces[i][1], pieces[i][2], wall[3])
    return out


def lines_inside(by_off, off, half, t0, t1):
    """True if a line runs inside the band (not on its faces) along a good part of t0-t1."""
    for key in range(offset_key(off - half) + 1, offset_key(off + half)):
        for r in by_off.get(key, ()):
            if abs(r[0] - off) < half - OFF_TOL and min(r[2], t1) - max(r[1], t0) > (t1 - t0) / 4.0:
                return True
    return False


def merge_pieces(pieces, rows, max_w, d, index):
    """Joins the pieces of the same wall -> [(off, t0, t1, w, [openings])].
    A gap is bridged when one of the faces goes on (T junction: the other face
    is cut by the branch) or when a door / window is drawn in it and no wall line
    runs inside the band (the 'gap' between two bits of a shaft / closet is not an
    opening: its walls go on there). A gap without anything (passage) stays open."""
    out, by_off = [], rows_by_offset(rows)
    for p in sorted(absorb_ends(normalize_bands(pieces)), key=lambda p: (p[3], offset_key(p[0]), p[1])):
        if out:
            off, t0, t1, w, ops = out[-1]
            if p[3] == w and abs(p[0] - off) <= OFF_TOL:
                gap = p[1] - t1
                half = w * MM / 2.0
                bridge = gap <= POINT_TOL or (gap <= max_w and (face_spans(by_off, off - half, t1, p[1]) or
                                                                face_spans(by_off, off + half, t1, p[1])))
                if not bridge and gap <= MAX_OPENING and not lines_inside(by_off, off, half, t1, p[1]):
                    found = find_openings(index, d, off, w, t1, p[1])
                    if found is not None:
                        ops.extend(found)
                        bridge = True
                if bridge:
                    out[-1] = (off, t0, max(t1, p[2]), w, ops)
                    continue
        out.append(p + ([],))
    return out


# ── Walls drawn twice ─────────────────────────────
class SegGrid(object):
    """Grid of the boxes of segments -> the ones near another segment."""
    CELL = 10.0

    def __init__(self):
        self.cells = {}

    def keys(self, a, b, r):
        c = self.CELL
        for i in range(int(math.floor((min(a[0], b[0]) - r) / c)), int(math.floor((max(a[0], b[0]) + r) / c)) + 1):
            for j in range(int(math.floor((min(a[1], b[1]) - r) / c)), int(math.floor((max(a[1], b[1]) + r) / c)) + 1):
                yield (i, j)

    def add(self, item, a, b, r):
        for key in self.keys(a, b, r):
            self.cells.setdefault(key, []).append(item)

    def near(self, a, b, r=0.0):
        out = set()
        for key in self.keys(a, b, r):
            out.update(self.cells.get(key, ()))
        return out


def covered_spans(seg, half, walls, grid, tol=OFF_TOL):
    """Parts of seg lying in the band of a wall -> [(s0, s1, wall index, parallel)],
    s = distance from the start of seg. All of it when both ends are in the band
    (crossing it or along it); the part along a parallel wall when the band of
    seg (half = its half width, 0 for a line) is inside the band of the wall
    (+ tol)."""
    a, b = seg
    length = dist(a, b)
    d = unit(sub(b, a))
    out = []
    for k in grid.near(a, b):
        wall = walls[k]
        w0, w1 = wall[0]
        u = unit(sub(w1, w0))
        hw, wl = wall[1] * MM / 2.0, dist(w0, w1)
        ta, tb = dot(sub(a, w0), u), dot(sub(b, w0), u)
        oa, ob = abs(cross(u, sub(a, w0))), abs(cross(u, sub(b, w0)))
        parallel = abs(cross(d, u)) < PARALLEL_SIN
        if max(oa, ob) + (half if parallel else 0.0) > hw + tol:
            continue
        if parallel:
            s0, s1 = sorted((dot(sub(w0, a), d), dot(sub(w1, a), d)))
            s0, s1 = max(s0, 0.0), min(s1, length)
            if s1 - s0 > POINT_TOL:
                out.append((s0, s1, k, True))
        elif min(ta, tb) >= -tol and max(ta, tb) <= wl + tol:
            out.append((0.0, length, k, False))
    return out


def uncovered(seg, spans):
    """Pieces of seg left once the spans [(s0, s1, ...)] are taken out -> [(s0, s1)]."""
    out, s = [], 0.0
    for sp in sorted(spans):
        if sp[0] - s > POINT_TOL:
            out.append((s, sp[0]))
        s = max(s, sp[1])
    length = seg_len(seg)
    if length - s > POINT_TOL:
        out.append((s, length))
    return out


def drop_covered(walls, singles):
    """walls = [(center seg, width mm, [openings])]. Removes what is found twice:
    - a wall that crosses inside the band of another one (the two jambs of a pier
      between two openings paired as a wall, the zigzag of a folding partition...)
    - the part of a wall that runs in the band of a wider / longer one (the same
      wall drawn on two layers, its core on another layer). Its doors / windows
      go to the wall that stays.
    - the part of a single line that runs in the band of a wall or closer than
      MIN_WIDTH to it (a face drawn again on another layer, a finish line).
    The wider (then longer) wall stays. A wall less than twice as long as wide
    does not remove anything: when it is wrong (inside of a shaft) the walls in
    it are the right ones."""
    order = sorted(range(len(walls)), key=lambda k: (-walls[k][1], -seg_len(walls[k][0])))
    kept, grid = [], SegGrid()
    for k in order:
        seg, w, ops = walls[k]
        a, d = seg[0], unit(sub(seg[1], seg[0]))
        spans = covered_spans(seg, w * MM / 2.0, kept, grid)
        for s0, s1 in (uncovered(seg, spans) if spans else [(0.0, seg_len(seg))]):
            if s1 - s0 < w * MM:
                continue                                   # what sticks out of the other wall is not a wall
            piece = ((add(a, mul(d, s0)), add(a, mul(d, s1))), w,
                     [op for op in ops if s0 <= dot(sub(op['center'], a), d) <= s1])
            if s1 - s0 >= 2.0 * w * MM:
                grid.add(len(kept), piece[0][0], piece[0][1], w * MM / 2.0 + OFF_TOL)
            kept.append(piece)
        for s0, s1, j, parallel in spans:
            if not parallel:
                continue
            for op in ops:                                 # openings of the part removed
                if (s0 <= dot(sub(op['center'], a), d) <= s1 and
                        not any(dist(op['center'], o['center']) < (op['width'] + o['width']) * MM / 2.0
                                for o in kept[j][2])):
                    kept[j][2].append(op)
    grid = SegGrid()
    for k, wall in enumerate(kept):
        grid.add(k, wall[0][0], wall[0][1], wall[1] * MM / 2.0 + MIN_WIDTH)
    lines = []
    for seg in singles:
        a, d = seg[0], unit(sub(seg[1], seg[0]))
        spans = covered_spans(seg, 0.0, kept, grid, MIN_WIDTH)
        lines += [(add(a, mul(d, s0)), add(a, mul(d, s1)))
                  for s0, s1 in (uncovered(seg, spans) if spans else [(0.0, seg_len(seg))])]
    return kept, lines


def wall_pieces(segs, max_w, index, progress):
    """-> ([(center seg, width mm, [openings])], [lines never paired]).
    Along the path the set of lines changes (junctions, openings): the walls are
    found on each stretch where the same lines are present (split_walls).
    Progress: 1 unit per line.
    Bits shorter than MIN_WIDTH are ignored (segments of hatch / insulation
    polylines): a face of a wall is never that short."""
    segs = [sg for sg in segs if seg_len(sg) >= MIN_WIDTH]
    walls, singles = [], []
    by_layer = {}
    for sg in segs:
        by_layer.setdefault(sg[2], []).append(sg)
    # Each layer is solved on its own: lines of two layers side by side (load-bearing
    # wall + partition, wall + cladding) are never the two faces of one wall
    for layer_segs in by_layer.values():
        for d, group in parallel_groups(layer_segs):
            rows = sorted(to_frame(d, s) for s in group)
            paired = [False] * len(rows)
            for comp in components(rows, max_w):
                crow = [rows[i] for i in comp]
                pieces = []
                for u, v, active in stretches(rows, comp):
                    hatch = pattern_lines(rows, active, max_w)
                    for i in hatch:
                        paired[i] = True                   # not single lines either
                    lines = [i for i in active if i not in hatch]
                    for i, j in split_walls(rows, lines, max_w):
                        a, b = rows[lines[i]][0], rows[lines[j]][0]
                        pieces.append(((a + b) / 2.0, u, v, round_width(b - a)))
                        for x in lines[i:j + 1]:
                            paired[x] = True
                for off, t0, t1, w, ops in merge_pieces(pieces, crow, max_w, d, index):
                    if t1 - t0 >= w * MM:                  # shorter: a jamb next to another wall
                        walls.append((from_frame(d, off, t0, t1), w, ops))
                progress.advance(len(comp))
            singles += [from_frame(d, *rows[i][:3]) for i in range(len(rows)) if not paired[i]]
    walls, singles = drop_covered(walls, singles)

    # Drawn with double lines -> the short single lines are end caps, jambs...
    if walls:
        singles = [s for s in singles if seg_len(s) > SINGLE_FACTOR * max_w]
    return walls, singles


def snap_ends(walls, progress):
    """walls = [[p0, p1, width mm, openings], ...]. A free end in the band of another
    wall is moved to its center line: the two faces drawn in the DWG stop at the
    face of the other wall (T junction: extended) or go on to its outer face (L
    corner: trimmed), Revit joins walls at their center line.
    -> indexes of the walls that touch another one."""
    count, joined = {}, set()
    for w in walls:
        for p in w[:2]:
            count[point_key(p)] = count.get(point_key(p), 0) + 1
    # Grid of the boxes of the walls -> only the walls near an end are tested
    CELL = 10.0
    cell = lambda v: int(math.floor(v / CELL))
    boxes, grid = [], {}
    for k, w in enumerate(walls):
        r = w[2] * MM / 2.0 + SNAP_TOL
        box = (min(w[0][0], w[1][0]) - r, min(w[0][1], w[1][1]) - r,
               max(w[0][0], w[1][0]) + r, max(w[0][1], w[1][1]) + r)
        boxes.append(box)
        for i in range(cell(box[0]), cell(box[2]) + 1):
            for j in range(cell(box[1]), cell(box[3]) + 1):
                grid.setdefault((i, j), []).append(k)

    for index, wall in enumerate(walls):
        for e in (0, 1):
            p, q = wall[e], wall[1 - e]
            if seg_len((p, q)) < POINT_TOL:
                continue
            if count[point_key(p)] > 1:
                joined.add(index)
                continue                                   # already joined (center line drawings)
            d = unit(sub(p, q))                            # outwards
            margin = wall[2] * MM / 2.0 + SNAP_TOL
            best = None
            near = set()
            for i in range(cell(p[0] - margin), cell(p[0] + margin) + 1):
                for j in range(cell(p[1] - margin), cell(p[1] + margin) + 1):
                    near.update(grid.get((i, j), ()))
            for k in near:
                other, box = walls[k], boxes[k]
                if other is wall or not (box[0] - margin <= p[0] <= box[2] + margin and
                                         box[1] - margin <= p[1] <= box[3] + margin):
                    continue
                L = seg_len(other[:2])
                if L < POINT_TOL:
                    continue
                u = unit(sub(other[1], other[0]))
                den = cross(d, u)
                if abs(den) < MIN_JOIN_SIN:
                    continue
                w0 = sub(other[0], p)
                s = cross(w0, u) / den                     # along d from p
                t = cross(w0, d) / den                     # along the other wall
                reach = other[2] * MM / 2.0 + SNAP_TOL      # the end is in the band of the other wall
                side = max(margin, reach)                  # ... or just past its end (L corner)
                # several walls at a node: the widest one is the main wall, the others run into it
                if (abs(s) <= reach and -side <= t <= L + side
                        and (best is None or (other[2], -abs(s)) > (best[2], -abs(best[0])))):
                    best = (s, add(p, mul(d, s)), other[2], k)
            if best:
                joined.update((index, best[3]))
                if abs(best[0]) > POINT_TOL:
                    wall[e] = best[1]
        progress.advance()
    return joined


# ── DWG ───────────────────────────────────────────
def iter_curves(geometry, classes):
    for g in geometry:
        if isinstance(g, GeometryInstance):
            for c in iter_curves(g.GetInstanceGeometry(), classes):
                yield c
        elif isinstance(g, classes):
            yield g


def read_layers(cad):
    """{layer name: {'segs': [((x0, y0), (x1, y1)), ...], 'arcs': [(center, [pts])]}}"""
    geometry = cad.get_Geometry(Options())
    if geometry is None:
        opt = Options()
        opt.View = doc.ActiveView
        geometry = cad.get_Geometry(opt)

    layers, names = {}, {}                  # names: style id -> layer (1 GetElement per layer, not per curve)
    for c in iter_curves(geometry or [], (Line, PolyLine, Arc)):
        sid = c.GraphicsStyleId
        if sid not in names:
            style = doc.GetElement(c.GraphicsStyleId)
            names[sid] = style.GraphicsStyleCategory.Name if style and style.GraphicsStyleCategory else None
        if names[sid] is None:
            continue
        layer = layers.setdefault(names[sid], {'segs': [], 'arcs': []})
        if isinstance(c, Arc):
            layer['arcs'].append(((c.Center.X, c.Center.Y), [(p.X, p.Y) for p in c.Tessellate()]))
            continue
        pts = [c.GetEndPoint(0), c.GetEndPoint(1)] if isinstance(c, Line) else list(c.GetCoordinates())
        for a, b in zip(pts, pts[1:]):
            if math.hypot(b.X - a.X, b.Y - a.Y) > POINT_TOL:
                layer['segs'].append(((a.X, a.Y), (b.X, b.Y)))
    return {k: v for k, v in layers.items() if v['segs'] or v['arcs']}


# ── Settings form ─────────────────────────────────
SETTINGS_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Walls From DWG - Settings" Width="520" SizeToContent="Height"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen">
  <StackPanel Margin="12">
    <GroupBox Header="Walls" Padding="6">
      <StackPanel>
        <TextBlock Text="Wall type (other widths are duplicated from it):"/>
        <ComboBox x:Name="type_cb" Margin="0,4,0,8"/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/><ColumnDefinition Width="110"/>
          </Grid.ColumnDefinitions>
          <Grid.RowDefinitions>
            <RowDefinition/><RowDefinition/><RowDefinition/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row="0" Text="Height (mm)" VerticalAlignment="Center"/>
          <TextBox   Grid.Row="0" Grid.Column="1" x:Name="height_tb" Margin="0,2"/>
          <TextBlock Grid.Row="1" Text="Width of the single lines = center line (mm)" VerticalAlignment="Center"/>
          <TextBox   Grid.Row="1" Grid.Column="1" x:Name="width_tb" Margin="0,2"/>
          <TextBlock Grid.Row="2" Text="Max width of the double lines (mm)" VerticalAlignment="Center"/>
          <TextBox   Grid.Row="2" Grid.Column="1" x:Name="max_tb" Margin="0,2"/>
        </Grid>
        <CheckBox x:Name="structural_cb" Content="Structural" Margin="0,6,0,0"/>
      </StackPanel>
    </GroupBox>
    <GroupBox Header="Doors (width = gap in the DWG)" Padding="6" Margin="0,8,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="110"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition/><RowDefinition/>
        </Grid.RowDefinitions>
        <ComboBox  Grid.Row="0" Grid.ColumnSpan="2" x:Name="door_cb" Margin="0,2,0,4"/>
        <TextBlock Grid.Row="1" Text="Height (mm)" VerticalAlignment="Center"/>
        <TextBox   Grid.Row="1" Grid.Column="1" x:Name="door_h_tb" Margin="0,2"/>
      </Grid>
    </GroupBox>
    <GroupBox Header="Windows (width = gap in the DWG)" Padding="6" Margin="0,8,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="110"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition/><RowDefinition/><RowDefinition/>
        </Grid.RowDefinitions>
        <ComboBox  Grid.Row="0" Grid.ColumnSpan="2" x:Name="window_cb" Margin="0,2,0,4"/>
        <TextBlock Grid.Row="1" Text="Height (mm)" VerticalAlignment="Center"/>
        <TextBox   Grid.Row="1" Grid.Column="1" x:Name="window_h_tb" Margin="0,2"/>
        <TextBlock Grid.Row="2" Text="Sill height (mm)" VerticalAlignment="Center"/>
        <TextBox   Grid.Row="2" Grid.Column="1" x:Name="sill_tb" Margin="0,2"/>
      </Grid>
    </GroupBox>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
      <Button x:Name="ok_b" Content="Next" Width="90" Margin="0,0,6,0"/>
      <Button x:Name="cancel_b" Content="Cancel" Width="90"/>
    </StackPanel>
  </StackPanel>
</Window>
"""


def to_mm(text, what, zero_ok=False):
    try:
        value = float(text.replace(',', '.'))
    except ValueError:
        raise ValueError("{}: '{}' is not a number.".format(what, text))
    if value < 0 or (value == 0 and not zero_ok):
        raise ValueError("{} must be > 0.".format(what))
    return value


def fill_combo(cb, names, last):
    for n in names:
        cb.Items.Add(n)
    cb.SelectedIndex = names.index(last) if last in names else 0


class SettingsForm(forms.WPFWindow):
    """Wall type, heights, widths, door / window families. Remembers the last choice."""
    def __init__(self, wall_types, door_families, window_families):
        forms.WPFWindow.__init__(self, SETTINGS_XAML, literal_string=True)
        self.wall_types, self.door_families, self.window_families = wall_types, door_families, window_families
        self.result = None
        by_name = lambda d: sorted(d, key=lambda x: x.lower())
        fill_combo(self.type_cb, by_name(wall_types), config.get_option('wall_type', ''))
        fill_combo(self.door_cb, [NO_FAMILY] + by_name(door_families), config.get_option('door_family', ''))
        fill_combo(self.window_cb, [NO_FAMILY] + by_name(window_families), config.get_option('window_family', ''))
        self.height_tb.Text   = config.get_option('height', '3000')
        self.width_tb.Text    = config.get_option('width', '150')
        self.max_tb.Text      = config.get_option('max_width', '600')
        self.door_h_tb.Text   = config.get_option('door_height', '2100')
        self.window_h_tb.Text = config.get_option('window_height', '1200')
        self.sill_tb.Text     = config.get_option('sill', '900')
        self.structural_cb.IsChecked = config.get_option('structural', False)
        self.ok_b.Click += self.on_ok
        self.cancel_b.Click += self.on_cancel

    def on_ok(self, sender, args):
        try:
            height   = to_mm(self.height_tb.Text, 'Wall height')
            width    = to_mm(self.width_tb.Text, 'Width of the single lines')
            max_w    = to_mm(self.max_tb.Text, 'Max width')
            door_h   = to_mm(self.door_h_tb.Text, 'Door height')
            window_h = to_mm(self.window_h_tb.Text, 'Window height')
            sill     = to_mm(self.sill_tb.Text, 'Sill height', zero_ok=True)
            if max_w * MM <= MIN_WIDTH:
                raise ValueError("Max width must be > {:g} mm.".format(MIN_WIDTH / MM))
        except ValueError as ex:
            forms.alert(str(ex))
            return
        door, window = self.door_cb.SelectedItem, self.window_cb.SelectedItem
        config.wall_type, config.door_family, config.window_family = self.type_cb.SelectedItem, door, window
        config.height, config.width, config.max_width = self.height_tb.Text, self.width_tb.Text, self.max_tb.Text
        config.door_height, config.window_height = self.door_h_tb.Text, self.window_h_tb.Text
        config.sill, config.structural = self.sill_tb.Text, bool(self.structural_cb.IsChecked)
        script.save_config()
        self.result = {'type':          self.wall_types[self.type_cb.SelectedItem],
                       'height':        height * MM,
                       'width':         int(round(width)),
                       'max_width':     max_w * MM,
                       'structural':    bool(self.structural_cb.IsChecked),
                       'door_family':   self.door_families.get(door),
                       'door_height':   door_h * MM,
                       'window_family': self.window_families.get(window),
                       'window_height': window_h * MM,
                       'sill':          sill * MM}
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()


# ── Layer form ────────────────────────────────────
LAYER_FORM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Walls From DWG - Layers" Width="560" Height="640"
        WindowStartupLocation="CenterScreen">
  <DockPanel Margin="10">
    <DockPanel DockPanel.Dock="Top" Margin="0,0,0,8">
      <TextBlock Text="Filter layers:" VerticalAlignment="Center" Margin="0,0,6,0"/>
      <TextBox x:Name="filter_tb"/>
    </DockPanel>
    <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal"
                HorizontalAlignment="Right" Margin="0,8,0,0">
      <Button x:Name="ok_b" Content="Create" Width="90" Margin="0,0,6,0"/>
      <Button x:Name="cancel_b" Content="Cancel" Width="90"/>
    </StackPanel>
    <ContentControl x:Name="header_cc" DockPanel.Dock="Top"/>
    <ScrollViewer VerticalScrollBarVisibility="Auto">
      <StackPanel x:Name="rows_panel"/>
    </ScrollViewer>
  </DockPanel>
</Window>
"""

COLUMNS = [('Layer', 360), ('Role', 140)]


def make_row_grid():
    g = Grid()
    g.Margin = Thickness(0, 2, 0, 2)
    for _, w in COLUMNS:
        cd = ColumnDefinition()
        cd.Width = GridLength(w)
        g.ColumnDefinitions.Add(cd)
    return g


def put(grid, ctrl, col):
    Grid.SetColumn(ctrl, col)
    ctrl.Margin = Thickness(2, 0, 2, 0)
    grid.Children.Add(ctrl)
    return ctrl


def word_matches(word, key):
    """key 'ABC' = the word starts with ABC, key 'ABC=' = the word is ABC."""
    return word == key[:-1] if key.endswith(u'=') else word.startswith(key)


def guess_role(layer):
    words = [w for w in re.split(u'[^A-Z\xc0-\xdd]+', layer.upper()) if w]
    for role, keys in ROLE_KEYS:
        if any(word_matches(w, k) for w in words for k in keys):
            return role
    return ROLE_NONE


class LayerForm(forms.WPFWindow):
    """One row per layer: walls, doors, windows or nothing (guessed from the name)."""
    def __init__(self, layers):
        forms.WPFWindow.__init__(self, LAYER_FORM_XAML, literal_string=True)
        self.result, self.rows = None, []
        header = make_row_grid()
        for col, (title, _) in enumerate(COLUMNS):
            put(header, TextBlock(Text=title, FontWeight=FontWeights.Bold), col)
        self.header_cc.Content = header

        for name in sorted(layers, key=lambda x: x.lower()):
            grid = make_row_grid()
            n = len(layers[name]['segs']) + len(layers[name]['arcs'])
            put(grid, TextBlock(Text="{}  ({})".format(name, n)), 0)
            cb = put(grid, ComboBox(), 1)
            for r in ROLES:
                cb.Items.Add(r)
            cb.SelectedItem = guess_role(name)
            self.rows.append((name, grid, cb))
            self.rows_panel.Children.Add(grid)
        self.filter_tb.TextChanged += self.on_filter
        self.ok_b.Click += self.on_ok
        self.cancel_b.Click += self.on_cancel

    def on_filter(self, sender, args):
        text = self.filter_tb.Text.lower()
        for name, grid, _ in self.rows:
            grid.Visibility = Visibility.Visible if text in name.lower() else Visibility.Collapsed

    def on_ok(self, sender, args):
        roles = {name: cb.SelectedItem for name, _, cb in self.rows if cb.SelectedItem != ROLE_NONE}
        if ROLE_WALLS not in roles.values():
            forms.alert("Give the role 'Walls' to at least one layer.")
            return
        self.result = roles
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()


# ── Wall types ────────────────────────────────────
def set_structure_width(cs, width):
    """Changes the layers of cs (CompoundStructure of the base type) so that
    its total width is `width` (feet). Raises ValueError if it is not possible.
    1- The structural layer (or the thickest core layer) absorbs the difference:
       the finishes keep their real thickness.
    2- If it would get too thin, all the layers are scaled (membranes stay at 0)."""
    if cs is None:
        raise ValueError("the type has no layers")
    layers = list(cs.GetLayers())
    widths = [cs.GetLayerWidth(i) for i in range(len(layers))]
    solid = [i for i, l in enumerate(layers)
             if l.Function != MaterialFunctionAssignment.Membrane and widths[i] > 0]
    if not solid:
        raise ValueError("the type has no layer with a width")
    min_layer = CompoundStructure.GetMinimumLayerThickness()

    main = cs.StructuralMaterialIndex
    if main not in solid:
        first, last = cs.GetFirstCoreLayerIndex(), cs.GetLastCoreLayerIndex()
        core = [i for i in solid if first <= i <= last] or solid
        main = max(core, key=lambda i: widths[i])
    new_main = widths[main] + width - sum(widths)
    if new_main >= min_layer:
        cs.SetLayerWidth(main, new_main)
        return

    k = width / sum(widths[i] for i in solid)
    if any(widths[i] * k < min_layer for i in solid):
        raise ValueError("{:g} mm is too thin for its layers".format(round(width / MM)))
    for i in solid:
        cs.SetLayerWidth(i, widths[i] * k)


def get_wall_type(base, w_mm, types):
    """Type of the base 'family' with this width: the base itself, an existing
    '<base> (<w>cm)' with the same width, or a new duplicate of the base."""
    width = w_mm * MM
    if abs(base.Width - width) < TOL_DIM:
        return base
    base_name = Element.Name.GetValue(base)
    name = "{} ({:g}cm)".format(base_name, w_mm / 10.0)
    for candidate in [name] + ["{} ({})".format(name, i) for i in range(2, 50)]:
        wall_type = types.get(candidate)
        if wall_type is None:
            cs = base.GetCompoundStructure()
            set_structure_width(cs, width)
            new_type = base.Duplicate(candidate)
            new_type.SetCompoundStructure(cs)
            types[candidate] = new_type
            return new_type
        if wall_type.Kind == WallKind.Basic and abs(wall_type.Width - width) < TOL_DIM:
            return wall_type
    raise ValueError("no free type name for '{}'".format(name))


# ── Door / window types (as in Sync Doors Windows) ─
def type_name(symbol):
    return symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()


def find_parameter(element, bips, names, writable=False):
    """First length parameter found on the element itself (by built-in parameter, then by name)."""
    candidates = [element.get_Parameter(bip) for bip in bips] + [element.LookupParameter(n) for n in names]
    for p in candidates:
        if p and p.StorageType == StorageType.Double and (not writable or not p.IsReadOnly):
            return p
    return None


def read_length(element, bips, names):
    p = find_parameter(element, bips, names)
    return p.AsDouble() if p and p.HasValue else None


def set_length(element, bips, names, value):
    p = find_parameter(element, bips, names, writable=True)
    if p is not None and abs(p.AsDouble() - value) > TOL_DIM:
        p.Set(value)


def families_of(bic):
    """{name: family} of the loadable families of a category."""
    out = {}
    for s in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType():
        f = getattr(s, 'Family', None)
        if f is not None and not f.IsInPlace:
            out[f.Name] = f
    return out


class TargetFamily(object):
    """A door / window family and the types created/reused per width x height.
    Dimensions that are instance parameters are set on the instance instead."""
    def __init__(self, family):
        self.family  = family
        self.symbols = sorted([doc.GetElement(i) for i in family.GetFamilySymbolIds()], key=type_name)
        self.base    = self.symbols[0]
        self.width_on_type  = find_parameter(self.base, BIPS_WIDTH, NAMES_WIDTH, writable=True) is not None
        self.height_on_type = find_parameter(self.base, BIPS_HEIGHT, NAMES_HEIGHT, writable=True) is not None
        self.cache, self.created = {}, []

    def symbol_for(self, width, height):
        key = (int(round(width / MM)) if self.width_on_type else None,
               int(round(height / MM)) if self.height_on_type else None)
        if key not in self.cache:
            symbol = self.base if key == (None, None) else (self._find(width, height) or self._create(key, width, height))
            if not symbol.IsActive:
                symbol.Activate()
            self.cache[key] = symbol
        return self.cache[key]

    def _find(self, width, height):
        for s in self.symbols:
            w = read_length(s, BIPS_WIDTH, NAMES_WIDTH)
            h = read_length(s, BIPS_HEIGHT, NAMES_HEIGHT)
            if ((not self.width_on_type or (w is not None and abs(w - width) <= TOL_DIM)) and
                    (not self.height_on_type or (h is not None and abs(h - height) <= TOL_DIM))):
                return s
        return None

    def _create(self, key, width, height):
        name = " x ".join(str(v) for v in key if v is not None)
        existing = set(type_name(s) for s in self.symbols)
        base_name, i = name, 2
        while name in existing:
            name = "{} ({})".format(base_name, i)
            i += 1
        new_type = self.base.Duplicate(name)
        if self.width_on_type:
            set_length(new_type, BIPS_WIDTH, NAMES_WIDTH, width)
        if self.height_on_type:
            set_length(new_type, BIPS_HEIGHT, NAMES_HEIGHT, height)
        self.symbols.append(new_type)
        self.created.append(name)
        return new_type


# ── Revit ─────────────────────────────────────────
class FailureHandler(IFailuresPreprocessor):
    """Deletes the warnings (overlapping walls...) and resolves the errors
    (the element is deleted) instead of losing the whole block."""
    def __init__(self):
        self.errors = 0

    def PreprocessFailures(self, accessor):
        result = FailureProcessingResult.Continue
        for f in accessor.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(f)
            elif f.HasResolutions():
                accessor.ResolveFailure(f)
                self.errors += 1
                result = FailureProcessingResult.ProceedWithCommit
        return result


class Cancelled(Exception):
    pass


class Progress(object):
    """Percentage on the pyRevit progress bar. A phase maps its work units
    to a range of the bar. Raises Cancelled when the user cancels."""
    def __init__(self, pb):
        self.pb, self.last = pb, -1
        self.phase(0, 100, 1)

    def phase(self, start, end, total):
        self.start, self.span, self.total, self.done = start, end - start, max(total, 1), 0
        self.show()

    def advance(self, n=1):
        self.done += n
        self.show()

    def show(self):
        if self.pb.cancelled:
            raise Cancelled()
        pct = int(self.start + self.span * min(self.done, self.total) / float(self.total))
        if pct != self.last:
            self.last = pct
            self.pb.update_progress(pct, 100)


def run_chunks(name, items, func, progress, units):
    """func(item) for each item, CHUNK per transaction -> [results that still exist].
    Cancel: the current chunk is rolled back, the finished ones are kept."""
    created, failed, errors = [], 0, 0
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        t = Transaction(doc, name)
        handler = FailureHandler()
        options = t.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(handler)
        t.SetFailureHandlingOptions(options)
        t.Start()
        ids = []
        try:
            for item in chunk:
                try:
                    ids.append((item, func(item)))
                except Cancelled:
                    raise
                except Exception:
                    failed += 1
                progress.advance(units)
            t.Commit()
        except Cancelled:
            t.RollBack()
            raise
        errors += handler.errors
        created.extend((item, i) for item, i in ids if doc.GetElement(i))
    return created, failed + errors


def door_swing(inst, view):
    """(hinge, middle of the swing) of the biggest arc of the door in plan, or None."""
    opt = Options()
    opt.View = view
    arcs = list(iter_curves(inst.get_Geometry(opt) or [], (Arc,)))
    if not arcs:
        return None
    big = max(arcs, key=lambda c: c.Radius)
    m = big.Evaluate(0.5, True)
    return (big.Center.X, big.Center.Y), (m.X, m.Y)


def orient_door(inst, op, view):
    """Flips the door until its arc swings to the side and from the jamb of the DWG.
    Works whatever the convention of the family (read from its own arc)."""
    if op['swing'] is None and op['hinge'] is None:
        return
    doc.Regenerate()
    sw = door_swing(inst, view)
    if sw is None:
        return
    if op['swing'] and inst.CanFlipFacing and dot(sub(sw[1], op['center']), op['swing']) < 0:
        inst.flipFacing()
        doc.Regenerate()
        sw = door_swing(inst, view) or sw
    if op['hinge'] and inst.CanFlipHand and dot(sub(sw[0], op['center']), op['hinge']) < 0:
        inst.flipHand()


# Work units (create / commit with the joins / door orientation)
WALL_UNITS, OPENING_UNITS = 3, 3


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- The active view must have a level.
view  = doc.ActiveView
level = view.GenLevel
if not level:
    forms.alert("Active view has no level (use a floor plan).", exitscript=True)

# 2- Form: DWG
cads = {}
for cad in FilteredElementCollector(doc).OfClass(ImportInstance).ToElements():
    cad_type = doc.GetElement(cad.GetTypeId())
    name = Element.Name.GetValue(cad_type) if cad_type else 'CAD'
    cads['{} [{}] - {}'.format(name, 'Link' if cad.IsLinked else 'Import', cad.Id)] = cad
if not cads:
    forms.alert("There are no DWG in this project.", exitscript=True)

picked = forms.SelectFromList.show(sorted(cads), title='Walls From DWG - Pick the DWG',
                                   multiselect=False, button_name='Select')
if not picked:
    script.exit()

with forms.ProgressBar(title='Reading the DWG...', indeterminate=True):
    layers = read_layers(cads[picked])
if not layers:
    forms.alert("The DWG has no lines.", exitscript=True)

# 3- Form: wall type, heights, widths, door / window families
wall_types = {Element.Name.GetValue(wt): wt for wt in FilteredElementCollector(doc).OfClass(WallType)
              if wt.Kind == WallKind.Basic}
if not wall_types:
    forms.alert("There are no basic wall types in this project.", exitscript=True)
form = SettingsForm(wall_types, families_of(BuiltInCategory.OST_Doors), families_of(BuiltInCategory.OST_Windows))
form.ShowDialog()
if not form.result:
    script.exit()
s = form.result

# 4- Form: role of the layers
layer_form = LayerForm(layers)
layer_form.ShowDialog()
if not layer_form.result:
    script.exit()
roles = layer_form.result

# 5- Geometry, types, walls, doors / windows
output.print_md("## Walls From DWG - {}".format(picked))
for role in (ROLE_WALLS, ROLE_DOORS, ROLE_WINDOWS):
    names = sorted(n for n, r in roles.items() if r == role)
    if names:
        output.print_md("- {} layers: {}".format(role, ", ".join(names)))

group = TransactionGroup(doc, "Walls From DWG")
group.Start()
created_ids = []
with forms.ProgressBar(title="Walls From DWG - Center lines... {value}%", cancellable=True) as pb:
    progress = Progress(pb)
    try:
        # 0-10 %: geometry
        progress.phase(0, 1, 2)
        index = build_index(layers, roles)
        progress.advance()
        segs = merge_collinear([(a, b, n) for n, r in roles.items() if r == ROLE_WALLS
                                for a, b in layers[n]['segs']], OFF_TOL)
        progress.advance()
        progress.phase(1, 7, len(segs))
        double, singles = wall_pieces(segs, s['max_width'], index, progress)
        walls = [[sg[0], sg[1], w, ops] for sg, w, ops in double] + [[sg[0], sg[1], s['width'], []] for sg in singles]
        progress.phase(7, 10, len(walls))
        joined = snap_ends(walls, progress)
        # A block less than twice as long as wide that touches no wall is a column / pier
        blocks = set(k for k, w in enumerate(walls) if k not in joined and seg_len(w[:2]) < BLOCK_RATIO * w[2] * MM)
        if blocks:
            output.print_md("- {} short thick blocks that touch no wall (columns / piers): not created.".format(len(blocks)))
        walls = [w for k, w in enumerate(walls) if k not in blocks and seg_len(w[:2]) >= MIN_SEG]
        if not walls:
            output.print_md("- **No walls found** in these layers.")

        # 10-15 %: types (one wall type per width, one door / window type per size)
        pb.title = "Walls From DWG - Types... {value}%"
        widths = sorted(set(w[2] for w in walls))
        openings = [op for w in walls for op in w[3]]
        targets = {'door':   TargetFamily(s['door_family']) if s['door_family'] else None,
                   'window': TargetFamily(s['window_family']) if s['window_family'] else None}
        heights = {'door': s['door_height'], 'window': s['window_height']}
        sizes = sorted(set((op['kind'], op['width']) for op in openings if targets[op['kind']]))
        progress.phase(10, 15, len(widths) + len(sizes))
        types, symbols = {}, {}
        with Transaction(doc, "Walls From DWG - types") as t:
            t.Start()
            existing = {Element.Name.GetValue(wt): wt for wt in FilteredElementCollector(doc).OfClass(WallType)}
            for w in widths:
                try:
                    types[w] = get_wall_type(s['type'], w, existing)
                except Exception as ex:
                    output.print_md("- **{} mm**: no wall type ({}), these walls are not created.".format(w, ex))
                progress.advance()
            for kind, w in sizes:
                try:
                    symbols[(kind, w)] = targets[kind].symbol_for(w * MM, heights[kind])
                except Exception as ex:
                    output.print_md("- **{} {} mm**: no type ({}).".format(kind, w, ex))
                progress.advance()
            t.Commit()
        for w in widths:
            if w in types:
                output.print_md("- **{} mm**: {} walls, type *{}*".format(
                    w, sum(1 for x in walls if x[2] == w), Element.Name.GetValue(types[w])))

        # 15-75 %: walls
        pb.title = "Walls From DWG - Walls... {value}%"
        todo = [w for w in walls if w[2] in types]
        progress.phase(15, 75 if openings else 100, len(todo) * WALL_UNITS)
        z = level.ProjectElevation

        def make_wall(w):
            line = Line.CreateBound(XYZ(w[0][0], w[0][1], z), XYZ(w[1][0], w[1][1], z))
            return Wall.Create(doc, line, types[w[2]].Id, level.Id, s['height'], 0.0, False, s['structural']).Id

        made, lost = run_chunks("Walls From DWG - walls", todo, make_wall, progress, WALL_UNITS)
        created_ids.extend(i for _, i in made)
        if lost:
            output.print_md("- {} walls Revit could not create.".format(lost))

        # 75-100 %: doors / windows in the walls created
        if openings:
            pb.title = "Walls From DWG - Doors / windows... {value}%"
            todo = [(op, i) for w, i in made for op in w[3] if (op['kind'], op['width']) in symbols]
            progress.phase(75, 100, len(todo) * OPENING_UNITS)

            def make_opening(item):
                op, wall_id = item
                symbol = symbols[(op['kind'], op['width'])]
                target = targets[op['kind']]
                inst = doc.Create.NewFamilyInstance(XYZ(op['center'][0], op['center'][1], z), symbol,
                                                    doc.GetElement(wall_id), level, StructuralType.NonStructural)
                if not target.width_on_type:
                    set_length(inst, BIPS_WIDTH, NAMES_WIDTH, op['width'] * MM)
                if not target.height_on_type:
                    set_length(inst, BIPS_HEIGHT, NAMES_HEIGHT, heights[op['kind']])
                p_sill = inst.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
                if p_sill and not p_sill.IsReadOnly:
                    p_sill.Set(s['sill'] if op['kind'] == 'window' else 0.0)
                if op['kind'] == 'door':
                    orient_door(inst, op, view)
                return inst.Id

            done, lost = run_chunks("Walls From DWG - doors / windows", todo, make_opening, progress, OPENING_UNITS)
            created_ids.extend(i for _, i in done)
            for kind in ('door', 'window'):
                found = sum(1 for op in openings if op['kind'] == kind)
                if not found:
                    continue
                if targets[kind] is None:
                    output.print_md("- **{} {}s** found: the walls go on through them, no family chosen.".format(found, kind))
                    continue
                n = sum(1 for (op, _), _ in done if op['kind'] == kind)
                output.print_md("- **{} {}s** of *{}* placed (of {} found){}.".format(
                    n, kind, targets[kind].family.Name, found,
                    ", new types: " + ", ".join(targets[kind].created) if targets[kind].created else ""))
            if lost:
                output.print_md("- {} doors / windows Revit could not place.".format(lost))
    except Cancelled:
        output.print_md("- **Cancelled**: what was already finished is kept.")
group.Assimilate()

# 6- Select what was created
if created_ids:
    uidoc.Selection.SetElementIds(List[ElementId](created_ids))
    output.print_md("**{} elements created and selected.**".format(len(created_ids)))

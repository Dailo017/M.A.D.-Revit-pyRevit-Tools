# -*- coding: utf-8 -*-
__title__   = "MEP\nNetwork"
__doc__     = """Version = 2.0
Date    = 20.10.2026
________________________________________________________________
Description:

Creates networks of ducts and/or pipes from the layers of a DWG:
1- Pick the DWG (linked or imported) used as the starting point.
2- For each layer choose a duct type, a pipe type or nothing,
   plus the system type, the height and the dimensions.
3- Lines drawn with several parallel lines (edges, edges + axis)
   are reduced to their center line. Their width / Ø is read from
   the DWG (inner contour, rounded to the closest size of the
   type), single lines use the size of the form. Reductions are
   added where the width changes.
4- Ends are extended / trimmed so that the network connects
   (elbow = 2, tee = 3, cross = 4), arcs of the DWG are replaced
   by elbows.
5- The placeholders are converted into real ducts / pipes.
6- The system types used are set to 'Performance': no network
   calculation is run by Revit.
________________________________________________________________
How-To:

1. Open a floor plan (the network is created on its level).
2. Click the button and pick the DWG.
3. Assign a type to the layers of the network, the height is
   the middle elevation from the level (mm).
________________________________________________________________
Last Updates:
- [20.10.2026] v2.0 Network created from the layers of a DWG
                    + center line of double lines + height and
                    dimensions per layer
- [05.10.2026] v1.1 Ducts and Pipes share the same code + only
                    matching system types are listed
- [29.06.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
import math

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import (Duct, DuctType, MechanicalSystemType, MechanicalUtils,
                                          DuctSizeSettings, DuctShape, SystemCalculationLevel)
from Autodesk.Revit.DB.Plumbing import Pipe, PipeType, PipingSystemType, PlumbingUtils
from pyrevit import forms, script

#.NET Imports
import clr
clr.AddReference('System')
clr.AddReference('PresentationFramework')
from System.Collections.Generic import List
from System.Windows import Thickness, GridLength, Visibility, FontWeights
from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, ComboBox, TextBox

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

output = script.get_output()

# Tolerances (feet)
POINT_TOL = 0.003        # ~1 mm, same point
OFF_TOL   = 0.033        # ~1 cm, same line (collinear)
ANG_TOL   = 0.01         # rad (~0.6°), parallel
KINK_TOL  = 0.1          # rad (~6°), 2 pieces that meet with a smaller angle go straight on
FOLD_BACK_TOL = 0.05     # cos, an elbow turning more than ~90° (piece going back) is not made
MIN_SEG   = 0.5          # ~15 cm, shorter segments are ignored

# Relative to the plan dimension (width / diameter) of the layer
WIDTH_FACTOR = 1.3       # parallel lines closer than this = same duct
PAIR_FACTOR  = 2.5       # ... up to this if their ends are aligned (drawn wider than the size chosen)
MAX_DRAWN_WIDTH = 6.56   # ~2 m, widest duct whose width is read from its double lines
EDGE_TOL = 0.23          # ~7 cm, closer parallel lines draw the same edge (double contour)
MIN_DUCT_WIDTH = 0.26    # ~8 cm, ... unless 3 of them centered: a small duct with its axis
AXIS_BONUS = 0.05        # edge + axis + edge is preferred to 2 edges when both fit
ECCENTRIC_TOL = 0.1      # ~3 cm, max side offset between 2 pieces of a duct that face each other
MIN_REDUCTION_LEN = 2.0  # ~60 cm, shorter pieces of another width are ignored
TRANSITION_GAP = 1.0     # ~30 cm, room left for a reduction (Revit needs a gap)
SNAP_FACTOR  = 3.5       # single lines: max distance to extend an end (elbows drawn with arcs)
SNAP_MIN     = 1.64      # ~50 cm
SNAP_DRAWN   = 3.0       # double lines: max distance to extend an end, x its own width
FLANGE_ZONE  = 1.0       # ~30 cm, gap a branch may cross to reach its main (flanges)
MIN_LENGTH_FACTOR = 1.2  # double lines: a duct is at least this x its width long (corners: edge + axis)
MIN_SINGLE_WITH_DRAWN = 10.0  # ~3 m, shorter single lines are dropped when there are double lines
MERGE_GAP_MAX = 1.0      # ~30 cm, max gap between 2 collinear lines joined (dashed lines, flanges)

NONE_LABEL = '-- Nothing --'

# Everything that changes between ducts and pipes
MEP_OPTIONS = {
    'Ducts': {'type_cls': DuctType, 'system_cls': MechanicalSystemType,
              'create': Duct.CreatePlaceholder,
              'elbow':  MechanicalUtils.ConnectDuctPlaceholdersAtElbow,
              'tee':    MechanicalUtils.ConnectDuctPlaceholdersAtTee,
              'cross':  MechanicalUtils.ConnectDuctPlaceholdersAtCross,
              'convert': MechanicalUtils.ConvertDuctPlaceholders},
    'Pipes': {'type_cls': PipeType, 'system_cls': PipingSystemType,
              'create': Pipe.CreatePlaceholder,
              'elbow':  PlumbingUtils.ConnectPipePlaceholdersAtElbow,
              'tee':    PlumbingUtils.ConnectPipePlaceholdersAtTee,
              'cross':  PlumbingUtils.ConnectPipePlaceholdersAtCross,
              'convert': PlumbingUtils.ConvertPipePlaceholders},
}

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
    # direction of the group = its longest line (a duct edge), not a slightly skewed neighbour
    out = []
    for _, g in groups:
        longest = max(g, key=seg_len)
        d = unit(sub(longest[1], longest[0]))
        if d[1] < 0 or (abs(d[1]) < 1e-12 and d[0] < 0):
            d = mul(d, -1.0)
        out.append((d, g))
    return out


def to_frame(d, s):
    """Segment -> (offset, t0, t1) in the frame of direction d."""
    n = (-d[1], d[0])
    off = (dot(s[0], n) + dot(s[1], n)) / 2.0
    t0, t1 = sorted((dot(s[0], d), dot(s[1], d)))
    return (off, t0, t1)


def from_frame(d, off, t0, t1):
    n = (-d[1], d[0])
    return (add(mul(d, t0), mul(n, off)), add(mul(d, t1), mul(n, off)))


def drop_symbols(segs):
    """Removes the closed rectangles that are not long (grille boxes, ducts seen
    in section, equipment...), even if other lines touch them: they are symbols,
    not part of the network. Long closed rectangles are pieces of duct: kept."""
    nodes = {}
    for i, s in enumerate(segs):
        k0, k1 = point_key(s[0]), point_key(s[1])
        nodes.setdefault(k0, []).append((i, k1))
        nodes.setdefault(k1, []).append((i, k0))
    direction = lambda i: unit(sub(segs[i][1], segs[i][0]))
    square = lambda i, j: abs(dot(direction(i), direction(j))) < math.sin(KINK_TOL)

    drop = set()
    for i, s in enumerate(segs):
        start, b = point_key(s[0]), point_key(s[1])
        for j, c in nodes.get(b, ()):
            if j == i or not square(i, j):
                continue
            for k, d in nodes.get(c, ()):
                if k in (i, j) or not square(j, k):
                    continue
                for l, e in nodes.get(d, ()):
                    if l in (i, j, k) or e != start or not square(k, l):
                        continue
                    sides = sorted(seg_len(segs[m]) for m in (i, j, k, l))
                    if sides[-1] < 2 * sides[0]:
                        drop.update((i, j, k, l))

    # What is drawn inside a symbol (grille sign...) goes with it
    boxes = []
    for i in drop:
        for j in drop:
            if j > i and point_key(segs[i][0]) in (point_key(segs[j][0]), point_key(segs[j][1])):
                pts = list(segs[i]) + list(segs[j])
                boxes.append((min(p[0] for p in pts), min(p[1] for p in pts),
                              max(p[0] for p in pts), max(p[1] for p in pts)))
    inside = lambda p, b: b[0] - OFF_TOL <= p[0] <= b[2] + OFF_TOL and b[1] - OFF_TOL <= p[1] <= b[3] + OFF_TOL
    return [s for i, s in enumerate(segs)
            if i not in drop and not any(inside(s[0], b) and inside(s[1], b) for b in boxes)]


def merge_collinear(segs, gap):
    """Joins collinear segments that overlap or are separated by less than gap.
    The extreme end points are kept as they are (they may be shared by other segments)."""
    out = []
    for d, group in parallel_groups(segs):
        rows = []
        for s in group:
            a, b = s if dot(s[0], d) <= dot(s[1], d) else (s[1], s[0])
            rows.append(to_frame(d, s) + (a, b))
        rows.sort(key=lambda r: r[0])
        clusters = []
        for r in rows:
            if clusters and r[0] - clusters[-1][0][0] <= OFF_TOL:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for c in clusters:
            c.sort(key=lambda r: r[1])
            start, end, t1 = c[0][3], c[0][4], c[0][2]
            for r in c[1:]:
                if r[1] <= t1 + gap:
                    if r[2] > t1:
                        end, t1 = r[4], r[2]
                else:
                    out.append((start, end))
                    start, end, t1 = r[3], r[4], r[2]
            out.append((start, end))
    return out



def same_duct(a, b, max_width, pair_width):
    """a, b = (offset, t0, t1) of two parallel lines, b[0] >= a[0].
    Close lines that overlap, or lines a bit further whose ends are aligned
    (the edges of a duct drawn wider than the size chosen)."""
    gap = b[0] - a[0]
    overlap = min(a[2], b[2]) - max(a[1], b[1])
    if gap <= max_width:
        return overlap > 0.3 * min(a[2] - a[1], b[2] - b[1])
    return (gap <= pair_width and overlap > 0
            and abs(a[1] - b[1]) <= gap + OFF_TOL and abs(a[2] - b[2]) <= gap + OFF_TOL)


def center_lines(segs, max_width, pair_width):
    """Replaces the parallel lines of one duct / pipe by their center line.
    Lines without a parallel partner are kept, except short ones (end caps)."""
    bands, singles = [], []
    for d, group in parallel_groups(segs):
        rows = sorted(to_frame(d, s) for s in group)

        # Union-find of close parallel lines that overlap
        parent = list(range(len(rows)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if rows[j][0] - rows[i][0] > pair_width:
                    break
                if same_duct(rows[i], rows[j], max_width, pair_width):
                    parent[root(j)] = root(i)

        components = {}
        for i in range(len(rows)):
            components.setdefault(root(i), []).append(rows[i])

        for comp in components.values():
            # Along the path, the set of lines changes (reductions, corners):
            # the ducts are found on each stretch where the same lines are present
            cuts = sorted(set(t for r in comp for t in r[1:3]))
            pieces = []
            for u, v in zip(cuts, cuts[1:]):
                if v - u <= POINT_TOL:
                    continue
                mid = (u + v) / 2.0
                ducts, alone = split_ducts(sorted(r for r in comp if r[1] <= mid <= r[2]), pair_width)
                pieces += [(off, u, v, w) for _, off, w in ducts]
                pieces += [(r[0], u, v, None) for r in alone]
            for off, t0, t1, w in merge_pieces(pieces):
                if w is None:
                    singles.append(from_frame(d, off, t0, t1))
                elif MIN_LENGTH_FACTOR * w <= t1 - t0:  # shorter -> flange, equipment...
                    bands.append((from_frame(d, off, t0, t1), w))

    bands = [b for b in bands if not is_flange(b, bands) and not is_overlapped(b, bands)]

    # Drawn mostly with double lines -> the single lines are end caps, flanges...;
    # otherwise only the short ones are dropped
    if sum(seg_len(b[0]) for b in bands) >= sum(seg_len(s) for s in singles):
        singles = []
    elif bands:
        singles = [s for s in singles if seg_len(s) > max(pair_width, MIN_SINGLE_WITH_DRAWN)]
    return [b[0] for b in bands] + singles, bands


def is_flange(band, bands):
    """Flanges / end caps drawn across a duct look like a short duct: perpendicular
    to it, centered on its axis, near its ends and as long as it is wide."""
    seg, w = band
    d, mid, L = unit(sub(seg[1], seg[0])), mul(add(seg[0], seg[1]), 0.5), seg_len(seg)
    for other, wo in bands:
        if other is seg or abs(L - wo) > 2 * EDGE_TOL:
            continue
        do = unit(sub(other[1], other[0]))
        if abs(dot(d, do)) > math.sin(KINK_TOL):
            continue
        t, off = param_on(other, mid)
        if off <= wo / 4.0 and -2 * wo <= t <= seg_len(other) + 2 * wo:
            return True
    return False


def is_overlapped(band, bands):
    """A shorter duct lying along a longer one (parallel, closer than half a
    width, more than half of it alongside) is a piece of it."""
    seg, w = band
    d, mid, L = unit(sub(seg[1], seg[0])), mul(add(seg[0], seg[1]), 0.5), seg_len(seg)
    for other, wo in bands:
        Lo = seg_len(other)
        if other is seg or Lo <= L:
            continue
        do = unit(sub(other[1], other[0]))
        if abs(cross(d, do)) > math.sin(KINK_TOL) or abs(cross(do, sub(mid, other[0]))) > max(w, wo) / 2.0:
            continue
        t0, t1 = sorted((dot(sub(seg[0], other[0]), do), dot(sub(seg[1], other[0]), do)))
        if min(t1, Lo) - max(t0, 0.0) >= 0.5 * L:
            return True
    return False


def merge_pieces(pieces):
    """Joins the consecutive stretches of the same duct: (offset, t0, t1, width)."""
    out = []
    for off, u, v, w in sorted(pieces, key=lambda p: p[1]):
        for o in out:
            if (abs(o[2] - u) <= POINT_TOL and abs(o[0] - off) <= 3 * OFF_TOL
                    and (o[3] is None) == (w is None) and (w is None or abs(o[3] - w) <= 2 * OFF_TOL)):
                o[2] = v
                break
        else:
            out.append([off, u, v, w])
    return out


def split_ducts(rows, pair_width):
    """rows: (offset, t0, t1) of close parallel lines, sorted by offset. Finds the
    ducts they draw (several ducts can run side by side):
    - lines closer than EDGE_TOL are the same edge (double contour, flange)
    - 3 lines, the middle one centered -> edge + axis + edge
    - 2 lines -> the 2 edges
    The lines of one duct are closer to each other than to the next duct, so the
    split that gives the narrowest ducts wins (a line left alone costs pair_width).
    -> ([(rows, center offset, inner width), ...], rows alone)"""
    edges = []
    for r in rows:
        if edges and r[0] - edges[-1][-1][0] <= EDGE_TOL:
            edges[-1].append(r)
        else:
            edges.append([r])
    left = lambda e: e[-1][0]           # inner line when the edge is on the left
    right = lambda e: e[0][0]           # ... on the right

    def small_duct(e):
        """3 close lines, the middle one centered: a small duct with its axis."""
        if len(e) == 3:
            a, m, b = e[0][0], e[1][0], e[2][0]
            if b - a >= MIN_DUCT_WIDTH and abs((m - a) - (b - m)) <= 2 * OFF_TOL:
                return (e, m, b - a)
        return None

    # best[(i, shared)] = (cost, ducts, alone) once the edges before i are used.
    # shared: edge i is already the right edge of a duct; as it has 2 lines it
    # can also be the left edge of the next one (2 ducts side by side, touching).
    n = len(edges)
    best = {(0, False): (0.0, [], [])}
    def relax(state, cost, ducts, alone):
        if state not in best or cost < best[state][0]:
            best[state] = (cost, ducts, alone)

    for i in range(n + 1):
        for shared in (False, True):
            if (i, shared) not in best or i == n:
                continue
            cost, ducts, alone = best[(i, shared)]
            if shared:
                relax((i + 1, False), cost, ducts, alone)
            else:
                relax((i + 1, False), cost + pair_width, ducts, alone + [max(edges[i], key=lambda r: r[2] - r[1])])
                small = small_duct(edges[i])
                if small:
                    relax((i + 1, False), cost + small[2] / 2.0 - AXIS_BONUS, ducts + [small], alone)
            # edge i + edge j (2 lines), or edge i + axis + edge j (3 lines)
            for j, axis in ((i + 1, None), (i + 2, i + 1)):
                if j >= n or (axis is not None and len(edges[axis]) != 1):
                    continue
                a, b = left(edges[i]), right(edges[j])
                if b - a > pair_width:
                    continue
                # cost = widest gap between the lines of the duct (axis -> half)
                if axis is None:
                    duct, gap = (edges[i] + edges[j], (a + b) / 2.0, b - a), b - a
                else:
                    m = edges[axis][0][0]
                    if abs((m - a) - (b - m)) > max(2 * OFF_TOL, 0.1 * (b - a)):
                        continue
                    duct, gap = (edges[i] + edges[axis] + edges[j], m, b - a), (b - a) / 2.0 - AXIS_BONUS
                relax((j + 1, False), cost + gap, ducts + [duct], alone)
                if len(edges[j]) >= 2:
                    relax((j, True), cost + gap, ducts + [duct], alone)

    result = min((best[k] for k in ((n, False), (n, True)) if k in best), key=lambda o: o[0])
    return result[1], result[2]


def nearest_size(w, sizes):
    """Measured width -> value of the closest size [(compared value, value set), ...]."""
    if not sizes:
        return w
    return min(sizes, key=lambda s: abs(s[0] - w))[1]


def assign_widths(segs, measured, sizes):
    """Width of each segment from the double lines it comes from (None = size
    of the form). The segments are split where the width changes (reductions)."""
    out, widths = [], []
    for s in segs:
        L = seg_len(s)
        d = unit(sub(s[1], s[0]))
        pieces = []
        mid = mul(add(s[0], s[1]), 0.5)
        for m, w in measured:
            dm = unit(sub(m[1], m[0]))
            if w is None or abs(cross(dm, d)) >= math.sin(KINK_TOL):
                continue
            if abs(cross(dm, sub(mid, m[0]))) > max(3 * OFF_TOL, w / 2.0):   # not on its axis
                continue
            a, b = sorted((dot(sub(m[0], s[0]), d), dot(sub(m[1], s[0]), d)))
            a, b = max(a, 0.0), min(b, L)
            if b - a > OFF_TOL:
                pieces.append((a, b, nearest_size(w, sizes)))
        if not pieces:
            out.append(s)
            widths.append(None)
            continue

        cuts = sorted(set([0.0, L] + [t for p in pieces for t in p[:2]]))
        spans = []
        for u, v in zip(cuts, cuts[1:]):
            if v - u > POINT_TOL:
                mid = (u + v) / 2.0
                covering = [p[2] for p in pieces if p[0] - POINT_TOL <= mid <= p[1] + POINT_TOL]
                spans.append([u, v, covering[0] if covering else None])
        # Parts not covered (ends extended to a corner) take the width of their neighbour
        known = [sp[2] for sp in spans if sp[2] is not None]
        last = known[0]
        for sp in spans:
            if sp[2] is None:
                sp[2] = last
            last = sp[2]

        merged = [spans[0]]
        for sp in spans[1:]:
            if abs(sp[2] - merged[-1][2]) < OFF_TOL:
                merged[-1][1] = sp[1]
            else:
                merged.append(sp)
        # Too short to hold a reduction -> takes the width of its longest neighbour
        while len(merged) > 1:
            lengths = [sp[1] - sp[0] for sp in merged]
            k = lengths.index(min(lengths))
            if lengths[k] >= MIN_REDUCTION_LEN:
                break
            n = k - 1 if k == len(merged) - 1 or (k > 0 and lengths[k - 1] >= lengths[k + 1]) else k + 1
            lo, hi = sorted((k, n))
            merged[lo:hi + 1] = [[merged[lo][0], merged[hi][1], merged[n][2]]]
        for u, v, w in merged:
            p0 = s[0] if u <= POINT_TOL else add(s[0], mul(d, u))
            p1 = s[1] if v >= L - POINT_TOL else add(s[0], mul(d, v))
            out.append((p0, p1))
            widths.append(w)
    return out, widths


class SegIndex(object):
    """Uniform grid to find the segments near a point."""
    def __init__(self, segs, cell):
        self.segs, self.cell, self.cells = segs, cell, {}
        for i, s in enumerate(segs):
            x0, x1 = sorted((s[0][0], s[1][0]))
            y0, y1 = sorted((s[0][1], s[1][1]))
            for cx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
                for cy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                    self.cells.setdefault((cx, cy), []).append(i)

    def near(self, pt):
        cx, cy = int(math.floor(pt[0] / self.cell)), int(math.floor(pt[1] / self.cell))
        found = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                found.update(self.cells.get((cx + dx, cy + dy), ()))
        return found


def line_intersection(p, u, q, v):
    """Intersection of the lines p + a*u and q + b*v (None if parallel)."""
    c = cross(u, v)
    if abs(c) < math.sin(ANG_TOL):
        return None
    w = sub(q, p)
    return add(p, mul(u, cross(w, v) / c))


def param_on(s, pt):
    """(t, distance) of pt projected on segment s, t in feet from s[0]."""
    d = unit(sub(s[1], s[0]))
    t = dot(sub(pt, s[0]), d)
    return t, abs(cross(d, sub(pt, s[0])))


def is_on_interior(pt, s, tol=POINT_TOL):
    t, off = param_on(s, pt)
    return off <= tol and tol < t < seg_len(s) - tol


def free_ends(segs):
    """Ends that touch neither another end nor another segment."""
    counts = {}
    for s in segs:
        for p in s:
            counts[point_key(p)] = counts.get(point_key(p), 0) + 1
    index = SegIndex(segs, 2.0)
    free = []
    for i, s in enumerate(segs):
        for e in (0, 1):
            p = s[e]
            if counts[point_key(p)] > 1:
                continue
            if any(is_on_interior(p, segs[j], OFF_TOL) for j in index.near(p) if j != i):
                continue
            free.append((i, e))
    return free


def snap_ends(segs, limits, widths, max_behind):
    """Extends / trims the free ends so that they meet:
    1- two free ends -> intersection of their lines (elbow, arcs of the DWG)
    2- a free end    -> onto another segment (tee)
    limits[i]: how far the ends of segment i may move, widths[i]: its width
    (a branch may also reach the axis of the main it ends on)."""
    segs = [list(s) for s in segs]
    snap = max(limits) if limits else 0.0

    def outward(i, e):
        return unit(sub(segs[i][e], segs[i][1 - e]))

    def reach(i, e, pt, limit=None):
        """Signed distance from the end to pt along the segment (None if too far)."""
        a = dot(sub(pt, segs[i][e]), outward(i, e))
        if -max_behind <= a <= (limit or limits[i]) and seg_len((segs[i][1 - e], pt)) > MIN_SEG / 2:
            return a
        return None

    def keeps_shape(end, pt):
        """Moving this end to pt leaves a segment long enough and not reversed
        (the other end may have moved already)."""
        i, e = end
        other = segs[i][1 - e]
        return seg_len((other, pt)) > MIN_SEG / 2 and dot(sub(pt, other), sub(segs[i][e], other)) > 0

    def tee_target(i, e, index):
        """(distance, point) where the free end meets another segment, or None."""
        p, u = segs[i][e], outward(i, e)
        best = None
        for j in index.near(p):
            if j == i or seg_len(segs[j]) <= POINT_TOL:
                continue
            pt = line_intersection(p, u, segs[j][0], unit(sub(segs[j][1], segs[j][0])))
            if pt is None:
                continue
            t, _ = param_on(segs[j], pt)
            if not (-POINT_TOL <= t <= seg_len(segs[j]) + POINT_TOL):
                continue
            a = reach(i, e, pt, max(limits[i], widths[j] / 2.0 + FLANGE_ZONE))
            if a is not None and keeps_shape((i, e), pt) and (best is None or abs(a) < best[0]):
                best = (abs(a), pt)
        return best

    free = free_ends(segs)
    index = SegIndex(segs, snap)
    tee_first = dict((end, tee_target(end[0], end[1], index)) for end in free)
    closer_tee = lambda end, d: tee_first[end] is not None and tee_first[end][0] < d - OFF_TOL

    # 1- Elbows: pairs of free ends (unless one of them is closer to a tee)
    grid = {}
    for f in free:
        p = segs[f[0]][f[1]]
        grid.setdefault((int(p[0] // snap), int(p[1] // snap)), []).append(f)

    candidates, off_axis = [], []
    for (i, e) in free:
        p = segs[i][e]
        cx, cy = int(p[0] // snap), int(p[1] // snap)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for (j, f) in grid.get((cx + dx, cy + dy), ()):
                    if (j, f) <= (i, e) or j == i:
                        continue
                    pt = line_intersection(p, outward(i, e), segs[j][f], outward(j, f))
                    if pt is None:
                        # Same line, ends facing each other (pieces drawn with a gap,
                        # reduction with one flat side)
                        q = segs[j][f]
                        gap = dot(sub(q, p), outward(i, e))
                        side = abs(cross(outward(i, e), sub(q, p)))
                        if (0 < gap <= limits[i] + limits[j] and dot(outward(i, e), outward(j, f)) < 0
                                and not closer_tee((i, e), gap / 2.0) and not closer_tee((j, f), gap / 2.0)):
                            if side <= ECCENTRIC_TOL:
                                candidates.append((gap, (i, e), (j, f), mul(add(p, q), 0.5)))
                            elif (abs(side - abs(widths[i] - widths[j]) / 2.0) <= ECCENTRIC_TOL
                                  and gap <= 2 * max(widths[i], widths[j])):
                                # reduction with one flat side: axes offset by half the width difference
                                off_axis.append((gap, (i, e), (j, f)))
                        continue
                    if dot(outward(i, e), outward(j, f)) > FOLD_BACK_TOL:    # turn > 90°: not a duct
                        continue
                    a, b = reach(i, e, pt), reach(j, f, pt)
                    if (a is not None and b is not None
                            and not closer_tee((i, e), abs(a)) and not closer_tee((j, f), abs(b))):
                        candidates.append((abs(a) + abs(b), (i, e), (j, f), pt))

    used = set()
    for _, end_a, end_b, pt in sorted(candidates):
        if end_a in used or end_b in used or not (keeps_shape(end_a, pt) and keeps_shape(end_b, pt)):
            continue
        used.update((end_a, end_b))
        segs[end_a[0]][end_a[1]] = pt
        segs[end_b[0]][end_b[1]] = pt

    # Facing pieces whose axes are a bit offset (reduction with one flat side):
    # the ends stay where they are, a reduction is tried between them later
    eccentric = []
    for _, end_a, end_b in sorted(off_axis):
        if end_a in used or end_b in used:
            continue
        used.update((end_a, end_b))
        eccentric.append((tuple(segs[end_a[0]][end_a[1]]), tuple(segs[end_b[0]][end_b[1]]), outward(*end_a)))

    # 2- Tees: remaining free ends onto the closest segment
    index = SegIndex(segs, snap)
    for (i, e) in free:
        if (i, e) in used:
            continue
        best = tee_target(i, e, index)
        if best:
            segs[i][e] = best[1]

    return [tuple(s) for s in segs], eccentric


def split_at_ends(segs):
    """Splits the segments where the end of another one touches them (tees).
    The end is moved exactly onto the segment so that its pieces stay collinear."""
    index = SegIndex(segs, 2.0)
    segs = [list(s) for s in segs]
    cuts = {}
    for i, s in enumerate(segs):
        for e in (0, 1):
            for j in index.near(s[e]):
                if j != i and is_on_interior(s[e], segs[j], OFF_TOL):
                    t, _ = param_on(segs[j], s[e])
                    s[e] = add(segs[j][0], mul(unit(sub(segs[j][1], segs[j][0])), t))
                    cuts.setdefault(j, []).append(s[e])
                    break
    out = []
    for i, s in enumerate(segs):
        pts = sorted(cuts.get(i, []), key=lambda p: param_on(s, p)[0])
        chain = [s[0]] + pts + [s[1]]
        for a, b in zip(chain, chain[1:]):
            if dist(a, b) > POINT_TOL:
                out.append((a, b))
    return out


def drop_stubs(segs, max_len):
    """Removes the short pieces with a free end (lines drawn past a corner)."""
    counts = {}
    for s in segs:
        for p in s:
            counts[point_key(p)] = counts.get(point_key(p), 0) + 1
    return [s for s in segs
            if seg_len(s) > max_len or all(counts[point_key(p)] > 1 for p in s)]


def shift_reductions(segs, widths, width):
    """A tee where the main changes of width: the wider main goes on past the
    branch (taps need a continuous main) and the reduction is moved downstream."""
    size = lambda i: widths[i] if widths[i] is not None else width
    segs, widths = [list(s) for s in segs], list(widths)
    nodes = {}
    for i, s in enumerate(segs):
        for e in (0, 1):
            nodes.setdefault(point_key(s[e]), []).append((i, e))

    for ends in list(nodes.values()):
        if len(ends) != 3:
            continue
        dirs = dict((i, unit(sub(segs[i][1], segs[i][0]))) for i, _ in ends)
        pairs = [(a, b) for k, a in enumerate(ends) for b in ends[k + 1:]
                 if abs(cross(dirs[a[0]], dirs[b[0]])) < math.sin(KINK_TOL)
                 and abs(size(a[0]) - size(b[0])) >= OFF_TOL]
        if len(pairs) != 1:
            continue
        wide, narrow = sorted(pairs[0], key=lambda end: -size(end[0]))
        branch = [end for end in ends if end not in pairs[0]][0]
        p, far = segs[narrow[0]][narrow[1]], segs[narrow[0]][1 - narrow[1]]
        shift = size(branch[0]) / 2.0 + TRANSITION_GAP
        if dist(p, far) <= shift + MIN_REDUCTION_LEN:
            continue
        q = add(p, mul(unit(sub(far, p)), shift))
        segs[narrow[0]][narrow[1]] = q
        segs.append([p, q])                         # wide piece after the tee
        widths.append(widths[wide[0]])
    return [tuple(s) for s in segs], widths


def junctions(segs, widths):
    """Joins again the collinear pieces of the same width that go through a node
    (the main of a tee stays continuous, needed by taps) and lists the connections:
    -> (segments, widths, [(kind, point, ids), ...])
       'elbow' (a, b) / 'tee' (main, branch) / 'cross' (main a, main b)
       'transition' (a, b): collinear, different widths
       'tee3' (main a, main b, branch): the main changes of width at the tee"""
    nodes = {}
    for i, s in enumerate(segs):
        for p in s:
            nodes.setdefault(point_key(p), (p, []))[1].append(i)

    parent = list(range(len(segs)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def angle_below(i, j, tol):
        return abs(cross(unit(sub(segs[i][1], segs[i][0])),
                         unit(sub(segs[j][1], segs[j][0])))) < math.sin(tol)
    def same_width(i, j):
        if widths[i] is None or widths[j] is None:
            return widths[i] is None and widths[j] is None
        return abs(widths[i] - widths[j]) < OFF_TOL

    pending = []
    for p, ids in nodes.values():
        # pairs: go straight on (small kinks of a reduction allowed);
        # joined: really the same duct -> one segment
        pairs = [(i, j) for k, i in enumerate(ids) for j in ids[k + 1:] if angle_below(i, j, KINK_TOL)]
        joined = [pair for pair in pairs if same_width(*pair) and angle_below(pair[0], pair[1], ANG_TOL)]
        rest = [i for i in ids if not any(i in pair for pair in pairs)]
        for i, j in joined:
            parent[root(j)] = root(i)
        if len(ids) == 2 and not pairs:
            far = [segs[i][1] if point_key(segs[i][0]) == point_key(p) else segs[i][0] for i in ids]
            if dot(unit(sub(far[0], p)), unit(sub(far[1], p))) <= FOLD_BACK_TOL:   # else turn > 90°: left open
                pending.append(('elbow', p, tuple(ids)))
        elif len(ids) == 2 and not joined:
            # kinked pieces of the same size: Revit cannot fit a fitting -> left open
            pending.append(('transition' if not same_width(*ids) else 'elbow', p, tuple(ids)))
        elif len(ids) == 3 and len(pairs) == 1 and len(rest) == 1:
            if joined:
                pending.append(('tee', p, (pairs[0][0], rest[0])))
            else:
                pending.append(('tee3', p, pairs[0] + (rest[0],)))
        elif len(ids) == 4 and len(joined) == 2 and not rest:
            pending.append(('cross', p, (joined[0][0], joined[1][0])))

    groups = {}
    for i in range(len(segs)):
        groups.setdefault(root(i), []).append(i)
    groups = list(groups.values())

    # A duct made of several drawn pieces is straightened: direction of its longest
    # piece, position = length weighted mean of the pieces (they are never drawn
    # perfectly aligned -> the duct would be a bit skewed)
    lines = []
    for g in groups:
        d = unit(sub(*reversed(segs[max(g, key=lambda i: seg_len(segs[i]))])))
        n = (-d[1], d[0])
        total = sum(seg_len(segs[i]) for i in g)
        off = sum(seg_len(segs[i]) * dot(mul(add(*segs[i]), 0.5), n) for i in g) / total
        lines.append((add(mul(n, off), (0.0, 0.0)), d))

    # Nodes are moved onto the new lines (corner = intersection of 2 of them)
    group_of = {}
    for k, g in enumerate(groups):
        for i in g:
            group_of[i] = k
    moved = {}      # (node, group) -> new point
    for key, (p, ids) in nodes.items():
        ks = sorted(set(group_of[i] for i in ids), key=lambda k: -sum(seg_len(segs[i]) for i in groups[k]))
        corner = None
        for a in ks:
            for b in ks:
                if a != b and corner is None:
                    c = line_intersection(lines[a][0], lines[a][1], lines[b][0], lines[b][1])
                    if c is not None and dist(c, p) <= 3 * ECCENTRIC_TOL:
                        corner = c
        for k in ks:
            base, d = lines[k]
            # parallel pieces only (reduction): each one keeps its own axis
            moved[(key, k)] = corner or add(base, mul(d, dot(sub(p, base), d)))

    merged, merged_widths, new_index = [], [], {}
    for k, g in enumerate(groups):
        d = lines[k][1]
        pts = [moved[(point_key(p), k)] for i in g for p in segs[i]]
        for i in g:
            new_index[i] = len(merged)
        merged.append((min(pts, key=lambda p: dot(p, d)), max(pts, key=lambda p: dot(p, d))))
        merged_widths.append(widths[g[0]])
    return merged, merged_widths, [(kind, moved[(point_key(p), group_of[ids[0]])], tuple(new_index[i] for i in ids))
                                   for kind, p, ids in pending]


def build_network(segs, width, sizes=None, max_drawn=0.0):
    """DWG segments of one layer -> (center lines, widths, connections).
    width: size of the form, used for single lines. Double lines give their own
    width (rounded to sizes), up to max_drawn."""
    max_width  = width * WIDTH_FACTOR + OFF_TOL
    gap        = width * PAIR_FACTOR + OFF_TOL
    pair_width = max(gap, max_drawn + OFF_TOL)

    segs = [s for s in segs if seg_len(s) > POINT_TOL]
    segs = drop_symbols(segs)
    segs = merge_collinear(segs, min(gap, MERGE_GAP_MAX))
    segs, measured = center_lines(segs, max_width, pair_width)

    # Double lines: they can be short (stubs to terminals), their ends move
    # according to their own width. Single lines: the size of the form.
    drawn = dict(measured)
    segs = [s for s in segs if seg_len(s) >= (MIN_SEG if s in drawn else max(max_width, MIN_SEG))]
    widths = [drawn.get(s, width) for s in segs]
    limits = [SNAP_DRAWN * drawn[s] if s in drawn else max(width * SNAP_FACTOR, SNAP_MIN) for s in segs]
    segs, eccentric = snap_ends(segs, limits, widths, max_width / 2.0)
    segs = merge_collinear(segs, POINT_TOL)
    segs = split_at_ends(segs)
    segs = drop_stubs(segs, max_width / 2.0)
    segs, widths = assign_widths(segs, measured, sizes)
    segs, widths = shift_reductions(segs, widths, width)
    segs, widths, joints = junctions(segs, widths)
    # the ends were straightened a bit: the eccentric reductions follow them
    ends = [p for s in segs for p in s]
    closest = lambda p: min(ends, key=lambda q: dist(p, q)) if ends else p
    return segs, widths, joints + [('eccentric', closest(p), (closest(q), d)) for p, q, d in eccentric]


# ── DWG ───────────────────────────────────────────
def iter_curves(geometry):
    for g in geometry:
        if isinstance(g, GeometryInstance):
            for c in iter_curves(g.GetInstanceGeometry()):
                yield c
        elif isinstance(g, (Line, PolyLine)):
            yield g


def read_layers(cad):
    """{layer name: [((x0, y0), (x1, y1)), ...]} of the lines and polylines."""
    geometry = cad.get_Geometry(Options())
    if geometry is None:
        opt = Options()
        opt.View = doc.ActiveView
        geometry = cad.get_Geometry(opt)

    layers = {}
    for c in iter_curves(geometry or []):
        style = doc.GetElement(c.GraphicsStyleId)
        if style is None or style.GraphicsStyleCategory is None:
            continue
        pts = [c.GetEndPoint(0), c.GetEndPoint(1)] if isinstance(c, Line) else list(c.GetCoordinates())
        segs = layers.setdefault(style.GraphicsStyleCategory.Name, [])
        for a, b in zip(pts, pts[1:]):
            segs.append(((a.X, a.Y), (b.X, b.Y)))
    return layers


# ── Layer form ────────────────────────────────────
LAYER_FORM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="MEP Network - Layers" Width="1010" Height="640"
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

COLUMNS = [('Layer', 230), ('Type', 280), ('System type', 200),
           ('Height (mm)', 85), ('W / Ø (mm)', 85), ('H (mm)', 85)]


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


def to_feet(text, what, layer):
    try:
        value = float(text.replace(',', '.'))
    except ValueError:
        raise ValueError("Layer '{}': {} is not a number.".format(layer, what))
    return UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)


class LayerRow(object):
    """One line of the form: layer -> type, system, height, dimensions."""
    def __init__(self, layer, n_segs, choices, systems):
        self.layer, self.choices, self.systems = layer, choices, systems
        self.grid = make_row_grid()
        put(self.grid, TextBlock(Text="{}  ({})".format(layer, n_segs)), 0)
        self.type_cb   = put(self.grid, ComboBox(), 1)
        self.system_cb = put(self.grid, ComboBox(IsEnabled=False), 2)
        self.height_tb = put(self.grid, TextBox(IsEnabled=False), 3)
        self.dim1_tb   = put(self.grid, TextBox(IsEnabled=False), 4)
        self.dim2_tb   = put(self.grid, TextBox(IsEnabled=False), 5)
        for c in choices:
            self.type_cb.Items.Add(c['label'])
        self.type_cb.SelectedIndex = 0
        self.type_cb.SelectionChanged += self.on_type

    @property
    def choice(self):
        return self.choices[self.type_cb.SelectedIndex]

    def on_type(self, sender, args):
        c = self.choice
        self.system_cb.Items.Clear()
        for name in sorted(self.systems.get(c['kind'], {})):
            self.system_cb.Items.Add(name)
        self.system_cb.SelectedIndex = 0 if self.system_cb.Items.Count else -1

        on = c['kind'] is not None
        for ctrl in (self.system_cb, self.height_tb, self.dim1_tb):
            ctrl.IsEnabled = on
        self.dim2_tb.IsEnabled = on and len(c['sizes']) == 2
        if on and not self.height_tb.Text:
            self.height_tb.Text = '2500'
        if on:
            self.dim1_tb.Text = c['defaults'][0]
            self.dim2_tb.Text = c['defaults'][1] if len(c['sizes']) == 2 else ''

    def settings(self):
        """None if the layer is not used, raises ValueError on wrong input."""
        c = self.choice
        if c['kind'] is None:
            return None
        if self.system_cb.SelectedItem is None:
            raise ValueError("Layer '{}': no system type.".format(self.layer))
        dims = [to_feet(self.dim1_tb.Text, 'W / Ø', self.layer)]
        if len(c['sizes']) == 2:
            dims.append(to_feet(self.dim2_tb.Text, 'H', self.layer))
        if min(dims) <= 0:
            raise ValueError("Layer '{}': dimensions must be > 0.".format(self.layer))
        return {'layer':     self.layer,
                'kind':      c['kind'],
                'type_id':   c['type_id'],
                'system_id': self.systems[c['kind']][self.system_cb.SelectedItem],
                'offset':    to_feet(self.height_tb.Text, 'height', self.layer),
                'width':     dims[0],
                'sizes':     list(zip(c['sizes'], dims)),
                'size_list': c['size_list']}


class LayerForm(forms.WPFWindow):
    def __init__(self, rows):
        forms.WPFWindow.__init__(self, LAYER_FORM_XAML, literal_string=True)
        self.rows, self.result = rows, None

        header = make_row_grid()
        for col, (title, _) in enumerate(COLUMNS):
            put(header, TextBlock(Text=title, FontWeight=FontWeights.Bold), col)
        self.header_cc.Content = header

        for r in rows:
            self.rows_panel.Children.Add(r.grid)
        self.filter_tb.TextChanged += self.on_filter
        self.ok_b.Click += self.on_ok
        self.cancel_b.Click += self.on_cancel

    def on_filter(self, sender, args):
        text = self.filter_tb.Text.lower()
        for r in self.rows:
            r.grid.Visibility = Visibility.Visible if text in r.layer.lower() else Visibility.Collapsed

    def on_ok(self, sender, args):
        try:
            result = [s for s in (r.settings() for r in self.rows) if s]
        except ValueError as ex:
            forms.alert(str(ex))
            return
        if not result:
            forms.alert("Assign a type to at least one layer.")
            return
        self.result = result
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()


def duct_size_list(shape):
    """[(size, size), ...] of the duct sizes of the project for this shape."""
    try:
        sizes = DuctSizeSettings.GetDuctSizeSettings(doc)[shape]
        return sorted(set((s.NominalDiameter, s.NominalDiameter) for s in sizes if s.UsedInSizeLists))
    except Exception:
        return []


def pipe_size_list(pipe_type):
    """[(outer diameter, nominal diameter), ...] of the segments of the pipe type
    (the DWG draws the outer diameter)."""
    out = set()
    try:
        rpm = pipe_type.RoutingPreferenceManager
        for i in range(rpm.GetNumberOfRules(RoutingPreferenceRuleGroupType.Segments)):
            segment = doc.GetElement(rpm.GetRule(RoutingPreferenceRuleGroupType.Segments, i).MEPPartId)
            if segment:
                out.update((s.OuterDiameter, s.NominalDiameter) for s in segment.GetSizes() if s.UsedInSizeLists)
    except Exception:
        pass
    return sorted(out)


def get_type_choices():
    """Duct and pipe types of the project with their size parameters."""
    choices = [{'label': NONE_LABEL, 'kind': None}]
    for kind, label in (('Ducts', 'Duct'), ('Pipes', 'Pipe')):
        types = FilteredElementCollector(doc).OfClass(MEP_OPTIONS[kind]['type_cls']).ToElements()
        for t in sorted(types, key=lambda x: Element.Name.GetValue(x)):
            if kind == 'Pipes':
                sizes, defaults = [BuiltInParameter.RBS_PIPE_DIAMETER_PARAM], ['50']
                size_list = pipe_size_list(t)
            elif t.Shape == ConnectorProfileType.Round:
                sizes, defaults = [BuiltInParameter.RBS_CURVE_DIAMETER_PARAM], ['250']
                size_list = duct_size_list(DuctShape.Round)
            else:
                sizes = [BuiltInParameter.RBS_CURVE_WIDTH_PARAM, BuiltInParameter.RBS_CURVE_HEIGHT_PARAM]
                defaults = ['400', '200']
                size_list = duct_size_list(DuctShape.Oval if t.Shape == ConnectorProfileType.Oval
                                           else DuctShape.Rectangular)
            choices.append({'label': '{}: {}'.format(label, Element.Name.GetValue(t)),
                            'kind': kind, 'type_id': t.Id,
                            'sizes': sizes, 'defaults': defaults, 'size_list': size_list})
    return choices


def group_layers(settings):
    """Layers with the same type, system, height and size make one network:
    a duct drawn on several layers of the DWG gets connected."""
    groups = {}
    for s in settings:
        key = (s['kind'], str(s['type_id']), str(s['system_id']), round(s['offset'], 4),
               tuple(round(v, 4) for _, v in s['sizes']))
        if key in groups:
            groups[key]['layers'].append(s['layer'])
        else:
            groups[key] = dict(s, layers=[s['layer']])
    for g in groups.values():
        g['layer'] = ' + '.join(g['layers'])
    return list(groups.values())


def get_systems():
    return {kind: {Element.Name.GetValue(e): e.Id
                   for e in FilteredElementCollector(doc).OfClass(opt['system_cls']).ToElements()}
            for kind, opt in MEP_OPTIONS.items()}


# ── Revit network ─────────────────────────────────
class FailureHandler(IFailuresPreprocessor):
    """Deletes the warnings and resolves the errors (e.g. a fitting that
    cannot be sized is deleted) instead of losing the whole layer."""
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


def placeholders(kind, exclude=None):
    cls = Duct if kind == 'Ducts' else Pipe
    collector = FilteredElementCollector(doc).OfClass(cls)
    if exclude:
        collector = collector.Excluding(List[ElementId](exclude))
    return [e for e in collector.ToElements() if e.IsPlaceholder]


def flat(ph):
    curve = ph.Location.Curve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    return ((p0.X, p0.Y), (p1.X, p1.Y))


class LivePlaceholders(object):
    """Placeholders of the network with a grid index. A connection can replace
    placeholders -> the index is rebuilt only when a lookup fails."""
    def __init__(self, kind, existing):
        self.kind, self.existing = kind, existing
        self.refresh()

    def refresh(self):
        self.phs = placeholders(self.kind, self.existing)
        self.index = SegIndex([flat(ph) for ph in self.phs], 2.0)

    def near(self, pt):
        return [self.phs[i] for i in self.index.near(pt) if self.phs[i].IsValidObject]

    def find(self, finder, pt, d, skip=None):
        found = finder(self.near(pt), pt, d, skip)
        if found is None:
            self.refresh()
            found = finder(self.near(pt), pt, d, skip)
        return found


def is_parallel(ph, d):
    s = flat(ph)
    return abs(cross(unit(sub(s[1], s[0])), d)) < math.sin(ANG_TOL)


def free_connector(phs, pt, d, skip=None):
    """Open end connector at pt of a placeholder / curve with direction d
    (skip: connector already used)."""
    for ph in phs:
        if not is_parallel(ph, d) or (skip is not None and ph.Id == skip.Owner.Id):
            continue
        for c in ph.ConnectorManager.Connectors:
            if (c.ConnectorType == ConnectorType.End and not c.IsConnected
                    and dist((c.Origin.X, c.Origin.Y), pt) < OFF_TOL):
                return c
    return None


def through(phs, pt, d, skip=None):
    """Placeholder with direction d that goes through pt (not at its ends)."""
    for ph in phs:
        if is_parallel(ph, d) and is_on_interior(pt, flat(ph), OFF_TOL):
            return ph
    return None


def leave_room_for_transitions(segs, widths, joints, width):
    """Revit can neither convert nor join two placeholders of different sizes
    that end at the same point -> the narrower one is moved back by TRANSITION_GAP.
    -> [(wide end, its direction, narrow end, its direction), ...]"""
    size = lambda i: widths[i] if widths[i] is not None else width
    transitions = []
    for kind, pt, ids in joints:
        if kind != 'transition':
            continue
        wide, narrow = sorted(ids, key=size, reverse=True)
        wide_end = min(segs[wide], key=lambda q: dist(q, pt))     # the 2 ends may differ a bit
        e = 0 if dist(segs[narrow][0], pt) < dist(segs[narrow][1], pt) else 1
        start, far = segs[narrow][e], segs[narrow][1 - e]
        if dist(start, far) > TRANSITION_GAP + MIN_SEG:
            segs[narrow][e] = add(start, mul(unit(sub(far, start)), TRANSITION_GAP))
        transitions.append((wide_end, unit(sub(segs[wide][1], segs[wide][0])),
                            segs[narrow][e], unit(sub(far, segs[narrow][e]))))
    return transitions


def add_transitions(new_ids, transitions):
    """Reductions between the converted ducts / pipes of different sizes."""
    curves = [e for e in (doc.GetElement(i) for i in new_ids) if isinstance(e, MEPCurve)]
    index = SegIndex([flat(c) for c in curves], 2.0)
    near = lambda pt: [curves[i] for i in index.near(pt)]
    ok = 0
    for pa, da, pb, db in transitions:
        ca = free_connector(near(pa), pa, da)
        cb = ca and free_connector(near(pb), pb, db, ca)
        try:
            if cb and doc.Create.NewTransitionFitting(ca, cb):
                ok += 1
        except Exception:
            pass
    return ok


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


# Work units per segment / connection (relative times measured on a real DWG)
CREATE_UNITS, JOINT_UNITS, CONVERT_UNITS, COMMIT_UNITS = 1, 1, 20, 7

def network_units(network):
    return len(network[0]) * (CREATE_UNITS + CONVERT_UNITS + COMMIT_UNITS) + len(network[2]) * JOINT_UNITS


def create_network(network, s, level, progress):
    """Placeholders on the segments -> connections -> real ducts / pipes.
    Segments with a width read from the DWG use it, the others the size of the form."""
    segs, widths, joints = network
    segs = [list(sg) for sg in segs]
    transitions = leave_room_for_transitions(segs, widths, joints, s['width'])
    transitions += [(p, d, q, mul(d, -1.0)) for kind, p, (q, d) in
                    (j for j in joints if j[0] == 'eccentric')]
    opt = MEP_OPTIONS[s['kind']]
    z = level.ProjectElevation + s['offset']
    existing = [e.Id for e in placeholders(s['kind'])]
    for (p0, p1), width in zip(segs, widths):
        ph = opt['create'](doc, s['system_id'], s['type_id'], level.Id,
                           XYZ(p0[0], p0[1], z), XYZ(p1[0], p1[1], z))
        sizes = list(s['sizes'])
        if width is not None:
            sizes[0] = (sizes[0][0], width)
        for bip, value in sizes:
            param = ph.get_Parameter(bip)
            if param and not param.IsReadOnly:
                param.Set(value)
        progress.advance(CREATE_UNITS)
    doc.Regenerate()

    # Elbows first, then tees / crosses on the (continuous) mains. A connection
    # can replace placeholders -> they are looked up again by their geometry.
    # Reductions are made after the conversion (no API for placeholders).
    joints = sorted(joints, key=lambda j: j[0] != 'elbow')
    direction = lambda i: unit(sub(segs[i][1], segs[i][0]))
    live = LivePlaceholders(s['kind'], existing)
    ok = failed = 0
    for kind, pt, ids in joints:
        if kind in ('transition', 'eccentric'):
            continue
        dirs = [direction(i) for i in ids]
        try:
            if kind == 'elbow':
                ca = live.find(free_connector, pt, dirs[0])
                cb = live.find(free_connector, pt, dirs[1])
                done = ca and cb and opt['elbow'](doc, ca, cb)
            elif kind == 'tee':
                main = live.find(through, pt, dirs[0])
                branch = live.find(free_connector, pt, dirs[1])
                done = main and branch and opt['tee'](doc, main.Id, branch.Owner.Id)
            elif kind == 'tee3':
                ca = live.find(free_connector, pt, dirs[0])
                cb = ca and live.find(free_connector, pt, dirs[1], ca)
                cc = live.find(free_connector, pt, dirs[2])
                done = ca and cb and cc and opt['tee'](doc, ca, cb, cc)
            else:
                ma, mb = live.find(through, pt, dirs[0]), live.find(through, pt, dirs[1])
                done = ma and mb and opt['cross'](doc, ma.Id, mb.Id)
        except Exception:
            done = False
        if done:
            ok += 1
        else:
            failed += 1
        progress.advance(JOINT_UNITS)

    new_ids = list(opt['convert'](doc, List[ElementId]([ph.Id for ph in placeholders(s['kind'], existing)])) or [])
    progress.advance(len(segs) * CONVERT_UNITS)

    if transitions:
        done = add_transitions(new_ids, transitions)
        ok += done
        failed += len(transitions) - done
        progress.advance(len(transitions) * JOINT_UNITS)
    return new_ids, ok, failed


def off_plan(new_ids, segs):
    """Ducts / pipes left by Revit outside the center lines (pieces of a fitting
    that could not be created): they are deleted, the ends stay open."""
    out = []
    for i in new_ids:
        e = doc.GetElement(i)
        if not isinstance(e, MEPCurve):
            continue
        a, b = flat(e)
        if not any(max(param_on(s, a)[1], param_on(s, b)[1]) < 3 * OFF_TOL and
                   min(param_on(s, a)[0], param_on(s, b)[0]) >= -TRANSITION_GAP and
                   max(param_on(s, a)[0], param_on(s, b)[0]) <= seg_len(s) + TRANSITION_GAP
                   for s in segs):
            out.append(i)
    return out


def stop_system_calculations(settings):
    """The system types used are set to 'Performance': Revit does not run the
    network calculations (flow, pressure...) in the background for them."""
    changed = []
    with Transaction(doc, "MEP Network - no system calculations") as t:
        t.Start()
        for system_id in set(s['system_id'] for s in settings):
            system_type = doc.GetElement(system_id)
            if system_type.CalculationLevel != SystemCalculationLevel.Performance:
                system_type.CalculationLevel = SystemCalculationLevel.Performance
                changed.append(Element.Name.GetValue(system_type))
        t.Commit()
    return changed


def above_view_range(view, offset):
    """True if the height (from the level of the view) is above the top of its view range."""
    try:
        vr = view.GetViewRange()
        if vr.GetLevelId(PlanViewPlane.TopClipPlane) != view.GenLevel.Id:
            return False
        return offset > vr.GetOffset(PlanViewPlane.TopClipPlane)
    except Exception:
        return False


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- The active view must have a level.
level = doc.ActiveView.GenLevel
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

picked = forms.SelectFromList.show(sorted(cads), title='MEP Network - Pick the DWG',
                                   multiselect=False, button_name='Select')
if not picked:
    script.exit()

with forms.ProgressBar(title='Reading the DWG...', indeterminate=True):
    layers = read_layers(cads[picked])
if not layers:
    forms.alert("The DWG has no lines.", exitscript=True)

# 3- Form: type, system, height and dimensions per layer
choices = get_type_choices()
if len(choices) == 1:
    forms.alert("There are no duct or pipe types in this project.", exitscript=True)
systems = get_systems()

form = LayerForm([LayerRow(name, len(layers[name]), choices, systems)
                  for name in sorted(layers, key=lambda x: x.lower())])
form.ShowDialog()
if not form.result:
    script.exit()

# 4- Center lines, placeholders, connections and conversion (one transaction per
#    network = the layers with the same settings)
output.print_md("## MEP Network - {}".format(picked))
settings = group_layers(form.result)
group = TransactionGroup(doc, "MEP Network from DWG")
group.Start()
stopped = stop_system_calculations(settings)
if stopped:
    output.print_md("- System calculations set to *Performance* (no network calculation): {}".format(", ".join(stopped)))
created_ids = []
with forms.ProgressBar(title="MEP Network - Center lines... {value}%", cancellable=True) as pb:
    progress = Progress(pb)
    try:
        # 0-10 %: geometry of all the networks
        progress.phase(0, 10, len(settings))
        networks = []
        for s in settings:
            networks.append(build_network(sum((layers[n] for n in s['layers']), []), s['width'], s['size_list'],
                                          MAX_DRAWN_WIDTH if s['kind'] == 'Ducts' else 0.0))
            progress.advance()

        # 10-100 %: Revit (placeholders, connections, conversion, commit)
        progress.phase(10, 100, sum(network_units(n) for n in networks))
        for s, network in zip(settings, networks):
            if not network[0]:
                output.print_md("- **{}**: no lines to convert.".format(s['layer']))
                continue
            pb.title = "MEP Network - {}... {{value}}%".format(s['layer'].replace('{', '{{').replace('}', '}}'))

            t = Transaction(doc, "MEP Network - {}".format(s['layer']))
            handler = FailureHandler()
            options = t.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(handler)
            t.SetFailureHandlingOptions(options)
            t.Start()
            try:
                new_ids, ok, failed = create_network(network, s, level, progress)
                t.Commit()
                progress.advance(len(network[0]) * COMMIT_UNITS)

                new_ids = [i for i in new_ids if doc.GetElement(i)]
                leftovers = off_plan(new_ids, network[0])
                if leftovers:
                    with Transaction(doc, "MEP Network - cleanup") as tc:
                        tc.Start()
                        doc.Delete(List[ElementId](leftovers))
                        tc.Commit()
                created_ids.extend(i for i in new_ids if doc.GetElement(i))
                output.print_md("- **{}**: {} segments ({} sized from the DWG), {} connections ({} failed), "
                                "{} fittings Revit could not make (left open).".format(
                    s['layer'], len(network[0]), sum(1 for w in network[1] if w is not None),
                    ok, failed, handler.errors + len(leftovers)))
                if above_view_range(doc.ActiveView, s['offset']):
                    output.print_md("  - **Not visible in this view**: the height is above the top of its view range.")
            except Cancelled:
                t.RollBack()
                raise
            except Exception as ex:
                t.RollBack()
                progress.advance(network_units(network))
                output.print_md("- **{}**: error, nothing created ({}).".format(s['layer'], ex))
    except Cancelled:
        output.print_md("- **Cancelled**: the layers already finished are kept.")
group.Assimilate()

# 5- Select what was created (also the elements hidden by the view range)
if created_ids:
    uidoc.Selection.SetElementIds(List[ElementId](created_ids))
    output.print_md("**{} ducts / pipes created and selected.**".format(len(created_ids)))

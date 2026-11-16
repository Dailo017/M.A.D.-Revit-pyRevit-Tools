# -*- coding: utf-8 -*-
__title__   = "Split\nWalls"
__doc__     = """Version = 2.6
Date    = 14.11.2026
________________________________________________________________
Description:

Splits each selected wall into one independent wall per layer
thicker than 5 cm (plaster, membranes... are ignored).

BASIC (compound) walls:
1- One wall per layer, placed exactly at the layer position.
   The original wall becomes one of the layers (it keeps its id,
   tags and dimensions), the others are new walls.
2- Doors, windows and wall openings are copied into EVERY layer
   wall, so deleting one of the new walls keeps the openings in
   the others.
3- Other hosted elements (fixtures...) are kept only in the
   layer closest to them.

STACKED walls:
1- For each member of the stack, one NEW basic wall per layer,
   with the position, base / top constraints and height of the
   member.
2- Each new wall gets a copy of the doors / windows that cut
   that member in the original (same type, parameters, sill
   and orientation), and of its rectangular Wall Openings.

CORNERS: when two split walls meet in an L, each layer is
extended / trimmed to wrap around the corner with the matching
layer of the other wall (structure with structure, then the
layers outside / inside of it in order).
When a split wall ends against another split wall (T), its
layers stop at the face of the other wall.

Layer types are created (or reused) per layer, named
"<Material> (<width>cm)". Only the layers with a structural
function keep the "Structural" flag.

Each wall is processed in its own transaction: if one wall
fails, the others are still split and the error is reported.
________________________________________________________________
How-To:

1. Select the walls (before or after clicking the button).
   Select both walls of a corner to get it cleaned up.
2. Review the report.
________________________________________________________________
Last Updates:
- [14.11.2026] v2.6 Wall ends checked on the real geometry:
                    - the footprint of every wall (split, or next to
                      a split wall) is measured before splitting; at
                      the end each wall end must be where it was;
                    - walls ending against a split wall (T) are
                      joined to the layer that has the face they
                      ended against;
                    - an end that Revit cannot join without moving
                      it is left unjoined, exactly where it was (it
                      used to stay at the old wall centerline);
                    - checked again after Revit joins the walls on
                      commit;
                    - joins of stacked walls released on the stacked
                      wall (its members follow it).
- [13.11.2026] v2.5 No wall moves anymore:
                    - layers measured on the real exterior face (the
                      location curve is the wall centerline even
                      with another Location Line: layers were
                      shifted half the wall width);
                    - joins of the layer walls AND of the walls
                      joined to them (T, L) released while splitting,
                      so they are not dragged; allowed again at the
                      end, except when joining would move a wall.
- [17.10.2026] v2.4 Layers < 5 cm ignored in basic walls too,
                    layer-to-layer corners (L and T), original
                    basic wall reused as a layer, faster (new
                    layers created in place, one regeneration
                    for all the doors / windows of a wall).
                    Uniform openings removed: Revit deleted the
                    doors / windows they left with nothing to cut.
- [17.10.2026] v2.3 Stacked walls rebuilt: new basic walls per
                    layer > 5 cm, doors / windows recreated,
                    uniform through openings measured on the
                    original geometry.
- [17.10.2026] v2.0 Stacked walls, openings copied into every
                    layer, multi-selection safe (one transaction
                    per wall), exact layer position for any
                    location line, report.
- [05.10.2026] v1.1 Cleanup + selection before transaction
- [11.02.2026] v1.0 First release
________________________________________________________________
Author: Mohamed Mostafa Bedair, Joven Mark Gumana, Erik Frits,
        Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
import re
import traceback

import clr
clr.AddReference('System')
from System.Collections.Generic import List

from Autodesk.Revit.DB import (Arc, BuiltInCategory, BuiltInParameter, CompoundStructure, CompoundStructureLayer,
                               CylindricalFace, Element, ElementClassFilter, ElementId, ElementTransformUtils,
                               FailureProcessingResult, FailureSeverity, FamilyInstance, FilteredElementCollector,
                               HostObjectUtils, IFailuresPreprocessor, Line, LocationPoint, MaterialFunctionAssignment,
                               BoundingBoxIntersectsFilter, LocationCurve, Outline,
                               Opening, Options, PlanarFace, ShellLayerType, Solid, StorageType,
                               Transaction, TransactionGroup, TransactionStatus, Transform, Wall, WallKind, WallType,
                               WallUtils, XYZ)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document
output = script.get_output()

FT_TO_CM  = 30.48
MIN_LAYER = 5 / FT_TO_CM  # feet (5 cm)  thinner layers (plaster, membranes...) are ignored
TOL_Z     = 0.033       # feet (~1 cm)  vertical tolerance for stacked members / inserts
TOL_DIM   = 0.0003      # feet (~0.1 mm) width tolerance to reuse a layer type
TOL_END   = 0.0033      # feet (~1 mm)  a wall end further than this from where it was has moved

# Instance parameters not copied when a door / window is recreated (derived from others)
SKIP_PARAMS = set([BuiltInParameter.INSTANCE_HEAD_HEIGHT_PARAM])

# Wall instance parameters copied from the stacked wall to the new walls
WALL_PARAMS = [BuiltInParameter.PHASE_CREATED, BuiltInParameter.PHASE_DEMOLISHED,
               BuiltInParameter.WALL_ATTR_ROOM_BOUNDING, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
               BuiltInParameter.ELEM_PARTITION_PARAM]

# Hosted categories copied into every layer wall (they cut the wall)
OPENING_CATS = [BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows, BuiltInCategory.OST_GenericModel]
OPENING_CAT_IDS = set(ElementId(c).ToString() for c in OPENING_CATS)

# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝
#==================================================
class WallSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Wall) and elem.WallType.Kind != WallKind.Curtain

    def AllowReference(self, ref, point):
        return False


class SilentFailures(IFailuresPreprocessor):
    """Deletes warnings (overlaps, duplicate marks...) and applies the default resolution to errors."""
    def PreprocessFailures(self, fa):
        resolved = False
        for f in fa.GetFailureMessages():
            sev = f.GetSeverity()
            if sev == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            elif sev == FailureSeverity.Error and f.HasResolutions():
                fa.ResolveFailure(f)
                resolved = True
        if resolved:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def get_name(elem):
    return Element.Name.GetValue(elem)


def sanitize(name):
    """Removes the characters Revit does not accept in type names."""
    return re.sub(r'[\\:{}\[\]|;<>?`~]', '-', name).strip()


def get_selected_walls():
    """Pre-selection if any, otherwise pick. Stacked members are replaced by their stacked wall."""
    elems = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    walls = [e for e in elems if WallSelectionFilter().AllowElement(e)]
    if not walls:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, WallSelectionFilter(), "Select the walls to split")
        except OperationCanceledException:
            script.exit()
        walls = [doc.GetElement(r) for r in refs]

    result, seen = [], set()
    for w in walls:
        if w.IsStackedWallMember:
            w = doc.GetElement(w.StackedWallOwnerId)
        if w.Id.ToString() not in seen:
            seen.add(w.Id.ToString())
            result.append(w)
    return result


def get_layers(cs, min_width):
    """Layers to split (exterior -> interior) as [(layer, offset_from_exterior_face)].
    Layers thinner than min_width are ignored; if all of them are thin, the thickest one is kept."""
    layers, acc = [], 0.0
    for layer in cs.GetLayers():
        layers.append((layer, acc))
        acc += layer.Width
    thick = [l for l in layers if l[0].Width >= min_width]
    if not thick and layers:
        thick = [max(layers, key=lambda l: l[0].Width)]
    return thick


def ext_face_from_key_ref(wall, cs):
    """Distance (along wall.Orientation) from the location curve to the exterior face, using the Location Line."""
    widths = [l.Width for l in cs.GetLayers()]
    total  = sum(widths)
    first, last = cs.GetFirstCoreLayerIndex(), cs.GetLastCoreLayerIndex()
    ext_shell = sum(widths[:first]) if first >= 0 else 0.0
    int_shell = sum(widths[last + 1:]) if last >= 0 else 0.0

    p   = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    key = p.AsInteger() if p else 0
    # Position of the location line measured from the wall centerline towards the exterior
    key_pos = {0: 0.0,                                  # Wall Centerline
               1: (int_shell - ext_shell) / 2.0,        # Core Centerline
               2: total / 2.0,                          # Finish Face: Exterior
               3: -total / 2.0,                         # Finish Face: Interior
               4: total / 2.0 - ext_shell,              # Core Face: Exterior
               5: -total / 2.0 + int_shell}.get(key, 0.0)  # Core Face: Interior
    return total / 2.0 - key_pos


def ext_face_from_geometry(wall, curve, normal):
    """Same as ext_face_from_key_ref but measured on the real exterior face (used for stacked members)."""
    try:
        refs = HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)
    except Exception:
        return None
    p0 = curve.GetEndPoint(0)
    for ref in refs:
        face = wall.GetGeometryObjectFromReference(ref)
        if isinstance(curve, Line) and isinstance(face, PlanarFace):
            if abs(face.FaceNormal.DotProduct(normal)) > 0.99:
                return (face.Origin - p0).DotProduct(normal)
        elif isinstance(curve, Arc) and isinstance(face, CylindricalFace):
            try:
                radius = face.get_Radius(0).GetLength()
            except Exception:
                return None
            outwards = normal.DotProduct(p0 - curve.Center) > 0
            return (radius - curve.Radius) if outwards else (curve.Radius - radius)
    return None


def offset_curve(curve, dist, normal):
    """Offsets the curve 'dist' towards 'normal' (exterior direction at the start point)."""
    if abs(dist) < 1e-9:
        return curve
    new_curve = curve.CreateOffset(dist, XYZ.BasisZ)
    if (new_curve.GetEndPoint(0) - curve.GetEndPoint(0)).DotProduct(normal) * dist < 0:
        new_curve = curve.CreateOffset(-dist, XYZ.BasisZ)
    return new_curve


def move_to_curve(wall, target, normal):
    """Moves the wall (Location Line = Wall Centerline) and its inserts so its centerline is 'target'."""
    current = wall.Location.Curve
    if isinstance(current, Line):
        dist = (target.GetEndPoint(0) - current.GetEndPoint(0)).DotProduct(normal)
        if abs(dist) > 1e-6:
            ElementTransformUtils.MoveElement(doc, wall.Id, normal.Multiply(dist))
    else:
        dz = current.GetEndPoint(0).Z - target.GetEndPoint(0).Z
        wall.Location.Curve = target.CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, dz)))


# ── Real geometry (footprint) ─────────────────────────
def plan_segments(wall):
    """Outline of the horizontal faces of the wall solids as segments [(XYZ, XYZ)]: seen in plan they draw
    its real footprint, with the extensions / trims of its joins (the location curve only goes up to the
    join point). Taken from the loops of the faces, which are closed: Solid.Edges does not return the
    edges of the wall ends that are joined to another wall."""
    segs = []
    geom = wall.get_Geometry(Options())
    if geom is None:
        return segs
    for obj in geom:
        if isinstance(obj, Solid) and obj.Volume > 1e-9:
            for face in obj.Faces:
                if isinstance(face, PlanarFace) and abs(face.FaceNormal.Z) > 0.5:
                    for loop in face.GetEdgesAsCurveLoops():
                        for edge in loop:
                            pts = list(edge.Tessellate())
                            segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return segs


def reach(segs, origin, d, n, c):
    """(min, max) distance along d - from origin - covered by the footprint on the line parallel to d
    at distance c towards n: where the wall really starts and ends on that line. None if it misses."""
    low, high = None, None
    for a, b in segs:
        ca, cb = (a - origin).DotProduct(n) - c, (b - origin).DotProduct(n) - c
        if (ca > 0) == (cb > 0):
            continue
        t = ca / (ca - cb)
        s = (a - origin).DotProduct(d) * (1 - t) + (b - origin).DotProduct(d) * t
        low  = s if low is None else min(low, s)
        high = s if high is None else max(high, s)
    return None if low is None else (low, high)


def footprints(wall):
    """{wall id: plan_segments} of the wall, or of each member of a stacked wall."""
    members = [doc.GetElement(i) for i in wall.GetStackedWallMemberIds()] if wall.IsStackedWall else [wall]
    return dict((m.Id.ToString(), plan_segments(m)) for m in members)


# ── Joins ─────────────────────────────────────────────
# Wall ends whose join was disallowed while splitting: {wall id: (wall, set of ends)}
FREED = {}
# Layer walls: {wall id: {"wall", "origin", "d", "n", "c", "reach"}} where the footprint of the original
# wall started / ended on the centerline of the layer (line at distance c of origin, see reach)
LAYER_ENDS = {}
# Ends of the walls NOT split around the split walls: {(wall id, end): {...}} where they really ended
# before splitting (see track_end)
NEIGHBORS = {}
# Ends of the layer walls set by fix_corners: {(wall id, end)}
CLEANED = set()
# plan_segments of the walls measured before splitting: {wall id: segments} (emptied once they are measured)
SEGMENTS = {}


def was_allowed(wall, end):
    """True if the join of that end was allowed before the script disallowed it."""
    return WallUtils.IsWallJoinAllowedAtEnd(wall, end) or end in FREED.get(wall.Id.ToString(), (None, ()))[1]


def free_ends(wall, source=None, curve=None):
    """Disallows the joins at both ends of the wall, so changing its type / location line or moving it
    does not drag the walls joined to it. They are allowed again by restore_joins (at the very end),
    except the ends that were already disallowed in 'source' (the wall it replaces, 'curve' = its curve
    if it has not been regenerated yet)."""
    for end in (0, 1):
        if source is None:
            restore = WallUtils.IsWallJoinAllowedAtEnd(wall, end)
        else:
            point   = (wall.Location.Curve if curve is None else curve).GetEndPoint(end)
            restore = was_allowed(source, near_end(source.Location.Curve, point))
        WallUtils.DisallowWallJoinAtEnd(wall, end)
        if restore:
            FREED.setdefault(wall.Id.ToString(), (wall, set()))[1].add(end)


def parts_of(wall):
    """The walls that have the geometry and the joins: the members of a stacked wall, or the wall."""
    return [doc.GetElement(i) for i in wall.GetStackedWallMemberIds()] if wall.IsStackedWall else [wall]


def owner_end(wall, end):
    """(wall, end), a member of a stacked wall being replaced by its stacked wall: the joins of a stacked
    wall are handled on it (its members follow it)."""
    if wall.IsStackedWallMember:
        owner = doc.GetElement(wall.StackedWallOwnerId)
        return owner, near_end(owner.Location.Curve, wall.Location.Curve.GetEndPoint(end))
    return wall, end


def walls_near(wall):
    """Basic walls and members of stacked walls (not the stacked walls) around the wall, itself excluded."""
    host_ids = set(p.Id.ToString() for p in parts_of(wall))
    host_ids.add(wall.Id.ToString())
    bb = wall.get_BoundingBox(None)
    if bb is None:
        return [], host_ids
    pad = XYZ(1, 1, 1)
    near = FilteredElementCollector(doc).OfClass(Wall).WherePasses(
        BoundingBoxIntersectsFilter(Outline(bb.Min - pad, bb.Max + pad)))
    return [w for w in near if w.Id.ToString() not in host_ids and not w.IsStackedWall
            and isinstance(w.Location, LocationCurve)], host_ids


def neighbor_ends(wall):
    """[(other wall, end)]: ends of the OTHER walls joined to the wall (T joins against its side, L corners,
    walls in line...)."""
    near, host_ids = walls_near(wall)
    result, seen = [], set()
    for other in near:
        for end in (0, 1):
            joined = [e.Id.ToString() for e in other.Location.get_ElementsAtJoin(end)]
            if not host_ids.intersection(joined):
                continue
            target, target_end = owner_end(other, end)
            key = (target.Id.ToString(), target_end)
            if key[0] not in host_ids and key not in seen:
                seen.add(key)
                result.append((target, target_end))
    return result


def ends_joined_at(wall, end):
    """[(other wall, its end)]: the ends of other walls joined at that end of the wall."""
    ids = set(p.Id.ToString() for p in parts_of(wall))
    ids.add(wall.Id.ToString())
    point = wall.Location.Curve.GetEndPoint(end)
    result, seen = [], set()
    for part in parts_of(wall):
        for e in part.Location.get_ElementsAtJoin(near_end(part.Location.Curve, point)):
            if not isinstance(e, Wall) or e.Id.ToString() in ids or not isinstance(e.Location, LocationCurve):
                continue
            for k in (0, 1):
                if ids.intersection(x.Id.ToString() for x in e.Location.get_ElementsAtJoin(k)):
                    other, other_end = owner_end(e, k)
                    key = (other.Id.ToString(), other_end)
                    if key[0] not in ids and key not in seen:
                        seen.add(key)
                        result.append((other, other_end))
    return result


def free_neighbor_ends(wall):
    """Disallows the joins of the OTHER walls whose ends are joined to the wall: those ends follow the
    location line of the wall when it changes, dragging the walls."""
    for other, end in neighbor_ends(wall):
        if WallUtils.IsWallJoinAllowedAtEnd(other, end):
            WallUtils.DisallowWallJoinAtEnd(other, end)
            FREED.setdefault(other.Id.ToString(), (other, set()))[1].add(end)


def track_end(wall, end, selected, slide=False):
    """Measures where that end of a wall that is not split really is (NEIGHBORS).
    Basic walls: on their centerline and next to both faces (a mitred end is not square).
    Stacked walls: on the centerline of each member.
    slide: the end is joined to a split wall (it may be moved onto a layer, see slide_to_layer)."""
    key   = (wall.Id.ToString(), end)
    curve = wall.Location.Curve
    if key in NEIGHBORS:
        NEIGHBORS[key]["slide"] = NEIGHBORS[key]["slide"] or slide
        return
    if key[0] in selected or not isinstance(curve, Line):
        return
    origin, d = curve.GetEndPoint(0), curve.Direction
    n = XYZ.BasisZ.CrossProduct(d)
    if wall.IsStackedWall:
        parts   = parts_of(wall)
        offsets = [[flat(p.Location.Curve.GetEndPoint(0) - origin).DotProduct(n)] for p in parts]
    else:
        half = wall.Width / 2.0 - 3 * TOL_END
        parts, offsets = [wall], [[0.0, half, -half]]
    lines = []                                              # (part, line offset, where it ended)
    for part, part_offsets in zip(parts, offsets):
        pid = part.Id.ToString()
        if pid not in SEGMENTS:
            SEGMENTS[pid] = plan_segments(part)
        segs = SEGMENTS[pid]
        for c in part_offsets:
            r = reach(segs, origin, d, n, c)
            if r is not None:
                lines.append((part, c, r[end]))
    if lines:
        NEIGHBORS[key] = {"wall": wall, "end": end, "points": (origin, curve.GetEndPoint(1)), "d": d,
                          "n": n, "lines": lines, "stacked": wall.IsStackedWall, "slide": slide}


def track_neighbors(wall, selected):
    """Measures - before anything is modified - where the walls around the wall really end:
    - both ends of every wall next to it, joined to it or not: a wall that only touched it can be joined
      by Revit to one of the new layer walls, and the wall a split wall ended against changes with it;
    - the ends joined to the other end of the walls joined to it: changing the location line of a wall
      makes Revit work out the joins of both its ends again."""
    joined  = neighbor_ends(wall)
    sliding = set((other.Id.ToString(), end) for other, end in joined)
    near, host_ids = walls_near(wall)
    for other in near:
        other = owner_end(other, 0)[0]
        if other.Id.ToString() not in host_ids:
            for end in (0, 1):
                track_end(other, end, selected, (other.Id.ToString(), end) in sliding)
    for other, end in joined:
        for third, third_end in ends_joined_at(other, 1 - end):
            track_end(third, third_end, selected)


def set_line(wall, points):
    """Moves the location line of the wall to the plan position 'points' (elevation and direction kept).
    Returns False if nothing is changed."""
    curve = wall.Location.Curve
    pts   = [XYZ(p.X, p.Y, curve.GetEndPoint(i).Z) for i, p in enumerate(points)]
    if (pts[1] - pts[0]).DotProduct(curve.Direction) < 0.03:                # too short, or turned around
        return False
    if all(pts[i].IsAlmostEqualTo(curve.GetEndPoint(i), 1e-6) for i in (0, 1)):
        return False
    wall.Location.Curve = Line.CreateBound(pts[0], pts[1])
    return True


def set_end(wall, end, point):
    """Moves one end of the location line of the wall."""
    curve = wall.Location.Curve
    pts   = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
    pts[end] = point
    return set_line(wall, pts)


def track_layer(wall, segs, curve, normal, c):
    """Registers where the original wall (footprint 'segs', location 'curve') started and ended on the
    centerline of the layer wall, at distance c of the curve towards 'normal' (LAYER_ENDS)."""
    if not segs or not isinstance(curve, Line):
        return
    origin, d = curve.GetEndPoint(0), curve.Direction
    r = reach(segs, origin, d, normal, c)
    if r is not None:
        LAYER_ENDS[wall.Id.ToString()] = {"wall": wall, "origin": origin, "d": d, "n": normal, "c": c,
                                          "reach": r}


def same_curve(a, b):
    return all(a.GetEndPoint(i).IsAlmostEqualTo(b.GetEndPoint(i), 1e-6) for i in (0, 1))


def end_moved(shift):
    """True if a wall end counts as moved. shift (feet) = where the wall really ends now - where it ended
    before splitting, measured along the wall: > 0 the wall is longer at that end, < 0 it is shorter.
    Strict on purpose, in both directions: a wall that ended against a thin layer that is not split (1 cm
    of plaster...) is NOT stretched across the gap that layer leaves to reach the next layer and stay
    joined; it is left unjoined, exactly where it was. To allow that growth instead, accept
    0 < shift < MIN_LAYER here (a wall must never be allowed to get shorter)."""
    return abs(shift) > TOL_END


def slide_to_layer(nb, layers):
    """T join: the neighbor ended against a face of the split wall. Its end point is moved, along its own
    axis, onto the centerline of the layer wall that now has that face: Revit joins it to the layer its
    end point is in, and trims it at the face of that layer - where it ended before.
    (Left at the old wall centerline it would be joined to whatever layer is there, e.g. the insulation.)"""
    wall, end = nb["wall"], nb["end"]
    if nb["stacked"]:
        return
    d    = nb["d"]
    out  = d if end == 1 else d.Negate()                    # leaving the wall through that end
    face = nb["points"][0] + d.Multiply(nb["lines"][0][2])  # where its centerline really ended
    bb   = wall.get_BoundingBox(None)
    found = None
    for info in layers:
        line = info["line"]
        if abs(line.Direction.DotProduct(d)) > 0.94:        # (almost) in line with the layer: not a T
            continue
        if bb is None or min(bb.Max.Z, info["z"][1]) - max(bb.Min.Z, info["z"][0]) < TOL_Z:
            continue
        normal = XYZ.BasisZ.CrossProduct(line.Direction)
        cos    = out.DotProduct(normal)
        if cos < 0:
            normal, cos = normal.Negate(), -cos
        gap = flat(line.GetEndPoint(0) - face).DotProduct(normal)           # from the old face to the centerline
        if gap <= 0 or end_moved(gap - info["width"] / 2.0):                # that face is not a face of the layer
            continue
        dist  = gap / cos                                                   # the same, along the neighbor
        along = flat(face + out.Multiply(dist) - line.GetEndPoint(0)).DotProduct(line.Direction)
        if along < -TOL_END or along > line.Length + TOL_END:
            continue
        if found is not None and abs(found - dist) > TOL_END:               # layers of stacked members not aligned
            return
        found = dist
    if found is not None:
        set_end(wall, end, face + out.Multiply(found))


def extend_to_reach(track, wall, end):
    """Layer wall whose original went beyond its location end point (it ran through the corner up to the
    far face of the other wall): its end point is moved there, so the wall that ended against it finds the
    side of the layer - not its end - and is joined as a T."""
    curve = wall.Location.Curve
    origin, d = track["origin"], track["d"]
    s = [(curve.GetEndPoint(i) - origin).DotProduct(d) for i in (0, 1)]
    target = track["reach"][0 if s[end] < s[1 - end] else 1]
    if abs(target - s[1 - end]) > abs(s[end] - s[1 - end]) + TOL_END:
        set_end(wall, end, origin + d.Multiply(target) + track["n"].Multiply(track["c"]))


def end_has_moved(key, item, cache):
    """True if the end of the wall is not where it was before splitting (measured on its geometry)."""
    wall, end = item["wall"], item["end"]
    curve = wall.Location.Curve
    track, nb = LAYER_ENDS.get(key[0]), NEIGHBORS.get(key)
    if (track is None and nb is None) or not isinstance(curve, Line):
        return not same_curve(curve, item["curve"])             # not measured: its location must not change

    def segments(part):
        pid = part.Id.ToString()
        if pid not in cache:
            cache[pid] = plan_segments(part)
        return cache[pid]

    if track is not None:
        origin, d, n, c = track["origin"], track["d"], track["n"], track["c"]
        if any(abs((curve.GetEndPoint(i) - origin).DotProduct(n) - c) > TOL_END for i in (0, 1)):
            return True                                         # moved sideways
        s    = [(curve.GetEndPoint(i) - origin).DotProduct(d) for i in (0, 1)]
        side = 0 if s[end] < s[1 - end] else 1
        r    = reach(segments(wall), origin, d, n, c)
        if r is None:
            return True
        return end_moved(r[1] - track["reach"][1] if side == 1 else track["reach"][0] - r[0])

    origin, d, n = nb["points"][0], nb["d"], nb["n"]
    if any(abs((curve.GetEndPoint(i) - origin).DotProduct(n)) > TOL_END for i in (0, 1)):
        return True                                             # moved sideways
    if (key[0], 1 - end) not in NEIGHBORS and curve.GetEndPoint(1 - end).DistanceTo(nb["points"][1 - end]) > TOL_END:
        return True                                             # its other end moved
    for part, c, value in nb["lines"]:
        r = reach(segments(part), origin, d, n, c)
        if r is None or end_moved(r[1] - value if end == 1 else value - r[0]):
            return True
    return False


def pin_end(key, item):
    """Leaves the end of the wall unjoined, exactly where it was before splitting: without a join the wall
    ends (square) at the end point of its location curve, which is moved to where the wall really ended."""
    wall, end = item["wall"], item["end"]
    WallUtils.DisallowWallJoinAtEnd(wall, end)
    curve = wall.Location.Curve
    track, nb = LAYER_ENDS.get(key[0]), NEIGHBORS.get(key)
    if (track is None and nb is None) or not isinstance(curve, Line):
        if not same_curve(curve, item["curve"]):
            wall.Location.Curve = item["curve"]
        return

    if track is not None:
        origin, d, offset = track["origin"], track["d"], track["n"].Multiply(track["c"])
        s      = [(curve.GetEndPoint(i) - origin).DotProduct(d) for i in (0, 1)]
        s[end] = track["reach"][0 if s[end] < s[1 - end] else 1]
        set_line(wall, [origin + d.Multiply(v) + offset for v in s])
        return

    origin, d, n = nb["points"][0], nb["d"], nb["n"]
    if nb["stacked"]:
        # A stacked wall has one location line, but its members may have ended at different places (each
        # one joined in its own way): every member is left where it was. Revit rebuilds the members from
        # the stacked wall whenever it changes, so the stacked wall goes first (back on its original line),
        # and the ends of its members pinned before are set again
        nb["pinned"] = True
        set_line(wall, nb["points"])
        doc.Regenerate()
        for pinned in [NEIGHBORS.get((key[0], e)) for e in (0, 1)]:
            if pinned is None or not pinned.get("pinned"):
                continue
            for part, c, value in pinned["lines"]:
                part_curve = part.Location.Curve
                part_end   = near_end(part_curve, pinned["points"][pinned["end"]])
                WallUtils.DisallowWallJoinAtEnd(part, part_end)
                s = [(part_curve.GetEndPoint(i) - origin).DotProduct(d) for i in (0, 1)]
                s[part_end] = value
                set_line(part, [origin + d.Multiply(v) + n.Multiply(c) for v in s])
        return
    s      = [(curve.GetEndPoint(i) - origin).DotProduct(d) for i in (0, 1)]    # on its original axis
    s[end] = nb["lines"][0][2]                                                  # where its centerline ended
    set_line(wall, [origin + d.Multiply(v) for v in s])


# Wall ends still to be checked: {(wall id, end): {"wall", "end", "curve", "restore"}}
PENDING = {}

def restore_joins():
    """Allows again the joins disallowed while splitting (except the ends cleaned up by fix_corners) and
    checks, on the real geometry, that every wall still ends where it ended before splitting.
    Joining moves the end point of a wall onto the location line of the wall it is joined to: that is fine
    as long as the wall itself (its faces, its real end) stays in place. The ends Revit cannot join without
    moving the wall are left unjoined, exactly where they were. Returns the ends left unjoined."""
    def add(wall, end, restore):
        if not wall.IsValidObject:                  # created in a rolled back transaction, or deleted
            return
        key = (wall.Id.ToString(), end)
        if key not in PENDING and key not in CLEANED:
            PENDING[key] = {"wall": wall, "end": end, "curve": wall.Location.Curve.Clone(), "restore": restore}

    for wall, ends in FREED.values():
        for end in ends:
            add(wall, end, True)
    FREED.clear()
    # Checked as well, although their join is not restored (it was already disallowed, or it is not a
    # join with a split wall): they must end where they ended too
    for nb in NEIGHBORS.values():
        add(nb["wall"], nb["end"], False)
    for track in LAYER_ENDS.values():
        for end in (0, 1):
            add(track["wall"], end, False)

    layers = [layer_info(t["wall"]) for t in LAYER_ENDS.values()
              if t["wall"].IsValidObject and isinstance(t["wall"].Location.Curve, Line)]
    for key in sorted(PENDING):
        item = PENDING[key]
        if not item["restore"] or not isinstance(item["wall"].Location.Curve, Line):
            continue
        if key in NEIGHBORS and NEIGHBORS[key]["slide"]:
            slide_to_layer(NEIGHBORS[key], layers)
        elif key[0] in LAYER_ENDS:
            extend_to_reach(LAYER_ENDS[key[0]], item["wall"], item["end"])
    for item in PENDING.values():
        if item["restore"] and not WallUtils.IsWallJoinAllowedAtEnd(item["wall"], item["end"]):
            WallUtils.AllowWallJoinAtEnd(item["wall"], item["end"])
    doc.Regenerate()
    return check_ends()


def check_ends():
    """Leaves unjoined, where they were, the wall ends (PENDING) that are not where they were before
    splitting. Unjoining an end can change the walls that were joined to it: they are checked again until
    nothing moves. Returns the ends left unjoined (that were joined)."""
    unjoined = 0
    for _ in range(6):
        cache = {}
        for key in list(PENDING):
            if not PENDING[key]["wall"].IsValidObject:
                PENDING.pop(key)
        moved = [key for key in sorted(PENDING) if end_has_moved(key, PENDING[key], cache)]
        if not moved:
            break
        for key in moved:
            item = PENDING.pop(key)
            if item["restore"] or WallUtils.IsWallJoinAllowedAtEnd(item["wall"], item["end"]):
                unjoined += 1
            pin_end(key, item)
        doc.Regenerate()
    return unjoined


def set_param(elem, bip, value):
    p = elem.get_Parameter(bip)
    if p is not None and not p.IsReadOnly:
        p.Set(value)


def is_opening(elem):
    if isinstance(elem, Opening):
        return True
    return elem.Category is not None and elem.Category.Id.ToString() in OPENING_CAT_IDS


def elem_point(elem):
    if isinstance(elem.Location, LocationPoint):
        return elem.Location.Point
    bb = elem.get_BoundingBox(None)
    return (bb.Min + bb.Max) / 2.0 if bb else None


def point_on_wall(point, wall):
    """Projects the point (horizontally) onto the wall location curve, keeping its elevation."""
    curve = wall.Location.Curve
    res   = curve.Project(XYZ(point.X, point.Y, curve.GetEndPoint(0).Z))
    return XYZ(res.XYZPoint.X, res.XYZPoint.Y, point.Z)


# ── Layer types ───────────────────────────────────────
# Wall types by name (filled once, updated when types are created)
TYPES = {}

def layer_type_matches(wall_type, layer):
    if wall_type.Kind != WallKind.Basic:
        return False
    cs = wall_type.GetCompoundStructure()
    if cs is None or cs.LayerCount != 1:
        return False
    l = cs.GetLayers()[0]
    return (l.MaterialId == layer.MaterialId and l.Function == layer.Function
            and abs(l.Width - layer.Width) < TOL_DIM)


def get_layer_type(base_type, layer):
    """Returns (creating it if needed) a single-layer wall type for the layer."""
    material  = doc.GetElement(layer.MaterialId)
    mat_name  = get_name(material) if material else "Generic"
    width_txt = "{:g}".format(round(layer.Width * FT_TO_CM, 1))
    base_name = sanitize("{} ({}cm)".format(mat_name, width_txt))

    candidates = [base_name, "{} - {}".format(base_name, layer.Function)]
    candidates += ["{} ({})".format(base_name, i) for i in range(2, 50)]
    for name in candidates:
        wall_type = TYPES.get(name)
        if wall_type is not None and not wall_type.IsValidObject:     # created in a rolled back transaction
            TYPES.pop(name)
            wall_type = None
        if wall_type is None:
            new_type = base_type.Duplicate(name)
            try:
                cs = CompoundStructure.CreateSingleLayerCompoundStructure(layer.Function, layer.Width, layer.MaterialId)
            except Exception:
                cs = CompoundStructure.CreateSimpleCompoundStructure(
                    List[CompoundStructureLayer]([CompoundStructureLayer(layer.Width, layer.Function, layer.MaterialId)]))
            if layer.Function == MaterialFunctionAssignment.Structure:
                cs.StructuralMaterialIndex = 0
            new_type.SetCompoundStructure(cs)
            TYPES[name] = new_type
            return new_type
        if layer_type_matches(wall_type, layer):
            return wall_type
    raise Exception("Could not find a free type name for '{}'".format(base_name))


# ╔╗ ╔═╗╔═╗╦╔═╗  ╦ ╦╔═╗╦  ╦  ╔═╗
# ╠╩╗╠═╣╚═╗║║    ║║║╠═╣║  ║  ╚═╗
# ╚═╝╩ ╩╚═╝╩╚═╝  ╚╩╝╩ ╩╩═╝╩═╝╚═╝
#==================================================
def hosted_instances(wall):
    """Family instances hosted by the wall that are NOT openings (fixtures, face based...)."""
    result = []
    for eid in wall.GetDependentElements(ElementClassFilter(FamilyInstance)):
        fi = doc.GetElement(eid)
        if fi.Host is not None and fi.Host.Id == wall.Id and not is_opening(fi):
            result.append(fi)
    return result


def nearest_index(point, curves):
    best, best_dist = 0, None
    for i, c in enumerate(curves):
        res = c.Project(XYZ(point.X, point.Y, c.GetEndPoint(0).Z))
        if res is not None and (best_dist is None or res.Distance < best_dist):
            best, best_dist = i, res.Distance
    return best


def place_layer_wall(src_wall, layer_type, target, normal, layer_idx, all_targets, structural, reuse=False):
    """Copies the basic wall (with its inserts) - or reuses it - applies the layer type and moves it
    to the layer position. Returns the layer wall."""
    if reuse:
        new_wall = src_wall
    else:
        copied   = ElementTransformUtils.CopyElements(doc, List[ElementId]([src_wall.Id]), XYZ.Zero)
        new_wall = None
        for eid in copied:
            e = doc.GetElement(eid)
            if isinstance(e, Wall):
                new_wall = e
        if new_wall is None:
            raise Exception("The wall could not be copied")
    new_wall.Pinned = False
    free_ends(new_wall, None if reuse else src_wall)    # moving it must not drag the walls joined to it

    # Non-opening hosted elements: only in the nearest layer (before moving the wall)
    for fi in hosted_instances(new_wall):
        pt = elem_point(fi)
        if pt is not None and nearest_index(pt, all_targets) != layer_idx:
            doc.Delete(fi.Id)

    new_wall.ChangeTypeId(layer_type.Id)
    set_param(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, 0)            # Location Line = Wall Centerline
    if not structural:
        set_param(new_wall, BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT, 0)
    doc.Regenerate()
    move_to_curve(new_wall, target, normal)
    return new_wall


def can_rebuild(wall):
    """False if a new wall cannot reproduce the wall (edited profile, attached top / base)."""
    if wall.SketchId != ElementId.InvalidElementId:
        return False
    for bip in (BuiltInParameter.WALL_TOP_IS_ATTACHED, BuiltInParameter.WALL_BOTTOM_IS_ATTACHED):
        p = wall.get_Parameter(bip)
        if p is not None and p.AsInteger() == 1:
            return False
    return True


def basic_member(wall, curve):
    """Data of a basic wall in the format of a stacked member (see stacked_members).
    curve: clone of its location curve (it is used after other walls are created and regenerated)."""
    doors, holes = [], []
    for eid in wall.FindInserts(True, False, False, False):
        e = doc.GetElement(eid)
        if isinstance(e, Opening):
            holes.append(e)
        elif isinstance(e, FamilyInstance) and is_opening(e):
            doors.append(e)
    rects = [opening_rect(op, curve) for op in holes if op.IsRectBoundary]
    return {"wall": wall, "curve": curve, "normal": wall.Orientation, "rel_bottom": 0.0,
            "height": wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble(),
            "is_top": True, "doors": doors, "holes": rects, "lost": len(holes) - len(rects)}


def split_basic_wall(wall, footprint):
    """Splits a basic wall. The original wall becomes one of the layers (the one closest to its fixtures,
    else the structural one). footprint: plan_segments of the wall, measured before any wall was modified.
    Returns (layer walls, openings, warnings)."""
    cs = wall.WallType.GetCompoundStructure()
    if cs is None:
        raise Exception("Wall type without compound structure")
    layers = get_layers(cs, MIN_LAYER)
    if len(layers) < 2:
        return [], 0, []

    # Clone: the curve returned by Location.Curve points to the geometry of the wall, and it is not valid
    # anymore (Revit crashes when it is read) once the wall changes its type or is moved
    curve, normal = wall.Location.Curve.Clone(), wall.Orientation
    # Measured on the real exterior face: the location curve is not always where the Location Line says
    ext = ext_face_from_geometry(wall, curve, normal)
    if ext is None:
        ext = ext_face_from_key_ref(wall, cs)
    offsets = [ext - acc - layer.Width / 2.0 for layer, acc in layers]      # layer centerlines
    targets = [offset_curve(curve, offset, normal) for offset in offsets]
    pieces  = [(get_layer_type(wall.WallType, layer), layer.Function == MaterialFunctionAssignment.Structure)
               for layer, _ in layers]

    # Layers that need the fixtures of the wall (they must be copies of it)
    fixture_layers = [nearest_index(pt, targets) for pt in
                      [elem_point(fi) for fi in hosted_instances(wall)] if pt is not None]
    structural = [i for i, piece in enumerate(pieces) if piece[1]]
    if fixture_layers:
        keep = max(set(fixture_layers), key=fixture_layers.count)
    else:
        keep = structural[0] if structural else 0
    rebuild = can_rebuild(wall)
    member  = basic_member(wall, curve)

    if wall.Pinned:
        wall.Pinned = False
    walls, jobs = [None] * len(pieces), []
    for i, (layer_type, is_structural) in enumerate(pieces):
        if i == keep:
            continue
        if rebuild and i not in fixture_layers:
            walls[i] = create_layer_wall(wall, member, layer_type, targets[i], is_structural)
            jobs.append((walls[i], member["doors"], member["holes"], member["curve"]))
        else:
            walls[i] = place_layer_wall(wall, layer_type, targets[i], normal, i, targets, is_structural)
    created, failed = add_openings(jobs)

    # The original wall last: the copies above are made from it unchanged
    walls[keep] = place_layer_wall(wall, pieces[keep][0], targets[keep], normal, keep, targets, pieces[keep][1],
                                   reuse=True)
    for layer_wall, offset in zip(walls, offsets):
        track_layer(layer_wall, footprint, curve, normal, offset)

    warnings = []
    if failed or member["lost"]:
        warnings.append("{} doors/windows/openings could not be created".format(failed + member["lost"]))
    openings = len(member["doors"]) + len(member["holes"])
    return walls, openings * (len(pieces) - len(jobs)) + created, warnings


# ╔═╗╔╦╗╔═╗╔═╗╦╔═╔═╗╔╦╗  ╦ ╦╔═╗╦  ╦  ╔═╗
# ╚═╗ ║ ╠═╣║  ╠╩╗║╣  ║║  ║║║╠═╣║  ║  ╚═╗
# ╚═╝ ╩ ╩ ╩╚═╝╩ ╩╚═╝═╩╝  ╚╩╝╩ ╩╩═╝╩═╝╚═╝
#==================================================
def cutting_ids(wall):
    """Ids (as text) of the elements that generate faces of the wall geometry, i.e. the openings that cut it."""
    ids  = set()
    opts = Options()
    opts.ComputeReferences = False
    geom = wall.get_Geometry(opts)
    if geom is None:
        return ids
    for obj in geom:
        if isinstance(obj, Solid):
            for face in obj.Faces:
                for eid in wall.GetGeneratingElementIds(face):
                    if eid != wall.Id:
                        ids.add(eid.ToString())
    return ids


def opening_z_range(elem):
    """(bottom, top) of the cut of an opening: sill / head height of doors and windows, else bounding box."""
    if isinstance(elem, FamilyInstance):
        level = doc.GetElement(elem.LevelId)
        sill  = elem.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
        head  = elem.get_Parameter(BuiltInParameter.INSTANCE_HEAD_HEIGHT_PARAM)
        if level is not None and sill and head and head.AsDouble() > sill.AsDouble():
            return (level.ProjectElevation + sill.AsDouble(), level.ProjectElevation + head.AsDouble())
    elif isinstance(elem, Opening) and elem.IsRectBoundary:
        zs = [p.Z for p in elem.BoundaryRect]
        return (min(zs), max(zs))
    bb = elem.get_BoundingBox(None)
    return (bb.Min.Z, bb.Max.Z) if bb else None


def opening_rect(opening, curve):
    """(u0, u1, z0, z1) of a rectangular wall opening, measured along 'curve' (curve parameter)."""
    us = [curve.Project(p).Parameter for p in opening.BoundaryRect]
    zs = [p.Z for p in opening.BoundaryRect]
    return (min(us), max(us), min(zs), max(zs))




def stacked_members(wall, curves):
    """Data of each member of the stacked wall (bottom -> top), measured on the original.
    curves: {member id: location curve} measured before any wall was modified (the ends of the location
    curve of a member depend on its joins, and they may have been disallowed by now)."""
    members = []
    for mid in wall.GetStackedWallMemberIds():
        member = doc.GetElement(mid)
        bb     = member.get_BoundingBox(None)
        if bb is None or member.WallType.GetCompoundStructure() is None:
            raise Exception("Stacked member {} has no geometry / structure".format(member.Id))
        members.append((bb.Min.Z, bb.Max.Z, member))
    members.sort(key=lambda m: m[0])

    # Doors / windows and wall openings of the stacked wall (hosted by the stacked wall or by its members)
    doors, openings = {}, {}
    for host in [wall] + [m[2] for m in members]:
        for eid in host.FindInserts(True, False, False, False):
            e = doc.GetElement(eid)
            if isinstance(e, Opening):
                openings[eid.ToString()] = e
            elif isinstance(e, FamilyInstance) and is_opening(e):
                doors[eid.ToString()] = e
    doors, openings = list(doors.values()), list(openings.values())
    cut_sets = [cutting_ids(m[2]) for m in members]
    found    = set().union(*cut_sets) if cut_sets else set()

    result, z0 = [], members[0][0]
    for i, (zmin, zmax, member) in enumerate(members):
        is_top = i == len(members) - 1
        top_z  = zmax if is_top else members[i + 1][0]
        curve  = curves.get(member.Id.ToString()) or member.Location.Curve.Clone()
        cs     = member.WallType.GetCompoundStructure()
        ext    = ext_face_from_geometry(member, curve, member.Orientation)
        if ext is None:
            ext = ext_face_from_key_ref(member, cs)

        # Doors / windows that cut this member (geometry), or that cross its height (fallback)
        wanted = []
        for e in doors:
            key = e.Id.ToString()
            if key in found:
                if key in cut_sets[i]:
                    wanted.append(e)
            else:
                z_range = opening_z_range(e)
                if z_range and z_range[1] > zmin + TOL_Z and z_range[0] < top_z - TOL_Z:
                    wanted.append(e)

        # Rectangular wall openings that cross the height of this member
        holes, lost = [], 0
        for op in openings:
            if not op.IsRectBoundary:
                lost += 1
                continue
            rect = opening_rect(op, curve)
            if rect[3] > zmin + TOL_Z and rect[2] < top_z - TOL_Z:
                holes.append(rect)

        result.append({"wall": member, "type": member.WallType, "cs": cs, "curve": curve,
                       "normal": member.Orientation, "ext": ext, "rel_bottom": zmin - z0,
                       "height": top_z - zmin, "zmin": zmin, "zmax": top_z, "is_top": is_top,
                       "doors": wanted, "holes": holes, "lost": lost})
    return result


def copy_instance_params(src, dst):
    """Copies the writable instance parameters (dimensions, sill, comments...) of src into dst."""
    for p in src.Parameters:
        if p.IsReadOnly or not p.HasValue or p.StorageType == StorageType.ElementId:
            continue
        bip = getattr(p.Definition, "BuiltInParameter", None)
        if bip in SKIP_PARAMS:
            continue
        q = dst.get_Parameter(p.GUID) if p.IsShared else dst.get_Parameter(p.Definition)
        if q is None or q.IsReadOnly or q.StorageType != p.StorageType:
            continue
        try:
            if p.StorageType == StorageType.Double:
                q.Set(p.AsDouble())
            elif p.StorageType == StorageType.Integer:
                q.Set(p.AsInteger())
            elif p.StorageType == StorageType.String:
                q.Set(p.AsString() or "")
        except Exception:
            pass
    for bip in (BuiltInParameter.PHASE_CREATED, BuiltInParameter.PHASE_DEMOLISHED):
        p, q = src.get_Parameter(bip), dst.get_Parameter(bip)
        if p and q and not q.IsReadOnly and q.AsElementId() != p.AsElementId():
            try:
                q.Set(p.AsElementId())
            except Exception:
                pass


def copy_wall_params(src, dst):
    for bip in WALL_PARAMS:
        p, q = src.get_Parameter(bip), dst.get_Parameter(bip)
        if p is None or q is None or q.IsReadOnly or not p.HasValue:
            continue
        try:
            if p.StorageType == StorageType.ElementId:
                q.Set(p.AsElementId())
            elif p.StorageType == StorageType.Integer:
                q.Set(p.AsInteger())
            elif p.StorageType == StorageType.Double:
                q.Set(p.AsDouble())
            elif p.StorageType == StorageType.String:
                q.Set(p.AsString() or "")
        except Exception:
            pass


def recreate_door(orig, wall):
    """Creates in 'wall' a copy of the original door / window (type, parameters, sill).
    The orientation is matched later by add_openings (it needs a regeneration)."""
    level = doc.GetElement(orig.LevelId) or doc.GetElement(wall.LevelId)
    point = point_on_wall(orig.Location.Point, wall)
    inst  = doc.Create.NewFamilyInstance(XYZ(point.X, point.Y, level.ProjectElevation),
                                         orig.Symbol, wall, level, StructuralType.NonStructural)
    copy_instance_params(orig, inst)
    return inst


def add_openings(jobs):
    """jobs: [(wall, doors, holes, curve)]. Recreates the doors / windows and creates the rectangular
    openings (measured on 'curve') in each wall, with only two regenerations. Returns (created, failed)."""
    if not jobs:
        return 0, 0
    doc.Regenerate()                                                        # the hosts need their geometry
    created, failed, insts = 0, 0, []
    for wall, doors, holes, curve in jobs:
        for door in doors:
            try:
                insts.append((recreate_door(door, wall), door))
            except Exception:
                failed += 1
        for hole in holes:
            try:
                create_hole(wall, curve, hole)
                created += 1
            except Exception:
                failed += 1
    if insts:
        doc.Regenerate()
        for inst, orig in insts:
            flip_facing = inst.CanFlipFacing and inst.FacingOrientation.DotProduct(orig.FacingOrientation) < 0
            flip_hand   = inst.CanFlipHand and inst.HandOrientation.DotProduct(orig.HandOrientation) < 0
            if flip_facing:
                inst.flipFacing()
            if flip_hand:
                inst.flipHand()
    return created + len(insts), failed


def create_hole(wall, curve, hole):
    """Creates a rectangular wall opening in 'wall' from a hole measured on the original curve."""
    u0, u1, z0, z1 = hole
    p0 = curve.Evaluate(u0, False)
    p1 = curve.Evaluate(u1, False)
    doc.Create.NewOpening(wall, point_on_wall(XYZ(p0.X, p0.Y, z0), wall), point_on_wall(XYZ(p1.X, p1.Y, z1), wall))


def create_layer_wall(stacked, member, layer_type, target, structural):
    """Creates a new basic wall for one layer of a stacked member (or of a basic wall), with the
    member's constraints, centered on 'target' with its exterior towards the member's exterior."""
    base_level = stacked.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
    base_off   = stacked.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble() + member["rel_bottom"]
    top_level  = stacked.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()

    level_z = doc.GetElement(base_level).ProjectElevation
    curve   = target.CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, level_z - target.GetEndPoint(0).Z)))
    # A new wall has its exterior at Z x direction and its Location Line at the Wall Centerline
    in_place = isinstance(curve, Line)
    if in_place and XYZ.BasisZ.CrossProduct(curve.Direction).DotProduct(member["normal"]) < 0:
        curve = curve.CreateReversed()
    new_wall = Wall.Create(doc, curve, layer_type.Id, base_level, member["height"], base_off, False, structural)
    free_ends(new_wall, stacked, curve)     # later moves of other walls must not drag it (and vice versa)

    if member["is_top"]:
        if top_level != ElementId.InvalidElementId:
            set_param(new_wall, BuiltInParameter.WALL_HEIGHT_TYPE, top_level)
            set_param(new_wall, BuiltInParameter.WALL_TOP_OFFSET,
                      stacked.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).AsDouble())
        else:
            set_param(new_wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
                      stacked.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble() - member["rel_bottom"])
    copy_wall_params(stacked, new_wall)
    set_param(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, 0)
    if in_place:
        return new_wall

    # Arcs: same exterior side as the member, then exact position of the layer centerline
    doc.Regenerate()
    if new_wall.Orientation.DotProduct(member["normal"]) < 0:
        new_wall.Flip()
        doc.Regenerate()
    move_to_curve(new_wall, target, member["normal"])
    return new_wall


def split_stacked_wall(wall, footprint, curves):
    """Rebuilds a stacked wall as basic walls (one per layer > 5 cm of each member).
    footprint: {member id: plan_segments}, curves: {member id: location curve}, both measured before any
    wall was modified. Returns (walls created, doors/windows + openings created, warnings)."""
    stacked_structural = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    stacked_structural = bool(stacked_structural and stacked_structural.AsInteger())

    # 1- Measure everything on the original (before modifying anything)
    pieces, warnings, lost = [], [], 0
    for member in stacked_members(wall, curves):
        lost  += member["lost"]
        layers = get_layers(member["cs"], MIN_LAYER)
        for layer, acc in layers:
            offset = member["ext"] - acc - layer.Width / 2.0   # layer centerline
            target = offset_curve(member["curve"], offset, member["normal"])
            if member["cs"].LayerCount == 1:
                layer_type = member["type"]                 # single-layer member keeps its own type
            else:
                layer_type = get_layer_type(member["type"], layer)
            structural = stacked_structural and layer.Function == MaterialFunctionAssignment.Structure
            pieces.append((member, layer_type, target, structural, member["holes"], offset))

    if not pieces:
        return [], 0, warnings

    # 2- Create the new walls, then their doors / windows and wall openings
    walls, jobs = [], []
    for member, layer_type, target, structural, holes, offset in pieces:
        new_wall = create_layer_wall(wall, member, layer_type, target, structural)
        walls.append(new_wall)
        jobs.append((new_wall, member["doors"], holes, member["curve"]))
        track_layer(new_wall, footprint.get(member["wall"].Id.ToString()), member["curve"], member["normal"],
                    offset)
    created_openings, failed = add_openings(jobs)
    if failed or lost:
        warnings.append("{} doors/windows/openings could not be created".format(failed + lost))

    if wall.Pinned:
        wall.Pinned = False
    doc.Delete(wall.Id)
    return walls, created_openings, warnings


# ╔═╗╔═╗╦═╗╔╗╔╔═╗╦═╗╔═╗
# ║  ║ ║╠╦╝║║║║╣ ╠╦╝╚═╗
# ╚═╝╚═╝╩╚═╝╚╝╚═╝╩╚═╚═╝
#==================================================
def wall_width(wall):
    if wall.IsStackedWall:
        return max(doc.GetElement(i).Width for i in wall.GetStackedWallMemberIds())
    return wall.Width


def end_neighbors(wall):
    """Ids (as text) of the walls joined at each end of the wall (stacked members -> their stacked wall)."""
    curve  = wall.Location.Curve
    result = [set(), set()]
    hosts  = [wall] + ([doc.GetElement(i) for i in wall.GetStackedWallMemberIds()] if wall.IsStackedWall else [])
    for host in hosts:
        host_curve = host.Location.Curve
        for host_end in (0, 1):
            end = near_end(curve, host_curve.GetEndPoint(host_end))
            for e in host.Location.get_ElementsAtJoin(host_end):
                if not isinstance(e, Wall):
                    continue
                if e.IsStackedWallMember:
                    e = doc.GetElement(e.StackedWallOwnerId)
                if e.Id != wall.Id:
                    result[end].add(e.Id.ToString())
    return result


def near_end(curve, point):
    return 0 if curve.GetEndPoint(0).DistanceTo(point) <= curve.GetEndPoint(1).DistanceTo(point) else 1


def flat(v):
    return XYZ(v.X, v.Y, 0)


def layer_info(wall):
    bb = wall.get_BoundingBox(None)
    cs = wall.WallType.GetCompoundStructure()
    structure = cs is not None and cs.LayerCount == 1 and \
        cs.GetLayers()[0].Function == MaterialFunctionAssignment.Structure
    return {"wall": wall, "line": wall.Location.Curve.Clone(), "width": wall.Width, "z": (bb.Min.Z, bb.Max.Z),
            "structure": structure}


def split_at_core(rank):
    """Layers ranked from the outside -> (outside layers from the core outwards, core, inside layers from
    the core inwards). The core is the thickest structural layer (else the thickest layer)."""
    core = max([i for i in rank if i["structure"]] or rank, key=lambda i: i["width"])
    c    = rank.index(core)
    return rank[:c][::-1], core, rank[c + 1:]


def z_overlap(a, b):
    return min(a["z"][1], b["z"][1]) - max(a["z"][0], b["z"][0])


def z_groups(infos):
    """Layer walls grouped by height (one group per stacked member)."""
    groups = {}
    for info in infos:
        groups.setdefault((round(info["z"][0], 2), round(info["z"][1], 2)), []).append(info)
    return list(groups.values())


def pos(info, origin, u):
    """Distance from origin to the layer centerline, along u."""
    return flat(info["line"].GetEndPoint(0) - origin).DotProduct(u)


def point_at(info, origin, u, value):
    """Point of the (unbounded) layer centerline at distance 'value' from origin along u."""
    p0, d = info["line"].GetEndPoint(0), info["line"].Direction
    den = d.DotProduct(u)
    if abs(den) < 1e-6:
        return None
    return p0 + d.Multiply((value - flat(p0 - origin).DotProduct(u)) / den)


def corner_l(w_infos, n_infos, origin, d_w, d_n, propose):
    """L corner. The layers are paired from the core (core with core, then the layers outside / inside
    of the core in order). Each pair forms a clean L: the layer of W goes up to the outer face of its
    pair and the layer of N stops at the inner face of its pair (outer = towards the outside of the
    corner). Unpaired layers close the corner outside, or stop at the inner face of the other wall."""
    u_w = flat(d_w.Multiply(d_n.DotProduct(d_w)) - d_n).Normalize()      # outside of W
    u_n = flat(d_n.Multiply(d_w.DotProduct(d_n)) - d_w).Normalize()      # outside of N

    def outer(info, u):
        return pos(info, origin, u) + info["width"] / 2.0

    def inner(info, u):
        return pos(info, origin, u) - info["width"] / 2.0

    for gw in z_groups(w_infos):
        for gn in z_groups(n_infos):
            weight = z_overlap(gw[0], gn[0])
            if weight < TOL_Z:
                continue
            w_out, w_core, w_in = split_at_core(sorted(gw, key=lambda i: -pos(i, origin, u_w)))
            n_out, n_core, n_in = split_at_core(sorted(gn, key=lambda i: -pos(i, origin, u_n)))
            ends = []                                                   # (layer, distance, axis)
            for a, b in [(w_core, n_core)] + list(zip(w_out, n_out)) + list(zip(w_in, n_in)):
                ends += [(a, outer(b, u_n), u_n), (b, inner(a, u_w), u_w)]
            ends += [(a, outer((n_out or [n_core])[-1], u_n), u_n) for a in w_out[len(n_out):]]
            ends += [(b, outer((w_out or [w_core])[-1], u_w), u_w) for b in n_out[len(w_out):]]
            ends += [(a, inner((n_in or [n_core])[-1], u_n), u_n) for a in w_in[len(n_in):]]
            ends += [(b, inner((w_in or [w_core])[-1], u_w), u_w) for b in n_in[len(w_in):]]
            for info, face, u in ends:
                propose(info, origin, point_at(info, origin, u, face), weight)


def corner_t(w_infos, n_infos, origin, d_w, d_n, propose):
    """T: each layer of W stops at the face of N on the side of W."""
    v = flat(d_w - d_n.Multiply(d_w.DotProduct(d_n))).Normalize()        # from N towards W
    for a in w_infos:
        faces = [pos(b, origin, v) + b["width"] / 2.0 for b in n_infos if z_overlap(a, b) > TOL_Z]
        if faces:
            propose(a, origin, point_at(a, origin, v, max(faces)), z_overlap(a, a))


def fix_corners(sources):
    """Extends / trims the layer walls at the ends where two split walls were joined.
    sources: {id: {"curve", "width", "ends", "layers"}} measured before splitting. Returns the corners fixed."""
    infos = {}
    for sid, s in sources.items():
        walls = [w for w in s["layers"] if w.IsValidObject and isinstance(w.Location.Curve, Line)]
        if walls and isinstance(s["curve"], Line):
            infos[sid] = [layer_info(w) for w in walls]

    proposals, handled, corners = {}, set(), 0

    def propose(info, origin, point, weight):
        if point is None:
            return
        end = near_end(info["line"], origin)
        if point.DistanceTo(info["line"].GetEndPoint(end)) > max_shift:
            return
        key = (info["wall"].Id.ToString(), end)
        if key not in proposals or proposals[key][0] < weight:
            proposals[key] = (weight, point, info["wall"], end)

    for sid in sorted(infos, key=int):
        s = sources[sid]
        for end in (0, 1):
            if (sid, end) in handled:
                continue
            origin = s["curve"].GetEndPoint(end)
            d_w    = flat(s["curve"].GetEndPoint(1 - end) - origin).Normalize()
            l_best, t_best = None, None
            for nid in s["ends"][end]:
                if nid not in infos:
                    continue
                n   = sources[nid]
                tol = s["width"] + n["width"]
                n_end = near_end(n["curve"], origin)
                q     = n["curve"].GetEndPoint(n_end)
                if flat(q - origin).GetLength() < tol:
                    d_n   = flat(n["curve"].GetEndPoint(1 - n_end) - q).Normalize()
                    cross = abs(d_w.CrossProduct(d_n).Z)
                    if cross > 0.2 and (l_best is None or cross > l_best[0]):
                        l_best = (cross, nid, n_end, d_n)
                elif t_best is None:
                    t_best = (nid, n["curve"].Direction)
            if l_best is not None:
                _, nid, n_end, d_n = l_best
                max_shift = 2 * (s["width"] + sources[nid]["width"])
                corner_l(infos[sid], infos[nid], origin, d_w, d_n, propose)
                handled.add((nid, n_end))
                corners += 1
            elif t_best is not None:
                nid, d_n = t_best
                max_shift = 2 * (s["width"] + sources[nid]["width"])
                corner_t(infos[sid], infos[nid], origin, d_w, d_n, propose)
                corners += 1

    for weight, point, wall, end in proposals.values():
        WallUtils.DisallowWallJoinAtEnd(wall, end)
        FREED.get(wall.Id.ToString(), (None, set()))[1].discard(end)     # stays disallowed (clean corner)
        CLEANED.add((wall.Id.ToString(), end))
        line  = wall.Location.Curve
        other = line.GetEndPoint(1 - end)
        point = XYZ(point.X, point.Y, line.GetEndPoint(end).Z)
        if point.DistanceTo(other) < 0.03:
            continue
        wall.Location.Curve = Line.CreateBound(point, other) if end == 0 else Line.CreateBound(other, point)
    return corners


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
walls = get_selected_walls()
if not walls:
    forms.alert("Select at least one basic or stacked wall.", exitscript=True)

for wt in FilteredElementCollector(doc).OfClass(WallType):
    TYPES[get_name(wt)] = wt

# Ends, joins and real footprint of every wall - and of the walls joined to them - measured before any
# of them is split: splitting a wall changes the joins (and so the geometry) of its neighbors
selected = set()
for wall in walls:
    selected.add(wall.Id.ToString())
    if wall.IsStackedWall:
        selected.update(i.ToString() for i in wall.GetStackedWallMemberIds())

sources = {}
for wall in walls:
    try:
        members = [doc.GetElement(i) for i in wall.GetStackedWallMemberIds()] if wall.IsStackedWall else []
        sources[wall.Id.ToString()] = {"curve": wall.Location.Curve.Clone(), "width": wall_width(wall),
                                       "ends": end_neighbors(wall), "layers": [],
                                       "footprint": footprints(wall),
                                       "curves": dict((m.Id.ToString(), m.Location.Curve.Clone()) for m in members)}
        track_neighbors(wall, selected)
    except Exception:
        print(traceback.format_exc())
SEGMENTS.clear()

report = []         # [wall id, type, result]
created_total = 0
corners = 0

tg = TransactionGroup(doc, "Split Walls")
tg.Start()
with forms.ProgressBar(title="Splitting walls... ({value} of {max_value})", cancellable=True) as pb:
    for n, wall in enumerate(walls):
        if pb.cancelled:
            break
        pb.update_progress(n, len(walls))

        if not wall.IsValidObject:
            continue
        wall_id   = output.linkify(wall.Id)
        type_name = get_name(wall.WallType)
        if wall.GroupId != ElementId.InvalidElementId:
            report.append([wall_id, type_name, "Skipped: wall is inside a group"])
            continue

        t = Transaction(doc, "Split Wall {}".format(wall.Id))
        options = t.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(SilentFailures())
        options.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(options)
        t.Start()
        try:
            source_id = wall.Id.ToString()
            source    = sources.get(source_id, {})
            footprint = source.get("footprint", {})
            free_neighbor_ends(wall)            # walls joined to it must not follow it
            if wall.IsStackedWall:
                layer_walls, openings, warnings = split_stacked_wall(wall, footprint, source.get("curves", {}))
            else:
                layer_walls, openings, warnings = split_basic_wall(wall, footprint.get(source_id))
            if not layer_walls:
                t.RollBack()
                report.append([wall_id, type_name, "Skipped: only one layer"])
                continue
            if t.Commit() != TransactionStatus.Committed:
                report.append([wall_id, type_name, "ERROR: Revit rejected the changes"])
                continue
            if source_id in sources:
                sources[source_id]["layers"] = layer_walls
            created_total += len(layer_walls)
            result = "OK: {} walls, {} openings".format(len(layer_walls), openings)
            if warnings:
                result += " - WARNING: " + "; ".join(warnings)
            report.append([wall_id, type_name, result])
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            report.append([wall_id, type_name, "ERROR: {}".format(ex)])
            print(traceback.format_exc())

# Layer-to-layer corners between the split walls
if created_total:
    t = Transaction(doc, "Split Walls - Corners")
    options = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(SilentFailures())
    options.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(options)
    t.Start()
    try:
        corners = fix_corners(sources)
        if t.Commit() != TransactionStatus.Committed:
            corners = "ERROR: Revit rejected the corners"
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        corners = "ERROR: {}".format(ex)
        print(traceback.format_exc())

# Joins disallowed while splitting (so no other wall was dragged) are allowed again, and every wall end
# is checked. Revit joins walls again when a transaction is committed: the ends are checked once more,
# in a new transaction, until a check finds everything in place
unjoined = 0
if created_total:
    for attempt in range(5):
        t = Transaction(doc, "Split Walls - Joins")
        options = t.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(SilentFailures())
        options.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(options)
        t.Start()
        try:
            changed = restore_joins() if attempt == 0 else check_ends()
            if attempt and not changed:
                t.RollBack()                    # nothing moved: nothing was modified
                break
            unjoined += changed
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            print(traceback.format_exc())
            break

if created_total:
    tg.Assimilate()
else:
    tg.RollBack()

output.print_md("## Split Walls")
output.print_md("**{}** walls processed, **{}** layer walls, corners: **{}**.".format(len(report), created_total,
                                                                                     corners))
if unjoined:
    output.print_md("**{}** wall ends were left unjoined, exactly where they were: Revit could not join them "
                    "without moving the walls.".format(unjoined))
output.print_table(report, columns=["Wall", "Type", "Result"])

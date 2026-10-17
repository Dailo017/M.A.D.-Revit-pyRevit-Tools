# -*- coding: utf-8 -*-
__title__   = "Split\nWalls"
__doc__     = """Version = 2.3
Date    = 17.10.2026
________________________________________________________________
Description:

Splits each selected wall into one independent wall per layer.

BASIC (compound) walls:
1- One wall per layer, placed exactly at the layer position
   (copy of the original wall with a single-layer type).
2- Doors, windows and wall openings are copied into EVERY new
   wall, so deleting one of the new walls keeps the openings in
   the others.
3- Other hosted elements (fixtures...) are kept only in the
   layer closest to them.

STACKED walls:
1- For each member of the stack, one NEW basic wall per layer
   thicker than 5 cm (plaster, membranes... are ignored), with
   the position, base / top constraints and height of the member.
2- Each new wall gets a copy of the doors / windows that cut
   that member in the original (same type, parameters, sill
   and orientation).
3- Each new wall also gets a rectangular Wall Opening, uniform
   through the whole wall, with the LARGEST size the opening had
   in that layer of the original (reveals / rebates included).

Layer types are created (or reused) per layer, named
"<Material> (<width>cm)". The original wall is deleted. Only the
layers with a structural function keep the "Structural" flag.

Each wall is processed in its own transaction: if one wall
fails, the others are still split and the error is reported.
________________________________________________________________
How-To:

1. Select the walls (before or after clicking the button).
2. Review the report.
________________________________________________________________
Last Updates:
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

from Autodesk.Revit.DB import (Arc, BooleanOperationsType, BooleanOperationsUtils, BuiltInCategory, BuiltInParameter,
                               CompoundStructure, CompoundStructureLayer, CurveLoop, CylindricalFace, Element,
                               ElementClassFilter, ElementId, ElementTransformUtils, FailureProcessingResult,
                               FailureSeverity, FamilyInstance, FilteredElementCollector, GeometryCreationUtilities,
                               HostObjectUtils, IFailuresPreprocessor, Line, LocationPoint, MaterialFunctionAssignment,
                               Opening, Options, PlanarFace, ShellLayerType, Solid, SolidUtils, StorageType,
                               Transaction, TransactionGroup, TransactionStatus, Transform, Wall, WallKind, WallType,
                               XYZ)
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
MIN_LAYER = 0.0016      # feet (~0.5 mm) basic walls: thinner layers (membranes) are skipped
MIN_LAYER_STACKED = 5 / FT_TO_CM  # feet (5 cm) stacked walls: thinner layers (plaster...) are ignored
EPS       = 0.003       # feet (~1 mm)  margin of the layer bands used to measure the openings
TOL_Z     = 0.033       # feet (~1 cm)  vertical tolerance for stacked members / inserts
TOL_DIM   = 0.0003      # feet (~0.1 mm) width tolerance to reuse a layer type

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


def place_layer_wall(src_wall, layer_type, target, normal, layer_idx, all_targets, structural):
    """Copies the basic wall (with its inserts), applies the layer type and moves it to the layer position.
    Returns the number of openings in the new wall."""
    copied   = ElementTransformUtils.CopyElements(doc, List[ElementId]([src_wall.Id]), XYZ.Zero)
    new_wall = None
    for eid in copied:
        e = doc.GetElement(eid)
        if isinstance(e, Wall):
            new_wall = e
    if new_wall is None:
        raise Exception("The wall could not be copied")
    new_wall.Pinned = False

    # Non-opening hosted elements: only in the nearest layer (before moving the wall)
    for fi in hosted_instances(new_wall):
        pt = elem_point(fi)
        if pt is not None and nearest_index(pt, all_targets) != layer_idx:
            doc.Delete(fi.Id)

    new_wall.ChangeTypeId(layer_type.Id)
    set_param(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, 0)            # Location Line = Wall Centerline
    doc.Regenerate()
    move_to_curve(new_wall, target, normal)

    if not structural:
        set_param(new_wall, BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT, 0)
    doc.Regenerate()
    return len([i for i in new_wall.FindInserts(True, False, False, False) if is_opening(doc.GetElement(i))])


def split_basic_wall(wall):
    """Splits a basic wall. Returns (walls created, openings, warnings)."""
    cs = wall.WallType.GetCompoundStructure()
    if cs is None:
        raise Exception("Wall type without compound structure")
    layers = get_layers(cs, MIN_LAYER)
    if len(layers) < 2:
        return 0, 0, []

    curve, normal = wall.Location.Curve, wall.Orientation
    ext     = ext_face_from_key_ref(wall, cs)
    targets = [offset_curve(curve, ext - acc - layer.Width / 2.0, normal) for layer, acc in layers]
    pieces  = [(get_layer_type(wall.WallType, layer), layer.Function == MaterialFunctionAssignment.Structure)
               for layer, _ in layers]

    if wall.Pinned:
        wall.Pinned = False
    openings = 0
    for i, (layer_type, structural) in enumerate(pieces):
        openings += place_layer_wall(wall, layer_type, targets[i], normal, i, targets, structural)
    doc.Delete(wall.Id)
    return len(pieces), openings, []


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


def wall_solid(wall):
    """Union of the solids of the wall geometry (with all its cuts)."""
    opts = Options()
    opts.ComputeReferences = False
    geom   = wall.get_Geometry(opts)
    result = None
    for obj in (geom or []):
        if isinstance(obj, Solid) and obj.Volume > 1e-9:
            if result is None:
                result = obj
            else:
                result = BooleanOperationsUtils.ExecuteBooleanOperation(result, obj, BooleanOperationsType.Union)
    return result


def band_solid(curve, normal, a, b, z0, z1):
    """Solid between the offsets a < b of the curve (towards 'normal'), from z0 to z1."""
    if isinstance(curve, Line):
        delta = EPS
    elif isinstance(curve, Arc):
        delta = EPS / curve.Radius
    else:
        return None
    base = curve.Clone()
    base.MakeBound(curve.GetEndParameter(0) + delta, curve.GetEndParameter(1) - delta)
    base = base.CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, z0 - base.GetEndPoint(0).Z)))
    ca = offset_curve(base, a, normal)
    cb = offset_curve(base, b, normal)
    loop = CurveLoop()
    loop.Append(ca)
    loop.Append(Line.CreateBound(ca.GetEndPoint(1), cb.GetEndPoint(1)))
    loop.Append(cb.CreateReversed())
    loop.Append(Line.CreateBound(cb.GetEndPoint(0), ca.GetEndPoint(0)))
    return GeometryCreationUtilities.CreateExtrusionGeometry(List[CurveLoop]([loop]), XYZ.BasisZ, z1 - z0)


def uz_extents(solid, curve):
    """(u0, u1, z0, z1): extents of the solid along the curve (curve parameter) and in height."""
    us, zs = [], []
    for edge in solid.Edges:
        for p in edge.Tessellate():
            us.append(curve.Project(p).Parameter)
            zs.append(p.Z)
    return (min(us), max(us), min(zs), max(zs)) if us else None


def insert_in_rect(elem, curve, rect):
    """True if the opening element lies inside the rectangle (u0, u1, z0, z1)."""
    pt      = elem_point(elem)
    z_range = opening_z_range(elem)
    if pt is None or z_range is None:
        return False
    u = curve.Project(pt).Parameter
    return (rect[0] - TOL_Z <= u <= rect[1] + TOL_Z) and z_range[1] > rect[2] and z_range[0] < rect[3]


def layer_holes(member, solid, a, b):
    """Openings of the original member inside the layer band [a, b] (distance from the member curve
    towards the exterior), as uniform rectangles (u0, u1, z0, z1) with their LARGEST extents."""
    curve, normal = member["curve"], member["normal"]
    zb, zt = member["zmin"], member["zmax"]
    band   = band_solid(curve, normal, a + EPS, b - EPS, zb + EPS, zt - EPS)
    if band is None:
        return None
    voids = BooleanOperationsUtils.ExecuteBooleanOperation(band, solid, BooleanOperationsType.Difference)

    holes = []
    for lump in SolidUtils.SplitVolumes(voids):
        if lump.Volume < 1e-4:
            continue
        rect = uz_extents(lump, curve)
        # Only voids of an opening of the original wall (not end joins / top profile)
        if rect is None or not any(insert_in_rect(e, curve, rect) for e in member["all_inserts"]):
            continue
        u0, u1, z0, z1 = rect
        if z0 <= zb + 3 * EPS:
            z0 = zb
        if z1 >= zt - 3 * EPS:
            z1 = zt
        holes.append((u0, u1, z0, z1))
    return holes


def stacked_members(wall):
    """Data of each member of the stacked wall (bottom -> top), measured on the original."""
    members = []
    for mid in wall.GetStackedWallMemberIds():
        member = doc.GetElement(mid)
        bb     = member.get_BoundingBox(None)
        if bb is None or member.WallType.GetCompoundStructure() is None:
            raise Exception("Stacked member {} has no geometry / structure".format(member.Id))
        members.append((bb.Min.Z, bb.Max.Z, member))
    members.sort(key=lambda m: m[0])

    # Openings of the stacked wall (hosted by the stacked wall or by its members) + embedded walls
    doors, all_inserts = {}, {}
    for host in [wall] + [m[2] for m in members]:
        for eid in host.FindInserts(True, False, True, False):
            e = doc.GetElement(eid)
            if e is None:
                continue
            all_inserts[eid.ToString()] = e
            if isinstance(e, FamilyInstance) and is_opening(e):
                doors[eid.ToString()] = e
    doors, all_inserts = list(doors.values()), list(all_inserts.values())
    cut_sets = [cutting_ids(m[2]) for m in members]
    found    = set().union(*cut_sets) if cut_sets else set()

    result, z0 = [], members[0][0]
    for i, (zmin, zmax, member) in enumerate(members):
        is_top = i == len(members) - 1
        top_z  = zmax if is_top else members[i + 1][0]
        curve  = member.Location.Curve
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

        result.append({"wall": member, "type": member.WallType, "cs": cs, "curve": curve,
                       "normal": member.Orientation, "ext": ext, "rel_bottom": zmin - z0,
                       "height": top_z - zmin, "zmin": zmin, "zmax": top_z, "is_top": is_top,
                       "doors": wanted, "all_inserts": all_inserts})
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
    """Creates in 'wall' a copy of the original door / window (type, parameters, sill, orientation)."""
    level = doc.GetElement(orig.LevelId) or doc.GetElement(wall.LevelId)
    point = point_on_wall(orig.Location.Point, wall)
    inst  = doc.Create.NewFamilyInstance(XYZ(point.X, point.Y, level.ProjectElevation),
                                         orig.Symbol, wall, level, StructuralType.NonStructural)
    copy_instance_params(orig, inst)
    doc.Regenerate()
    if inst.CanFlipFacing and inst.FacingOrientation.DotProduct(orig.FacingOrientation) < 0:
        inst.flipFacing()
        doc.Regenerate()
    if inst.CanFlipHand and inst.HandOrientation.DotProduct(orig.HandOrientation) < 0:
        inst.flipHand()


def create_hole(wall, curve, hole):
    """Creates a rectangular wall opening in 'wall' from a hole measured on the original curve."""
    u0, u1, z0, z1 = hole
    p0 = curve.Evaluate(u0, False)
    p1 = curve.Evaluate(u1, False)
    doc.Create.NewOpening(wall, point_on_wall(XYZ(p0.X, p0.Y, z0), wall), point_on_wall(XYZ(p1.X, p1.Y, z1), wall))


def create_layer_wall(stacked, member, layer_type, target, structural):
    """Creates a new basic wall for one layer of a stacked member, with the member's constraints."""
    base_level = stacked.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
    base_off   = stacked.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble() + member["rel_bottom"]
    top_level  = stacked.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()

    level_z = doc.GetElement(base_level).ProjectElevation
    curve   = target.CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, level_z - target.GetEndPoint(0).Z)))
    new_wall = Wall.Create(doc, curve, layer_type.Id, base_level, member["height"], base_off, False, structural)

    if member["is_top"]:
        if top_level != ElementId.InvalidElementId:
            set_param(new_wall, BuiltInParameter.WALL_HEIGHT_TYPE, top_level)
            set_param(new_wall, BuiltInParameter.WALL_TOP_OFFSET,
                      stacked.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).AsDouble())
        else:
            set_param(new_wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
                      stacked.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble() - member["rel_bottom"])
    copy_wall_params(stacked, new_wall)

    # Same exterior side as the member, then exact position of the layer centerline
    set_param(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, 0)
    doc.Regenerate()
    if new_wall.Orientation.DotProduct(member["normal"]) < 0:
        new_wall.Flip()
        doc.Regenerate()
    move_to_curve(new_wall, target, member["normal"])
    doc.Regenerate()
    return new_wall


def split_stacked_wall(wall):
    """Rebuilds a stacked wall as basic walls (one per layer > 5 cm of each member).
    Returns (walls created, doors/windows + openings created, warnings)."""
    stacked_structural = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    stacked_structural = bool(stacked_structural and stacked_structural.AsInteger())

    # 1- Measure everything on the original (before modifying anything)
    pieces, warnings = [], []
    for member in stacked_members(wall):
        layers  = get_layers(member["cs"], MIN_LAYER_STACKED)
        solid   = None
        if member["all_inserts"]:
            try:
                solid = wall_solid(member["wall"])
            except Exception:
                solid = None
            if solid is None:
                warnings.append("openings of member {} could not be measured".format(member["wall"].Id))
        for layer, acc in layers:
            b      = member["ext"] - acc                   # exterior side of the layer
            target = offset_curve(member["curve"], b - layer.Width / 2.0, member["normal"])
            holes  = []
            if solid is not None:
                try:
                    holes = layer_holes(member, solid, b - layer.Width, b) or []
                except Exception:
                    warnings.append("openings of a layer of member {} could not be measured".format(member["wall"].Id))
            if member["cs"].LayerCount == 1:
                layer_type = member["type"]                 # single-layer member keeps its own type
            else:
                layer_type = get_layer_type(member["type"], layer)
            structural = stacked_structural and layer.Function == MaterialFunctionAssignment.Structure
            pieces.append((member, layer_type, target, structural, holes))

    if not pieces:
        return 0, 0, warnings

    # 2- Create the new walls with their doors / windows and uniform openings
    created_openings, failed = 0, 0
    for member, layer_type, target, structural, holes in pieces:
        new_wall = create_layer_wall(wall, member, layer_type, target, structural)
        for door in member["doors"]:
            try:
                recreate_door(door, new_wall)
                created_openings += 1
            except Exception:
                failed += 1
        for hole in holes:
            try:
                create_hole(new_wall, member["curve"], hole)
                created_openings += 1
            except Exception:
                failed += 1
    if failed:
        warnings.append("{} doors/windows/openings could not be created".format(failed))

    if wall.Pinned:
        wall.Pinned = False
    doc.Delete(wall.Id)
    return len(pieces), created_openings, warnings


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
walls = get_selected_walls()
if not walls:
    forms.alert("Select at least one basic or stacked wall.", exitscript=True)

for wt in FilteredElementCollector(doc).OfClass(WallType):
    TYPES[get_name(wt)] = wt

report = []         # [wall id, type, result]
created_total = 0

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
            if wall.IsStackedWall:
                created, openings, warnings = split_stacked_wall(wall)
            else:
                created, openings, warnings = split_basic_wall(wall)
            if created == 0:
                t.RollBack()
                report.append([wall_id, type_name, "Skipped: only one layer"])
                continue
            if t.Commit() != TransactionStatus.Committed:
                report.append([wall_id, type_name, "ERROR: Revit rejected the changes"])
                continue
            created_total += created
            result = "OK: {} walls, {} openings".format(created, openings)
            if warnings:
                result += " - WARNING: " + "; ".join(warnings)
            report.append([wall_id, type_name, result])
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            report.append([wall_id, type_name, "ERROR: {}".format(ex)])
            print(traceback.format_exc())

if created_total:
    tg.Assimilate()
else:
    tg.RollBack()

output.print_md("## Split Walls")
output.print_md("**{}** walls processed, **{}** new walls created.".format(len(report), created_total))
output.print_table(report, columns=["Wall", "Type", "Result"])

# -*- coding: utf-8 -*-
__title__   = "Sync Doors\nWindows"
__doc__     = """Version = 2.0
Date    = 14.10.2026
________________________________________________________________
Description:

Synchronizes the doors and windows of a linked ARC model
into the active STR model using ONE door family and ONE
window family of the active model:
1- Creates the types needed for each width x height found
   in the linked model (reuses existing types when they match).
2- Places each element in the matching wall of the active model
   (same position along the wall, same bottom elevation, same
   facing / hand orientation).
3- Updates elements already synced (type, dimensions, position,
   sill height, orientation, phase).
4- Deletes synced elements whose source no longer exists in the
   linked model (or no longer sits in a wall of this model).
5- Any door/window of this model overlapping the position of an
   ARC opening is deleted and replaced by the ARC one. If two ARC
   openings overlap each other, only one is copied.
6- ARC doors/windows that do not cut through their wall
   (decorative: reliefs, recesses, thickness changes) are ignored.

Synced elements are tracked with Extensible Storage (the
"Comments" parameter is left free). Elements synced with v1.0
("ARC_SYNC:" in Comments) are migrated automatically.
________________________________________________________________
How-To:

1. Click the button and select the linked ARC model.
2. Pick the door family and the window family of this model
   (or "Do not sync" to skip a category).
3. Pick which dimensions to copy (nominal or rough opening).
4. Confirm the summary and review the report.
________________________________________________________________
Last Updates:
- [14.10.2026] v2.0 One family per category, types by dimensions,
                    wall matching by direction, per-element
                    transactions, Extensible Storage tracking.
- [05.10.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
import clr
clr.AddReference('System')
from System import Guid, String
from System.Collections.Generic import List

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ElementId, ElementMulticategoryFilter,
                               ElementTransformUtils, FailureProcessingResult, FailureSeverity,
                               FamilyInstance, FamilyPlacementType, FamilySymbol, FilteredElementCollector,
                               IFailuresPreprocessor, Level, Line, LocationCurve, LocationPoint, Phase,
                               RevitLinkInstance, StorageType, Transaction, TransactionGroup,
                               TransactionStatus, Wall, WallKind, XYZ, Options, Solid, GeometryInstance,
                               SolidCurveIntersectionOptions)
from Autodesk.Revit.DB.ExtensibleStorage import AccessLevel, Entity, Schema, SchemaBuilder
from Autodesk.Revit.DB.Structure import StructuralType
from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document
output = script.get_output()

FT_TO_MM        = 304.8
TOL_POS         = 0.01        # feet (~3 mm)  position tolerance
TOL_DIM         = 0.003       # feet (~1 mm)  dimension tolerance
LEVEL_TOL       = 0.5         # feet (~15 cm) a level slightly above the opening bottom is still valid
MAX_WALL_OFFSET = 1.0         # feet (~30 cm) extra distance allowed between ARC opening and STR wall
PARALLEL_COS    = 0.985       # ~10° max angle between ARC host wall and STR wall
OVERLAP_TOL     = 0.033       # feet (~1 cm)  two openings overlap if they share more than this
DEFAULT_SIZE    = 1.0         # feet (~30 cm) size assumed when an opening has no width/height parameter

LEGACY_PREFIX   = "ARC_SYNC:"  # v1.0 tag in Comments
SCHEMA_GUID     = Guid("6b1f2c1e-5a8d-4c63-9b0e-3f7d2a91c4e8")
SCHEMA_NAME     = "MAD_SyncDoorsWindows"
F_SOURCE        = "SourceUid"
F_LINK          = "LinkUid"

DOORS, WINDOWS  = "Doors", "Windows"
CATEGORIES      = {DOORS: BuiltInCategory.OST_Doors, WINDOWS: BuiltInCategory.OST_Windows}
doors_cat_id    = ElementId(BuiltInCategory.OST_Doors)

BIPS_WIDTH         = [BuiltInParameter.DOOR_WIDTH, BuiltInParameter.WINDOW_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM]
BIPS_HEIGHT        = [BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.WINDOW_HEIGHT, BuiltInParameter.FAMILY_HEIGHT_PARAM]
BIPS_ROUGH_WIDTH   = [BuiltInParameter.FAMILY_ROUGH_WIDTH_PARAM]
BIPS_ROUGH_HEIGHT  = [BuiltInParameter.FAMILY_ROUGH_HEIGHT_PARAM]
NAMES_WIDTH        = ["Width", "Ancho", "Anchura"]
NAMES_HEIGHT       = ["Height", "Altura", "Alto"]
NAMES_ROUGH_WIDTH  = ["Rough Width", "Ancho aproximado", "Ancho de hueco"]
NAMES_ROUGH_HEIGHT = ["Rough Height", "Altura aproximada", "Altura de hueco"]

NO_SYNC = "<Do not sync>"


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝
#==================================================
# ── Generic utilities ─────────────────────────────
def to_mm(value):
    return int(round(value * FT_TO_MM)) if value is not None else None

def type_name(symbol):
    return symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()

def category_key(element):
    return DOORS if element.Category.Id == doors_cat_id else WINDOWS

def describe(src):
    if src is None:
        return "-"
    return "{} : {} (ARC id {})".format(src.Symbol.Family.Name, type_name(src.Symbol), src.Id)

def describe_instance(e):
    return "{} : {} (id {})".format(e.Symbol.Family.Name, type_name(e.Symbol), e.Id)

def size_text(pl):
    return "{} x {}".format(to_mm(pl.width) or "?", to_mm(pl.height) or "?")

def find_parameter(element, bips, names, writable=False):
    """First length parameter found on the element itself (by built-in parameter, then by name)."""
    candidates = [element.get_Parameter(bip) for bip in bips] + [element.LookupParameter(n) for n in names]
    for p in candidates:
        if p and p.StorageType == StorageType.Double and (not writable or not p.IsReadOnly):
            return p
    return None

def read_length(element, bips, names):
    """Value of a length parameter on the instance or, if not there, on its type."""
    holders = [element, element.Symbol] if isinstance(element, FamilyInstance) else [element]
    for e in holders:
        p = find_parameter(e, bips, names)
        if p and p.HasValue:
            return p.AsDouble()
    return None

def set_length(element, bips, names, value):
    """Writes a length parameter of the element. Returns True if the value changed."""
    p = find_parameter(element, bips, names, writable=True)
    if value is None or p is None or abs(p.AsDouble() - value) <= TOL_DIM:
        return False
    p.Set(value)
    return True

def dims_equal(a, b):
    return a is None or b is None or abs(a - b) <= TOL_DIM

def tangent_2d(curve, param):
    v = curve.ComputeDerivatives(param, False).BasisX
    v = XYZ(v.X, v.Y, 0)
    return v.Normalize() if v.GetLength() > 1e-9 else None

def project_on_curve(curve, point):
    """Projects the point (in plan) on the curve. Returns IntersectionResult or None."""
    return curve.Project(XYZ(point.X, point.Y, curve.GetEndPoint(0).Z))


# ── Tracking (Extensible Storage) ─────────────────
def get_schema():
    schema = Schema.Lookup(SCHEMA_GUID)
    if schema:
        return schema
    builder = SchemaBuilder(SCHEMA_GUID)
    builder.SetSchemaName(SCHEMA_NAME)
    builder.SetReadAccessLevel(AccessLevel.Public)
    builder.SetWriteAccessLevel(AccessLevel.Public)
    builder.AddSimpleField(F_SOURCE, clr.GetClrType(String))
    builder.AddSimpleField(F_LINK, clr.GetClrType(String))
    return builder.Finish()

schema = get_schema()

def read_tag(element):
    """(source UniqueId, link UniqueId or None for legacy tags) or None if the element is not synced."""
    entity = element.GetEntity(schema)
    if entity.IsValid():
        return entity.Get[String](F_SOURCE), entity.Get[String](F_LINK)
    p   = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    txt = p.AsString() if p else None
    if txt and txt.startswith(LEGACY_PREFIX):
        return txt[len(LEGACY_PREFIX):], None
    return None

def write_tag(element, source_uid, link_uid):
    entity = Entity(schema)
    entity.Set[String](F_SOURCE, source_uid)
    entity.Set[String](F_LINK, link_uid)
    element.SetEntity(entity)
    p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)   # clean v1.0 tag
    if p and not p.IsReadOnly and (p.AsString() or "").startswith(LEGACY_PREFIX):
        p.Set("")


# ── Transactions ──────────────────────────────────
class FailureCollector(IFailuresPreprocessor):
    """Deletes warnings silently; on errors rolls back the transaction and keeps the message."""
    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, accessor):
        result = FailureProcessingResult.Continue
        for msg in accessor.GetFailureMessages():
            if msg.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(msg)
            else:
                self.errors.append(msg.GetDescriptionText())
                result = FailureProcessingResult.ProceedWithRollBack
        return result

def run_transaction(name, func, *args):
    """Runs func inside its own transaction. Returns (ok, result, error message)."""
    t         = Transaction(doc, name)
    collector = FailureCollector()
    options   = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(collector)
    options.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(options)
    t.Start()
    try:
        result = func(*args)
    except Exception as ex:
        t.RollBack()
        return False, None, str(ex)
    if t.Commit() != TransactionStatus.Committed:
        return False, None, "; ".join(collector.errors) or "transaction rolled back"
    return True, result, None


# ── Target families (active model) ────────────────
class TargetFamily(object):
    """One family of the active model and the types created/reused per dimensions."""
    def __init__(self, family):
        self.family  = family
        self.symbols = sorted([doc.GetElement(i) for i in family.GetFamilySymbolIds()], key=type_name)
        self.base    = self.symbols[0]
        self.width_on_type  = find_parameter(self.base, BIPS_WIDTH, NAMES_WIDTH, writable=True) is not None
        self.height_on_type = find_parameter(self.base, BIPS_HEIGHT, NAMES_HEIGHT, writable=True) is not None
        self.cache   = {}
        self.created = []

    def type_key(self, width, height):
        return (to_mm(width) if self.width_on_type else None,
                to_mm(height) if self.height_on_type else None)

    def symbol_for(self, width, height):
        """Type with those dimensions (only the dimensions driven by the type). Creates it if needed."""
        key = self.type_key(width, height)
        if key in self.cache:
            return self.cache[key]
        if key == (None, None):
            symbol = self.base
        else:
            symbol = self._find(width, height) or self._create(key, width, height)
        if not symbol.IsActive:
            symbol.Activate()
        self.cache[key] = symbol
        return symbol

    def _find(self, width, height):
        for s in self.symbols:
            w = read_length(s, BIPS_WIDTH, NAMES_WIDTH)
            h = read_length(s, BIPS_HEIGHT, NAMES_HEIGHT)
            if (not self.width_on_type or dims_equal(w, width)) and (not self.height_on_type or dims_equal(h, height)):
                return s
        return None

    def _create(self, key, width, height):
        name     = " x ".join(str(v) for v in key if v is not None)
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


# ── Levels, phases and walls of the active model ──
levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.ProjectElevation)
phases = {ph.Name: ph for ph in FilteredElementCollector(doc).OfClass(Phase).ToElements()}

def level_for(z):
    below = [l for l in levels if l.ProjectElevation <= z + LEVEL_TOL]
    return below[-1] if below else levels[0]

walls = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType().ToElements():
    loc = w.Location
    bb  = w.get_BoundingBox(None)
    if isinstance(loc, LocationCurve) and loc.Curve.IsBound and bb and w.WallType.Kind != WallKind.Curtain:
        walls.append((w, loc.Curve, bb.Min.Z, bb.Max.Z))

def find_wall(point, src_tangent, z_mid):
    """Wall of the active model that contains the opening: covers z_mid, is parallel to the ARC host
    wall, the point projects inside its location line and it is the closest one in plan."""
    best, best_pt, best_dist = None, None, None
    for wall, curve, z_min, z_max in walls:
        if not (z_min - TOL_POS <= z_mid <= z_max + TOL_POS):
            continue
        res = project_on_curve(curve, point)
        if res is None or res.Distance > wall.Width + MAX_WALL_OFFSET:
            continue
        if not (curve.GetEndParameter(0) + 1e-6 < res.Parameter < curve.GetEndParameter(1) - 1e-6):
            continue                                    # projection clamped to an end: outside the wall
        tangent = tangent_2d(curve, res.Parameter)
        if src_tangent and tangent and abs(tangent.DotProduct(src_tangent)) < PARALLEL_COS:
            continue
        if best_dist is None or res.Distance < best_dist:
            best, best_pt, best_dist = wall, res.XYZPoint, res.Distance
    return best, best_pt


# ── Overlaps ──────────────────────────────────────
class Footprint(object):
    """Extent of an opening in its wall: position on the location line, width and vertical range."""
    def __init__(self, wall, point, width, bottom, height):
        res           = project_on_curve(wall.Location.Curve, point)
        self.wall_key = wall.UniqueId
        self.point    = res.XYZPoint if res else point
        self.width    = width or DEFAULT_SIZE
        self.bottom   = bottom
        self.top      = bottom + (height or DEFAULT_SIZE)

    def overlaps(self, other):
        if self.wall_key != other.wall_key:
            return False
        along    = (self.width + other.width) / 2.0 - self.point.DistanceTo(other.point)
        vertical = min(self.top, other.top) - max(self.bottom, other.bottom)
        return along > OVERLAP_TOL and vertical > OVERLAP_TOL

def instance_footprint(inst):
    """Footprint of a door/window of the active model, or None if it is not hosted in a basic wall."""
    host = inst.Host
    if not isinstance(host, Wall) or not isinstance(host.Location, LocationCurve) or not isinstance(inst.Location, LocationPoint):
        return None
    level  = doc.GetElement(inst.LevelId)
    p_sill = inst.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    bottom = (level.ProjectElevation if level else inst.Location.Point.Z) + (p_sill.AsDouble() if p_sill else 0.0)
    return Footprint(host, inst.Location.Point,
                     read_length(inst, BIPS_WIDTH, NAMES_WIDTH), bottom, read_length(inst, BIPS_HEIGHT, NAMES_HEIGHT))


# ╔═╗╔═╗╦  ╔═╗╔═╗╔╦╗╦╔═╗╔╗╔
# ╚═╗║╣ ║  ║╣ ║   ║ ║║ ║║║║
# ╚═╝╚═╝╩═╝╚═╝╚═╝ ╩ ╩╚═╝╝╚╝
#==================================================
# 1- Linked ARC model
links = [l for l in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements() if l.GetLinkDocument()]
if not links:
    forms.alert("There are no loaded Revit links in this model.", exitscript=True)

links_dict = {l.Name: l for l in links}
if len(links) == 1:
    link_instance = links[0]
else:
    chosen = forms.SelectFromList.show(sorted(links_dict.keys()), title="Select the linked ARC model",
                                       button_name="Select", multiselect=False)
    if not chosen:
        script.exit()
    link_instance = links_dict[chosen]

linked_doc     = link_instance.GetLinkDocument()
transform_link = link_instance.GetTotalTransform()
link_uid       = link_instance.UniqueId

# 2- Doors and windows of the linked model that can be synced
def source_bottom_z_link(src):
    """Elevation (internal coordinates of the LINKED model) of the bottom of the ARC opening."""
    arc_level = linked_doc.GetElement(src.LevelId) or linked_doc.GetElement(src.Host.LevelId)
    p_sill    = src.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    return arc_level.ProjectElevation + (p_sill.AsDouble() if p_sill else 0.0)

wall_solids_cache = {}
def wall_solids(wall):
    """Solids of a linked wall (already cut by its doors/windows), cached per wall."""
    if wall.UniqueId not in wall_solids_cache:
        solids, geom = [], wall.get_Geometry(Options())
        for g in (geom or []):
            items = g.GetInstanceGeometry() if isinstance(g, GeometryInstance) else [g]
            solids.extend(s for s in items if isinstance(s, Solid) and s.Volume > 0)
        wall_solids_cache[wall.UniqueId] = solids
    return wall_solids_cache[wall.UniqueId]

def material_along(solids, line):
    options = SolidCurveIntersectionOptions()
    for s in solids:
        hit = s.IntersectWithCurve(line, options)
        if sum(hit.GetCurveSegment(i).Length for i in range(hit.SegmentCount)) > TOL_POS:
            return True
    return False

def cuts_host(src):
    """True if the ARC door/window really opens its wall: a line through the wall thickness at the
    opening (center and +-1/4 width, mid height) finds no wall material. Decorative families
    (reliefs, recesses, thickness changes) leave material and return False.
    When the check cannot be done, the element is considered a real opening."""
    try:
        wall   = src.Host
        solids = wall_solids(wall)
        curve  = wall.Location.Curve
        point  = src.Location.Point
        res    = project_on_curve(curve, point)
        tan    = tangent_2d(curve, res.Parameter) if res else None
        if not solids or tan is None:
            return True
        normal = XYZ(-tan.Y, tan.X, 0)
        reach  = wall.Width + MAX_WALL_OFFSET
        width  = read_length(src, BIPS_WIDTH, NAMES_WIDTH) or DEFAULT_SIZE
        height = read_length(src, BIPS_HEIGHT, NAMES_HEIGHT) or DEFAULT_SIZE
        center = XYZ(point.X, point.Y, source_bottom_z_link(src) + height / 2.0)
        for offset in (0.0, -width / 4.0, width / 4.0):
            c = center + tan * offset
            if not material_along(solids, Line.CreateBound(c - normal * reach, c + normal * reach)):
                return True
        return False
    except Exception:
        return True

def skip_reason(e):
    if not isinstance(e, FamilyInstance) or e.SuperComponent is not None:
        return "nested"
    if e.DesignOption is not None and not e.DesignOption.IsPrimary:
        return "secondary design option"
    p_dem = e.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED)
    if p_dem and p_dem.AsElementId() != ElementId.InvalidElementId:
        return "demolished"
    if not isinstance(e.Host, Wall) or e.Host.WallType.Kind == WallKind.Curtain:
        return "not hosted in a basic wall"
    if not isinstance(e.Location, LocationPoint):
        return "no location point"
    if not cuts_host(e):
        return "does not cut its wall (decorative)"
    return None

cat_filter = ElementMulticategoryFilter(List[BuiltInCategory](CATEGORIES.values()))
sources, skipped = {DOORS: [], WINDOWS: []}, {}
for e in FilteredElementCollector(linked_doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElements():
    reason = skip_reason(e)
    if reason:
        skipped[reason] = skipped.get(reason, 0) + 1
    else:
        sources[category_key(e)].append(e)

# 3- One family per category
def wall_hosted_families(bic):
    families = {}
    for s in FilteredElementCollector(doc).OfCategory(bic).OfClass(FamilySymbol).ToElements():
        f = s.Family
        if not f.IsInPlace and f.FamilyPlacementType == FamilyPlacementType.OneLevelBasedHosted:
            families[f.Name] = f
    return families

targets = {}
for cat in (DOORS, WINDOWS):
    families = wall_hosted_families(CATEGORIES[cat])
    n_src    = len(sources[cat])
    n_fams   = len(set(s.Symbol.Family.Name for s in sources[cat]))
    if not families:
        output.print_md("- No wall-hosted {0} family loaded in this model: {0} skipped.".format(cat.lower()))
        continue
    chosen = forms.SelectFromList.show([NO_SYNC] + sorted(families.keys()),
                                       title="{} family  ({} {} in {} ARC families)".format(cat, n_src, cat.lower(), n_fams),
                                       button_name="Use this family", multiselect=False)
    if not chosen:
        script.exit()
    if chosen != NO_SYNC:
        targets[cat] = TargetFamily(families[chosen])

if not targets:
    forms.alert("No family selected. Nothing to sync.", exitscript=True)

# 4- Dimensions to copy
OPT_NOMINAL, OPT_ROUGH = "Nominal (Width / Height)", "Rough opening (Rough Width / Rough Height)"
dims_mode = forms.CommandSwitchWindow.show([OPT_NOMINAL, OPT_ROUGH], message="Dimensions to copy from the linked model:")
if not dims_mode:
    script.exit()
use_rough = dims_mode == OPT_ROUGH


# ╔═╗╦  ╔═╗╔╗╔
# ╠═╝║  ╠═╣║║║
# ╩  ╩═╝╩ ╩╝╚╝
#==================================================
# 5- Read-only analysis: where and how each ARC element must exist in this model.
def source_dimensions(src):
    w = h = None
    if use_rough:
        w = read_length(src, BIPS_ROUGH_WIDTH, NAMES_ROUGH_WIDTH)
        h = read_length(src, BIPS_ROUGH_HEIGHT, NAMES_ROUGH_HEIGHT)
    w = w or read_length(src, BIPS_WIDTH, NAMES_WIDTH)
    h = h or read_length(src, BIPS_HEIGHT, NAMES_HEIGHT)
    return w, h

def source_bottom_z(src):
    """Elevation (internal coordinates of THIS model) of the bottom of the ARC opening."""
    return transform_link.OfPoint(XYZ(0, 0, source_bottom_z_link(src))).Z

def source_tangent(src):
    curve = src.Host.Location.Curve if isinstance(src.Host.Location, LocationCurve) else None
    res   = project_on_curve(curve, src.Location.Point) if curve else None
    t     = tangent_2d(curve, res.Parameter) if res else None
    return transform_link.OfVector(t) if t else None

def source_phase(src):
    p  = src.get_Parameter(BuiltInParameter.PHASE_CREATED)
    ph = linked_doc.GetElement(p.AsElementId()) if p else None
    return phases.get(ph.Name) if ph else None

class Plan(object):
    pass

plans, no_wall, errors = [], [], []
for cat, target in targets.items():
    for src in sources[cat]:
        try:
            pl          = Plan()
            pl.src, pl.cat, pl.target = src, cat, target
            pl.width, pl.height = source_dimensions(src)
            pl.bottom_z = source_bottom_z(src)
            pl.level    = level_for(pl.bottom_z)
            z_mid       = pl.bottom_z + (pl.height / 2.0 if pl.height else 1.0)
            point       = transform_link.OfPoint(src.Location.Point)
            pl.wall, pl.point = find_wall(point, source_tangent(src), z_mid)
            pl.facing   = transform_link.OfVector(src.FacingOrientation)
            pl.hand     = transform_link.OfVector(src.HandOrientation)
            pl.phase    = source_phase(src)
            (plans if pl.wall else no_wall).append(pl)
        except Exception as ex:
            errors.append((src, "analysis: {}".format(ex)))

# Synced elements already in this model (only this link and the synced categories)
existing, duplicates = {}, []
for e in FilteredElementCollector(doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElements():
    tag = read_tag(e)
    if not tag or category_key(e) not in targets:
        continue
    src_uid, tag_link = tag
    if tag_link not in (None, link_uid):
        continue
    if src_uid in existing:
        duplicates.append(e)
    else:
        existing[src_uid] = e

# ARC doors/windows overlapping each other in the same STR wall: only one is copied
# (the one already synced, otherwise the biggest).
for pl in plans:
    pl.footprint = Footprint(pl.wall, pl.point, pl.width, pl.bottom_z, pl.height)

def plan_priority(pl):
    return (pl.src.UniqueId in existing, (pl.width or 0) * (pl.height or 0))

kept, arc_overlaps = [], []
for pl in sorted(plans, key=plan_priority, reverse=True):
    rival = next((k for k in kept if k.footprint.overlaps(pl.footprint)), None)
    if rival:
        arc_overlaps.append((pl, rival))
    else:
        kept.append(pl)
plans = sorted(kept, key=lambda p: p.cat)

# Doors/windows of THIS model (placed by hand, synced before tracking, etc.) that overlap
# the position of an ARC opening: they are deleted and replaced by the ARC one.
tracked_uids = set(e.UniqueId for e in existing.values())
by_wall      = {}
for e in FilteredElementCollector(doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElements():
    if not isinstance(e, FamilyInstance) or e.UniqueId in tracked_uids:
        continue
    tag = read_tag(e)
    if tag and tag[1] not in (None, link_uid):
        continue                                        # synced from another link
    fp = instance_footprint(e)
    if fp:
        by_wall.setdefault(fp.wall_key, []).append((e, fp))

planned_uids = set(pl.src.UniqueId for pl in plans)
error_uids   = set(src.UniqueId for src, _ in errors)          # analysis failed: leave them untouched
to_delete    = {}                                             # UniqueId -> (element, description, reason)
for uid, e in existing.items():
    if uid not in planned_uids and uid not in error_uids:
        to_delete[e.UniqueId] = (e, describe_instance(e), "source removed / not copied")
for e in duplicates:
    to_delete[e.UniqueId] = (e, describe_instance(e), "duplicated sync")
replaced_uids = set()
for pl in plans:
    pl.replaces = []                     # deleted in the same transaction that creates/updates pl
    for e, fp in by_wall.get(pl.footprint.wall_key, []):
        if e.UniqueId not in to_delete and e.UniqueId not in replaced_uids and fp.overlaps(pl.footprint):
            pl.replaces.append((e, describe_instance(e)))
            replaced_uids.add(e.UniqueId)
n_overlap = len(replaced_uids)

n_new = len([pl for pl in plans if pl.src.UniqueId not in existing])

msg = ("Link: {}\n\n"
       "To create:  {}\n"
       "To check / update:  {}\n"
       "To delete (obsolete):  {}\n"
       "Overlapping doors/windows to replace by the ARC one:  {}\n"
       "ARC overlapping duplicates (only one copied):  {}\n"
       "ARC elements without a matching wall here:  {}\n\n"
       "Continue?").format(link_instance.Name, n_new, len(plans) - n_new, len(to_delete), n_overlap,
                           len(arc_overlaps), len(no_wall))
if not forms.alert(msg, title="Sync Doors / Windows", yes=True, no=True):
    script.exit()


# ╔═╗╦ ╦╔╗╔╔═╗
# ╚═╗╚╦╝║║║║
# ╚═╝ ╩ ╝╚╝╚═╝
#==================================================
def needs_recreate(inst, pl):
    """True if the existing element cannot be adapted and must be deleted and created again."""
    if inst.Host is None or inst.Host.Id != pl.wall.Id:
        return True                                   # hosted families cannot change host
    if inst.LevelId != pl.level.Id:
        return True
    if not isinstance(pl.wall.Location.Curve, Line):  # curved wall: moving along a chord is not valid
        res = project_on_curve(pl.wall.Location.Curve, inst.Location.Point)
        return res is None or res.XYZPoint.DistanceTo(pl.point) > TOL_POS
    return False

def move_along_wall(inst, pl):
    res   = project_on_curve(pl.wall.Location.Curve, inst.Location.Point)
    delta = pl.point - res.XYZPoint
    if delta.GetLength() <= TOL_POS:
        return False
    ElementTransformUtils.MoveElement(doc, inst.Id, delta)
    return True

def sync_element(pl, inst):
    """Creates or updates the element of the plan. Returns (instance, status, list of changes)."""
    changes = []
    for e, _ in pl.replaces:
        if e.IsValidObject:
            doc.Delete(e.Id)
    if pl.replaces:
        changes.append("replaced {} overlapping".format(len(pl.replaces)))

    if inst is not None and needs_recreate(inst, pl):
        doc.Delete(inst.Id)
        inst = None
        changes.append("recreated")

    if inst is None:
        point  = XYZ(pl.point.X, pl.point.Y, pl.level.ProjectElevation)
        inst   = doc.Create.NewFamilyInstance(point, pl.symbol, pl.wall, pl.level, StructuralType.NonStructural)
        status = "updated" if "recreated" in changes else "created"
    else:
        status = "updated"
        if inst.Symbol.Id != pl.symbol.Id:
            inst.ChangeTypeId(pl.symbol.Id)
            changes.append("type")
        if move_along_wall(inst, pl):
            changes.append("position")

    write_tag(inst, pl.src.UniqueId, link_uid)

    p_sill = inst.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    sill   = pl.bottom_z - pl.level.ProjectElevation
    if p_sill and not p_sill.IsReadOnly and abs(p_sill.AsDouble() - sill) > TOL_POS:
        p_sill.Set(sill)
        changes.append("sill")

    if not pl.target.width_on_type and set_length(inst, BIPS_WIDTH, NAMES_WIDTH, pl.width):
        changes.append("width")
    if not pl.target.height_on_type and set_length(inst, BIPS_HEIGHT, NAMES_HEIGHT, pl.height):
        changes.append("height")

    p_phase = inst.get_Parameter(BuiltInParameter.PHASE_CREATED)
    if pl.phase and p_phase and not p_phase.IsReadOnly and p_phase.AsElementId() != pl.phase.Id:
        p_phase.Set(pl.phase.Id)
        changes.append("phase")

    doc.Regenerate()
    if inst.CanFlipFacing and inst.FacingOrientation.DotProduct(pl.facing) < 0:
        inst.flipFacing()
        doc.Regenerate()
        changes.append("facing")
    if inst.CanFlipHand and inst.HandOrientation.DotProduct(pl.hand) < 0:
        inst.flipHand()
        changes.append("hand")

    if status == "updated" and not changes:
        status = "unchanged"
    return inst, status, changes

def create_types():
    for pl in plans:
        pl.symbol = pl.target.symbol_for(pl.width, pl.height)

def delete_element(element):
    if element.IsValidObject:
        doc.Delete(element.Id)

results = {"created": [], "updated": [], "unchanged": []}
failed  = list(errors)
deleted = []

tg = TransactionGroup(doc, "Sync ARC doors and windows")
tg.Start()
try:
    # Types first, in their own transaction, so a failing element never rolls back a type.
    ok, _, err = run_transaction("Sync - create types", create_types)
    if not ok:
        tg.RollBack()
        forms.alert("Could not create the types:\n{}".format(err), exitscript=True)

    # Delete first (obsolete + overlapping), so new elements never land on top of old ones.
    for e, description, reason in to_delete.values():
        ok, _, err = run_transaction("Sync - delete", delete_element, e)
        if ok:
            deleted.append((description, reason))
        else:
            failed.append((None, "could not delete {}: {}".format(description, err)))

    # One transaction per element: an error in one element does not undo the others.
    with forms.ProgressBar(title="Syncing doors and windows... ({value} of {max_value})", cancellable=True) as pb:
        for i, pl in enumerate(plans):
            if pb.cancelled:
                break
            ok, res, err = run_transaction("Sync - element", sync_element, pl, existing.get(pl.src.UniqueId))
            if ok:
                inst, status, changes = res
                results[status].append((pl, inst, changes))
            else:
                failed.append((pl.src, err))
            pb.update_progress(i + 1, len(plans))

    tg.Assimilate()
except Exception:
    if tg.HasStarted():
        tg.RollBack()
    raise


# ╦═╗╔═╗╔═╗╔═╗╦═╗╔╦╗
# ╠╦╝║╣ ╠═╝║ ║╠╦╝ ║
# ╩╚═╚═╝╩  ╚═╝╩╚═ ╩
#==================================================
output.print_md("## ARC ► STR doors and windows")
output.print_md("**Link:** {}  |  **Dimensions:** {}".format(link_instance.Name, dims_mode))
replaced = [(e_desc, pl) for status in ("created", "updated") for pl, _, _ in results[status] for _, e_desc in pl.replaces]
output.print_table([[len(results["created"]), len(results["updated"]), len(results["unchanged"]),
                     len(replaced), len(deleted), len(failed)]],
                   columns=["Created", "Updated", "Unchanged", "Overlaps replaced", "Deleted", "Failed"])

for cat, target in targets.items():
    output.print_md("**{} family:** {}  (width on {}, height on {})".format(
        cat, target.family.Name,
        "type" if target.width_on_type else "instance",
        "type" if target.height_on_type else "instance"))
    if target.created:
        output.print_md("- Types created: " + ", ".join(sorted(target.created)))

rows = [[output.linkify(inst.Id), pl.cat, type_name(inst.Symbol), size_text(pl), status, ", ".join(changes)]
        for status in ("created", "updated") for pl, inst, changes in results[status]]
if rows:
    output.print_table(rows, columns=["Element", "Category", "Type", "W x H (mm)", "Status", "Changes"],
                       title="Created / updated")

if replaced:
    output.print_md("### Overlapping doors/windows replaced by the ARC one")
    for e_desc, pl in replaced:
        output.print_md("- {} → {}".format(e_desc, describe(pl.src)))

if deleted:
    output.print_md("### Deleted")
    for description, reason in deleted:
        output.print_md("- {} ({})".format(description, reason))

if arc_overlaps:
    output.print_md("### Overlapping doors/windows in the ARC model (only one copied)")
    for pl, rival in arc_overlaps:
        output.print_md("- Not copied: {}  ← overlaps {}".format(describe(pl.src), describe(rival.src)))

if no_wall:
    output.print_md("### ARC elements without a matching wall in this model")
    output.print_md("Not created (and deleted if they were synced before). Check that a parallel wall exists "
                    "at the same position and height.")
    for pl in no_wall:
        output.print_md("- {} {}".format(describe(pl.src), size_text(pl)))

if failed:
    output.print_md("### Failed")
    for src, reason in failed:
        output.print_md("- {} → {}".format(describe(src), reason))

if skipped:
    output.print_md("### Not synced from the link")
    for reason, n in sorted(skipped.items()):
        output.print_md("- {}: {}".format(reason, n))

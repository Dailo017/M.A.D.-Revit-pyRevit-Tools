# -*- coding: utf-8 -*-
__title__   = "Sync Doors\nWindows"
__doc__     = """Version = 1.0
Date    = 05.10.2026
________________________________________________________________
Description:

Synchronizes the doors and windows of a linked ARC model
into the active STR model:
1- Replaces each ARC family with the STR family chosen in a form.
2- Creates new types when no type with the required dimensions exists.
3- Places each element in the nearest wall of the active model.
4- Updates elements already synced and deletes the ones that
   no longer exist in the linked model.

Each created element stores in "Comments" the UniqueId of
its source ARC element.
________________________________________________________________
How-To:

1. Click the button and select the linked ARC model.
2. For each ARC family, pick the STR family to replace it with
   (cancel to skip that family).
3. Review the report in the output window.
________________________________________________________________
TODO:
[FEATURE] - Implement needs_recreate() to adapt existing
            elements instead of always recreating them.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, ElementId, Transaction, ElementTransformUtils, FamilyInstance, FamilySymbol, XYZ, ElementMulticategoryFilter
from Autodesk.Revit.DB.Structure import StructuralType
from pyrevit import forms, script

#.NET Imports
import clr
from Autodesk.Revit.DB import *
from rpw.ui.forms import SelectFromList
from System.Collections.Generic import List
clr.AddReference('System')

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

output = script.get_output()

TAG_PREFIX     = "ARC_SYNC:"   # prefix in Comments to recognize synced elements
TOL_POS        = 0.01          # feet (~3 mm)  position tolerance
TOL_DIM        = 0.003         # feet (~1 mm)  dimension tolerance
MAX_WALL_DIST  = 3.0           # feet (~0.9 m) max distance to the nearest wall

BIPS_WIDTH  = [BuiltInParameter.FAMILY_WIDTH_PARAM, BuiltInParameter.DOOR_WIDTH, BuiltInParameter.WINDOW_WIDTH]
BIPS_HEIGHT = [BuiltInParameter.FAMILY_HEIGHT_PARAM, BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.WINDOW_HEIGHT]

doors_cat_id = ElementId(BuiltInCategory.OST_Doors)


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Select the linked ARC model and collect its doors and windows.
links = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()

# Form to select the ARC model
links_dict  = {link.Name: link for link in links}
links_names = [link.Name for link in links]
value = SelectFromList('Select Linked Model', links_names)

selected_link = links_dict[value]

link_instance  = doc.GetElement(selected_link.Id)
linked_doc     = link_instance.GetLinkDocument()
transform_link = link_instance.GetTotalTransform()

categories      = [BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows]
categories_list = List[BuiltInCategory](categories)
cat_filter      = ElementMulticategoryFilter(categories_list)
linked_doors_windows = FilteredElementCollector(linked_doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElements()


# ╔═╗╦ ╦╔╗╔╔═╗  ╔═╗╦═╗╔═╗  ►  ╔═╗╔╦╗╦═╗
# ╚═╗╚╦╝║║║║    ╠═╣╠╦╝║       ╚═╗ ║ ╠╦╝
# ╚═╝ ╩ ╝╚╝╚═╝  ╩ ╩╩╚═╚═╝     ╚═╝ ╩ ╩╚═
#==================================================
# 2- Synchronize the doors and windows of the linked model into the active model:
#    - replaces each ARC family with the STR family chosen in a form
#    - creates new types if none exists with the required dimensions
#    - places each element in the nearest wall of the active model
#    - updates the ones already created and deletes the ones no longer in the linked model
# Each created element stores in "Comments" the UniqueId of the source ARC element.

# ── Utilities ─────────────────────────────────────
def type_name(symbol):
    return symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()

def find_parameter(element, bips, include_type=True):
    """First length parameter found on the element (and optionally on its type)."""
    candidates = [element]
    if include_type and isinstance(element, FamilyInstance):
        candidates.append(element.Symbol)
    for e in candidates:
        for bip in bips:
            p = e.get_Parameter(bip)
            if p and p.HasValue and p.StorageType == StorageType.Double:
                return p
    return None

def read_dimensions(element):
    p_w = find_parameter(element, BIPS_WIDTH)
    p_h = find_parameter(element, BIPS_HEIGHT)
    return (p_w.AsDouble() if p_w else None, p_h.AsDouble() if p_h else None)

def apply_dimensions(element, width, height):
    """Writes width/height only on the element's own parameters (type or instance)."""
    for bips, val in ((BIPS_WIDTH, width), (BIPS_HEIGHT, height)):
        p = find_parameter(element, bips, include_type=False)
        if val is not None and p and not p.IsReadOnly and abs(p.AsDouble() - val) > TOL_DIM:
            p.Set(val)

def dims_equal(a, b):
    return a is None or b is None or abs(a - b) < TOL_DIM

def get_type(family, width, height):
    """Returns a type of the family with those dimensions; if none exists, creates it by duplicating."""
    symbols = [doc.GetElement(i) for i in family.GetFamilySymbolIds()]
    for s in symbols:
        w, h = read_dimensions(s)
        if dims_equal(w, width) and dims_equal(h, height):
            return s
    name = "{} x {} mm".format(int(round(width * 304.8)), int(round(height * 304.8)))
    existing_names = [type_name(s) for s in symbols]
    while name in existing_names:
        name += "_"
    new_type = symbols[0].Duplicate(name)
    apply_dimensions(new_type, width, height)
    output.print_md("- Type created: **{} : {}**".format(family.Name, name))
    return new_type

def bottom_elevation(source):
    """Elevation (internal coordinates of OUR model) of the bottom of the ARC opening."""
    arc_level = linked_doc.GetElement(source.LevelId)
    z_level   = transform_link.OfPoint(XYZ(0, 0, arc_level.ProjectElevation)).Z
    p_sill    = source.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    return z_level + (p_sill.AsDouble() if p_sill else 0.0)


# ── Levels and walls of our model ─────────────────
levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.ProjectElevation)

def level_for(z):
    below = [l for l in levels if l.ProjectElevation <= z + TOL_POS]
    return below[-1] if below else levels[0]

walls = [w for w in FilteredElementCollector(doc).OfClass(Wall).ToElements()
         if isinstance(w.Location, LocationCurve) and w.WallType.Kind != WallKind.Curtain]

def nearest_wall(point, z_test):
    """Wall whose location line is closest (in plan) to the point and that covers elevation z_test."""
    best, best_pt, best_dist = None, None, MAX_WALL_DIST
    for w in walls:
        bb = w.get_BoundingBox(None)
        if bb is None or not (bb.Min.Z - TOL_POS <= z_test <= bb.Max.Z + TOL_POS):
            continue
        curve = w.Location.Curve
        res = curve.Project(XYZ(point.X, point.Y, curve.GetEndPoint(0).Z))
        if res and res.Distance < best_dist:
            best, best_pt, best_dist = w, res.XYZPoint, res.Distance
    return best, best_pt


# ── Form: ARC family -> STR family ────────────────
def families_of_category(bic):
    symbols = FilteredElementCollector(doc).OfCategory(bic).OfClass(FamilySymbol).ToElements()
    return {s.Family.Name: s.Family for s in symbols}

str_families = {"Doors": families_of_category(BuiltInCategory.OST_Doors),
                "Windows": families_of_category(BuiltInCategory.OST_Windows)}

sources = [e for e in linked_doors_windows
           if isinstance(e, FamilyInstance) and isinstance(e.Host, Wall) and e.Host.WallType.Kind != WallKind.Curtain]

def category_key(element):
    return "Doors" if element.Category.Id == doors_cat_id else "Windows"

mapping = {}   # (category, ARC family) -> STR Family  (None = skip)
for e in sources:
    cat = category_key(e)
    key = (cat, e.Symbol.Family.Name)
    if key in mapping:
        continue
    options = sorted(str_families[cat].keys())
    if not options:
        forms.alert("There are no {} families loaded in this model.".format(cat.lower()), exitscript=True)
    chosen = forms.SelectFromList.show(options,
                                       title="ARC {}: '{}' -> choose STR family".format(cat, key[1]),
                                       button_name="Assign", multiselect=False)
    mapping[key] = str_families[cat].get(chosen) if chosen else None


# ── Comparison / update decision ──────────────────
def needs_recreate(existing, wall, level):
    """True if the existing element cannot be adapted and must be deleted and created again."""
    # TODO(human)
    return True


# ── Synchronization ───────────────────────────────
existing_elements = {}
for e in FilteredElementCollector(doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElements():
    p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    txt = p.AsString() if p else None
    if txt and txt.startswith(TAG_PREFIX):
        existing_elements[txt[len(TAG_PREFIX):]] = e

def adjust_instance(inst, source, symbol, level, bottom_z, width, height):
    inst.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(TAG_PREFIX + source.UniqueId)
    p_sill = inst.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    if p_sill and not p_sill.IsReadOnly:
        p_sill.Set(bottom_z - level.ProjectElevation)
    apply_dimensions(inst, width, height)            # in case width/height are instance parameters
    doc.Regenerate()
    facing = transform_link.OfVector(source.FacingOrientation)
    if inst.CanFlipFacing and inst.FacingOrientation.DotProduct(facing) < 0:
        inst.flipFacing()
        doc.Regenerate()
    hand = transform_link.OfVector(source.HandOrientation)
    if inst.CanFlipHand and inst.HandOrientation.DotProduct(hand) < 0:
        inst.flipHand()

created, updated, deleted, failed = 0, 0, 0, []
current_uids = set()

t = Transaction(doc, "Sync ARC doors and windows")
t.Start()
try:
    for source in sources:
        current_uids.add(source.UniqueId)    # skipped ones too, so they are not deleted
        family = mapping.get((category_key(source), source.Symbol.Family.Name))
        if family is None:
            continue
        try:
            point    = transform_link.OfPoint(source.Location.Point)
            bottom_z = bottom_elevation(source)
            level    = level_for(bottom_z)
            wall, wall_point = nearest_wall(point, bottom_z + 0.3)
            if wall is None:
                failed.append((source, "no nearby wall"))
                continue

            width, height = read_dimensions(source)
            symbol = get_type(family, width, height) if width and height else doc.GetElement(list(family.GetFamilySymbolIds())[0])
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()

            existing = existing_elements.get(source.UniqueId)
            if existing and needs_recreate(existing, wall, level):
                doc.Delete(existing.Id)
                existing = None

            target = XYZ(wall_point.X, wall_point.Y, level.ProjectElevation)
            if existing is None:
                inst = doc.Create.NewFamilyInstance(target, symbol, wall, level, StructuralType.NonStructural)
                created += 1
            else:
                inst = existing
                if inst.Symbol.Id != symbol.Id:
                    inst.ChangeTypeId(symbol.Id)
                current = inst.Location.Point
                delta   = XYZ(target.X - current.X, target.Y - current.Y, 0)
                if delta.GetLength() > TOL_POS:
                    ElementTransformUtils.MoveElement(doc, inst.Id, delta)
                updated += 1

            adjust_instance(inst, source, symbol, level, bottom_z, width, height)
        except Exception as ex:
            failed.append((source, str(ex)))

    # Delete the ones that no longer exist in the linked model
    for uid, e in existing_elements.items():
        if uid not in current_uids and e.IsValidObject:
            doc.Delete(e.Id)
            deleted += 1

    t.Commit()
except Exception:
    t.RollBack()
    raise


# ── Report ────────────────────────────────────────
output.print_md("## ARC ► STR Synchronization")
output.print_md("- Created: **{}**\n- Updated: **{}**\n- Deleted: **{}**\n- Failed: **{}**".format(
    created, updated, deleted, len(failed)))
for source, reason in failed:
    output.print_md("  - {} ({}) → {}".format(source.Symbol.Family.Name, source.Id, reason))

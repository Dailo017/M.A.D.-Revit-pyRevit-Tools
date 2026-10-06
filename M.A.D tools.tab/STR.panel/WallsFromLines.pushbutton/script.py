# -*- coding: utf-8 -*-
__title__   = "Walls From\nLines"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Creates walls from pairs of parallel model lines in the active
view (e.g. the two faces of a wall drawn in a CAD plan):
1- Finds pairs of parallel lines closer than MAX_OFFSET (~45 cm).
2- Draws a center line between them with the chosen line style.
3- Creates a wall of the chosen type on each center line
   (height ~3 m, level of the active view).
________________________________________________________________
How-To:

1. Open a floor plan with the model lines.
2. Click the button, choose the wall type and the line style.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Cleanup + level checked before creating anything
- [23.04.2026] v1.0 First release
________________________________________________________________
Author: Aaron Rumple"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from collections import namedtuple

from pyrevit.framework import List
from pyrevit import revit, DB, forms, script
from pyrevit.compat import get_elementid_value_func

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
doc         = revit.doc
uidoc       = revit.uidoc
active_view = doc.ActiveView

MAX_OFFSET = 1.5          # feet (~45 cm) max distance between the two lines
WALL_HEIGHT = 10.0        # feet (~3 m)
ANG_TOL  = 1e-6
DIST_TOL = 1e-6
LEN_TOL  = 1e-6

POINT_RESOLUTION     = '{:.4f}'
DIRECTION_RESOLUTION = '{:.2f}'
OFFSET_RESOLUTION    = '{:.4f}'


# ── Utilities ─────────────────────────────────────
def is_line_curve(curve):
    return isinstance(curve, DB.Line)


def normalize(v):
    if v is None or v.GetLength() < 1e-12:
        return None
    return v.Normalize()


def are_parallel(v1, v2, tol=ANG_TOL):
    if v1 is None or v2 is None:
        return False
    return v1.CrossProduct(v2).GetLength() <= tol


def get_active_view_sketch_plane(document, view):
    sp = view.SketchPlane
    if sp:
        return sp
    plane = DB.Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin)
    t = DB.Transaction(document, "Create Active View Sketch Plane")
    t.Start()
    sp = DB.SketchPlane.Create(document, plane)
    view.SketchPlane = sp
    t.Commit()
    return sp


# ── Line styles ───────────────────────────────────
class LineStyleOption(forms.TemplateListItem):
    @property
    def name(self):
        cat = self.item.GraphicsStyleCategory
        return cat.Name if cat else "<No Category>"


def get_model_line_styles(document):
    styles = []
    lines_cat = document.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    for subcat in lines_cat.SubCategories:
        try:
            gs = subcat.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
            if gs:
                styles.append(gs)
        except:
            pass
    return sorted(styles, key=lambda x: x.GraphicsStyleCategory.Name)


# ── Collection ────────────────────────────────────
def collect_model_lines_in_active_view(document, view):
    model_lines = []
    for ce in DB.FilteredElementCollector(document, view.Id).OfClass(DB.CurveElement):
        if isinstance(ce, DB.ModelCurve):
            curve = ce.GeometryCurve
            if curve and is_line_curve(curve) and curve.Length > LEN_TOL:
                model_lines.append(ce)
    return model_lines


def line_data(model_curve):
    curve = model_curve.GeometryCurve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    return {
        "curve":  curve,
        "p0":     p0,
        "p1":     p1,
        "mid":    (p0 + p1) * 0.5,
        "dir":    normalize(p1 - p0),
        "length": curve.Length,
    }


# ── Center geometry ───────────────────────────────
def project_point_to_segment(seg_curve, test_point, tol=1e-6):
    r = seg_curve.Project(test_point)
    if r is None:
        return (False, None, None)
    proj = r.XYZPoint
    p0 = seg_curve.GetEndPoint(0)
    p1 = seg_curve.GetEndPoint(1)
    on_seg = abs((proj.DistanceTo(p0) + proj.DistanceTo(p1)) - p0.DistanceTo(p1)) <= tol
    return (on_seg, proj, test_point.DistanceTo(proj))


def build_center_line_from_pair(data_a, data_b, max_offset):
    if not are_parallel(data_a["dir"], data_b["dir"]):
        return None

    short_data = data_a if data_a["length"] <= data_b["length"] else data_b
    other_data = data_b if short_data is data_a else data_a

    ok, proj_mid, dist = project_point_to_segment(other_data["curve"], short_data["mid"])
    if not ok or dist is None or dist <= DIST_TOL or dist > max_offset:
        return None

    move_vec = proj_mid - short_data["mid"]
    if abs(move_vec.DotProduct(short_data["dir"])) > 1e-5:
        return None

    half_vec = move_vec * 0.5
    c0 = short_data["p0"] + half_vec
    c1 = short_data["p1"] + half_vec
    if c0.DistanceTo(c1) <= LEN_TOL:
        return None
    return DB.Line.CreateBound(c0, c1)


# ── Overkill (merge overlapping center lines) ─────
CurvePoint = namedtuple('CurvePoint', ['x', 'y', 'cid'])


class LinearCurveGroup(object):

    def __init__(self, curve, include_style=False):
        self.points = set()
        p1 = curve.GeometryCurve.GetEndPoint(0)
        p2 = curve.GeometryCurve.GetEndPoint(1)

        self.dir_x, self.dir_y = self.get_direction(curve)
        self.dir_offset = self.get_offset(p1, p2)
        self.weight = self.get_weight(curve) if include_style else None
        self.cgroup_id = (self.dir_x, self.dir_y, self.dir_offset, self.weight)

        self.dir_cid = get_elementid_value_func()(curve.Id)
        self.add_points([self.get_point(p1.X, p1.Y), self.get_point(p2.X, p2.Y)])

    def get_direction(self, curve):
        v = curve.GeometryCurve.GetEndPoint(1) - curve.GeometryCurve.GetEndPoint(0)
        if v.GetLength() < 1e-9:
            return (0, 0)
        v = v.Normalize()
        return (float(DIRECTION_RESOLUTION.format(v.X)), float(DIRECTION_RESOLUTION.format(v.Y)))

    def get_offset(self, p1, p2):
        A = p2.Y - p1.Y
        B = p1.X - p2.X
        C = -(A * p1.X + B * p1.Y)
        return float(OFFSET_RESOLUTION.format(C))

    def get_weight(self, curve):
        try:
            return get_elementid_value_func()(curve.LineStyle.Id)
        except:
            return 0

    def get_point(self, x, y):
        return CurvePoint(x=float(POINT_RESOLUTION.format(x)),
                          y=float(POINT_RESOLUTION.format(y)),
                          cid=self.dir_cid)

    def add_points(self, curve_points):
        for curve_point in curve_points:
            self.points.add(curve_point)

    def overkill(self, document=None):
        if document and len(self.points) > 2:
            root_curve = document.GetElement(DB.ElementId(self.dir_cid))
            min_p = min(self.points, key=lambda p: p.x + p.y)
            max_p = max(self.points, key=lambda p: p.x + p.y)
            z = root_curve.GeometryCurve.GetEndPoint(0).Z
            try:
                root_curve.SetGeometryCurve(DB.Line.CreateBound(DB.XYZ(min_p.x, min_p.y, z),
                                                                DB.XYZ(max_p.x, max_p.y, z)), True)
                to_delete = [DB.ElementId(x.cid) for x in self.points if x.cid != self.dir_cid]
                if to_delete:
                    document.Delete(List[DB.ElementId](to_delete))
                return len(to_delete)
            except:
                pass
        return 0


class CurveGroupCollection(object):
    def __init__(self):
        self.curve_groups = []

    def extend(self, curve_element):
        if isinstance(curve_element.GeometryCurve, DB.Line):
            self.curve_groups.append(LinearCurveGroup(curve_element))


def overkill_created_curves(curve_elements):
    collection = CurveGroupCollection()
    for c in curve_elements:
        collection.extend(c)
    deleted = 0
    for g in collection.curve_groups:
        deleted += g.overkill(document=doc)
    return deleted


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- The active view must have a level (floor plan).
level = active_view.GenLevel
if not level:
    forms.alert("Active view has no level (use a floor plan).", exitscript=True)

# 2- Form: wall type
wall_type_dict = {}
for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType).ToElements():
    p = wt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    wall_type_dict[p.AsString() if p else "Unnamed"] = wt

selected_name = forms.SelectFromList.show(sorted(wall_type_dict.keys()),
                                          title="Select Wall Type", multiselect=False)
if not selected_name:
    forms.alert("No wall type selected.", exitscript=True)
wall_type = wall_type_dict[selected_name]

# 3- Form: line style of the center lines
selected_style = forms.SelectFromList.show([LineStyleOption(x) for x in get_model_line_styles(doc)],
                                           title="Select Model Line Style", multiselect=False)
if not selected_style:
    forms.alert("No style selected.", exitscript=True)

# 4- Center lines between pairs of parallel lines
sketch_plane = get_active_view_sketch_plane(doc, active_view)
data = [line_data(x) for x in collect_model_lines_in_active_view(doc, active_view)]

candidate_lines = []
for i in range(len(data)):
    for j in range(i + 1, len(data)):
        center_line = build_center_line_from_pair(data[i], data[j], MAX_OFFSET)
        if center_line:
            candidate_lines.append(center_line)

if not candidate_lines:
    forms.alert("No pairs of parallel lines were found in the active view.", exitscript=True)

# 5- Create center lines + walls
created_ids = []
with revit.Transaction("Create Center Lines + Walls"):
    for line in candidate_lines:
        new_mc = doc.Create.NewModelCurve(line, sketch_plane)
        new_mc.LineStyle = selected_style
        created_ids.append(new_mc.Id)
        try:
            DB.Wall.Create(doc, line, wall_type.Id, level.Id, WALL_HEIGHT, 0.0, False, False)
        except Exception as e:
            print("Error creating wall: {}".format(e))

with revit.Transaction("Overkill"):
    overkill_created_curves([doc.GetElement(x) for x in created_ids])

forms.alert("Finished: {} center lines / walls.".format(len(candidate_lines)))

# -*- coding: utf-8 -*-
__title__   = "Clear Height\nMEP"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Calculates the free space between pipes, ducts and cable trays
and the floor below them (floors of a linked model), and writes
it in the parameter chosen in the form.

A ray is cast downwards from 3 points of each element (start,
middle, end); the shortest distance to a floor is stored.
________________________________________________________________
How-To:

1. Open a 3D view (not a template) where the link is visible.
2. Click the button and type the parameter name where the
   clear height will be stored. It must be a LENGTH, INSTANCE
   project parameter assigned to Pipes, Ducts and Cable Trays;
   otherwise you'll be warned.
3. Select the linked model with the floors.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Parameter chosen in a form + project parameter check
- [03.03.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from pyrevit import forms

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

CATEGORIES = {BuiltInCategory.OST_PipeCurves: "Pipes",
              BuiltInCategory.OST_DuctCurves: "Ducts",
              BuiltInCategory.OST_CableTray:  "Cable Trays"}
floors_cat_id = ElementId(BuiltInCategory.OST_Floors)

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- The ray casting needs a 3D view.
view3d = doc.ActiveView
if not isinstance(view3d, View3D) or view3d.IsTemplate:
    forms.alert("Open a 3D view (where the linked floors are visible) and try again.", exitscript=True)

# 2- Form to type the parameter where the clear height is stored.
param_name = forms.ask_for_string(default="ClearHeight",
                                  prompt="Parameter name where the clear height will be stored:",
                                  title="Clear Height MEP")
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 3- Check it exists as an INSTANCE project parameter assigned to the MEP categories.
binding  = None
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter, data type LENGTH, '
                'for Pipes, Ducts and Cable Trays.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)
missing = [name for bic, name in CATEGORIES.items() if not binding.Categories.Contains(Category.GetCategory(doc, bic))]
if missing:
    forms.alert('The project parameter "{}" is not assigned to: {}.'.format(param_name, ", ".join(missing)), exitscript=True)

# 4- Collect the MEP elements and check the parameter data type.
elements = []
for bic in CATEGORIES:
    elements.extend(FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements())
if not elements:
    forms.alert("There are no pipes, ducts or cable trays in the project.", exitscript=True)

first_param = elements[0].LookupParameter(param_name)
if not first_param or first_param.StorageType != StorageType.Double:
    forms.alert('The project parameter "{}" must be of data type LENGTH.'.format(param_name), exitscript=True)

# 5- Select the linked model with the floors
all_rvt_links  = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()
dict_rvt_links = {lnk.GetLinkDocument().Title: lnk for lnk in all_rvt_links if lnk.GetLinkDocument()}
if not dict_rvt_links:
    forms.alert("There are no loaded linked models in this project.", exitscript=True)

link_names = sorted(dict_rvt_links.keys())
selected_lnk_name = forms.ask_for_one_item(link_names, default=link_names[0],
                                           prompt="Select Link", title="Link Selection")
if not selected_lnk_name:
    forms.alert("No link selected.", exitscript=True)
selected_lnk = dict_rvt_links[selected_lnk_name]
linked_doc   = selected_lnk.GetLinkDocument()

ref_intersector = ReferenceIntersector(ElementCategoryFilter(BuiltInCategory.OST_Floors),
                                       FindReferenceTarget.Element, view3d)
ref_intersector.FindReferencesInRevitLinks = True

# 6- Cast the rays and write the minimum distance
t = Transaction(doc, "Clear Height MEP")
t.Start()
try:
    for elem in elements:
        loc = elem.Location
        if not isinstance(loc, LocationCurve):
            continue
        curve  = loc.Curve
        points = [curve.GetEndPoint(0), curve.Evaluate(0.5, True), curve.GetEndPoint(1)]

        distances = []
        for p in points:
            hit = ref_intersector.FindNearest(p, XYZ(0, 0, -1))
            if not hit:
                continue
            ref = hit.GetReference()
            floor = None
            if ref.LinkedElementId != ElementId.InvalidElementId:
                if ref.ElementId == selected_lnk.Id:          # only the selected link
                    floor = linked_doc.GetElement(ref.LinkedElementId)
            elif ref.ElementId != ElementId.InvalidElementId:
                floor = doc.GetElement(ref.ElementId)
            if floor and floor.Category and floor.Category.Id == floors_cat_id:
                distances.append(hit.Proximity)

        if distances:
            param = elem.LookupParameter(param_name)
            if param and not param.IsReadOnly:
                param.Set(min(distances))

    t.Commit()
except Exception:
    t.RollBack()
    raise

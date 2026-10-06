# -*- coding: utf-8 -*-
__title__   = "Reference\nLevel"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Changes the reference level of the selected MEP elements
WITHOUT moving them: the offset is recalculated so the
elements keep their current elevation.
________________________________________________________________
How-To:

1. Click the button and select the elements.
2. Choose the new reference level.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Cleanup + cancel handling
- [11.02.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import forms

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

# Level parameters (first writable one found is used)
BIPS_LEVEL = [BuiltInParameter.FAMILY_LEVEL_PARAM, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
              BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM, BuiltInParameter.RBS_START_LEVEL_PARAM,
              BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM]
# Offset parameters
BIPS_OFFSET = [BuiltInParameter.INSTANCE_ELEVATION_PARAM, BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
               BuiltInParameter.RBS_OFFSET_PARAM]

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Select the elements
try:
    refs = uidoc.Selection.PickObjects(ObjectType.Element)
except:
    forms.alert("No elements were selected.", exitscript=True)
elems = [doc.GetElement(r) for r in refs]

# 2- Select the level
levels = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements()
levels_dict = {lv.Name: lv for lv in levels}

res = forms.SelectFromList.show(sorted(levels_dict.keys()), button_name='Select Level')
if not res:
    forms.alert("No level selected.", exitscript=True)

new_level_id = levels_dict[res].Id
new_level_z  = levels_dict[res].ProjectElevation   # feet

# 3- Change level and recalculate the offset to keep Z
t = Transaction(doc, "Reference Level")
t.Start()
try:
    for el in elems:
        loc = el.Location
        if isinstance(loc, LocationPoint):
            z_current = loc.Point.Z
        elif isinstance(loc, LocationCurve):
            z_current = loc.Curve.GetEndPoint(0).Z
        else:
            continue

        level_param = None
        for bip in BIPS_LEVEL:
            p = el.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(new_level_id)
                level_param = p
                break
        if not level_param:
            continue

        for bip in BIPS_OFFSET:
            p = el.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(z_current - new_level_z)
                break

    t.Commit()
except Exception:
    t.RollBack()
    raise

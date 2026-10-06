# -*- coding: utf-8 -*-
__title__   = "Room Tags\nFrom Link"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Places a room tag on every room of a linked model, in every
floor plan view of the project.
________________________________________________________________
How-To:

1. Click the button and select the linked model.
2. Tags that cannot be placed are counted in the final report.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 One single transaction + templates and
                    unplaced rooms are skipped
- [18.05.2026] v1.0 First release
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

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Select the linked model
links = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()
dict_rvt_links = {lnk.GetLinkDocument().Title: lnk for lnk in links if lnk.GetLinkDocument()}
if not dict_rvt_links:
    forms.alert("There are no loaded linked models in this project.", exitscript=True)

link_names = sorted(dict_rvt_links.keys())
selected_lnk_name = forms.ask_for_one_item(link_names, default=link_names[0],
                                           prompt="Select Link", title="Link Selection")
if not selected_lnk_name:
    forms.alert("No link selected.", exitscript=True)

selected_lnk = dict_rvt_links[selected_lnk_name]
linked_doc   = selected_lnk.GetLinkDocument()
transform    = selected_lnk.GetTotalTransform()

# 2- Floor plan views (no templates) and placed rooms of the link
views = [v for v in FilteredElementCollector(doc).OfClass(ViewPlan).WhereElementIsNotElementType() if not v.IsTemplate]
rooms = [r for r in FilteredElementCollector(linked_doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()
         if r.Location is not None]
if not rooms:
    forms.alert('There are no placed rooms in "{}".'.format(selected_lnk_name), exitscript=True)

# 3- Place the tags (one single transaction)
created, failed = 0, 0
t = Transaction(doc, "Place Room Tags")
t.Start()
try:
    for view in views:
        for room in rooms:
            point = transform.OfPoint(room.Location.Point)    # link -> host coordinates
            try:
                tag = doc.Create.NewRoomTag(LinkElementId(selected_lnk.Id, room.Id), UV(point.X, point.Y), view.Id)
                if tag is None:
                    failed += 1
                else:
                    created += 1
            except Exception:
                failed += 1
    t.Commit()
except Exception:
    t.RollBack()
    raise

forms.alert("Room tags created: {}\nNot placed: {}".format(created, failed))

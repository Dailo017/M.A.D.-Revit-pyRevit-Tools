# -*- coding: utf-8 -*-
__title__   = "Attach\nWalls"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Allows the join at both ends of the selected walls.
________________________________________________________________
How-To:

1. Click the button and select the walls.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Cleanup + only walls are processed
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

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Select the walls.
try:
    refs = uidoc.Selection.PickObjects(ObjectType.Element)
except:
    forms.alert("No elements were selected.", exitscript=True)
pick_walls = [w for w in (doc.GetElement(r) for r in refs) if isinstance(w, Wall)]
if not pick_walls:
    forms.alert("The selection contains no walls.", exitscript=True)

# 2- Allow the join at the start (0) and end (1) of each wall.
t = Transaction(doc, "Allow Wall Join")
t.Start()
try:
    for wall in pick_walls:
        WallUtils.AllowWallJoinAtEnd(wall, 0)
        WallUtils.AllowWallJoinAtEnd(wall, 1)
    t.Commit()
except Exception:
    t.RollBack()
    raise

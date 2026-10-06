# -*- coding: utf-8 -*-
__title__   = "Select\nThick Walls"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Selects in Revit all the walls of the project thicker than
35 cm (MIN_WIDTH_CM).
________________________________________________________________
How-To:

1. Click the button: the walls are selected in the model.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Cleanup + warning when no wall is found
- [14.11.2025] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from pyrevit import forms

#.NET Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

MIN_WIDTH_CM = 35

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
min_width_ft = UnitUtils.ConvertToInternalUnits(MIN_WIDTH_CM, UnitTypeId.Centimeters)
walls = FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType().ToElements()
thick_walls = [w for w in walls if w.Width > min_width_ft]

if not thick_walls:
    forms.alert("There are no walls thicker than {} cm.".format(MIN_WIDTH_CM), exitscript=True)

uidoc.Selection.SetElementIds(List[ElementId]([w.Id for w in thick_walls]))

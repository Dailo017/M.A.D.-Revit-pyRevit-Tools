# -*- coding: utf-8 -*-
__title__   = "UPPER /\nLowercase"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Changes the names of the families and/or types of the project
to UPPERCASE or lowercase.
________________________________________________________________
How-To:

1. Click the button and choose: Families, Types, or both.
2. Choose UPPERCASE or lowercase.
3. Names that cannot be changed are listed in the output window.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 A failing name no longer stops the rest
- [27.02.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import *
from Autodesk.Revit.DB.Structure import *
from Autodesk.Revit.DB.Architecture import *
from Autodesk.Revit.DB.Plumbing import *
from Autodesk.Revit.DB.Electrical import *
from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

output = script.get_output()

# Editable type classes (system + loadable)
TYPE_CLASSES = [
    # ===== Architecture / Structure =====
    WallType, FloorType, RoofType, CeilingType,
    StairsType, StairsRunType, StairsLandingType,
    RailingType, TopRailType, HandRailType,
    PanelType, MullionType, FilledRegionType,
    RebarBarType, RebarHookType, RebarShape,
    FamilySymbol,                       # loadable families in general
    # ===== MEP =====
    DuctType, FlexDuctType, PipeType, FlexPipeType,
    ConduitType, CableTrayType, WireType,
]

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Options (asked before opening the transaction).
option = forms.alert("Choose an option?", options=["Families", "Types", "Families and Types"])
if not option:
    forms.alert("No Option Selected.", exitscript=True)

case = forms.alert("UPPER or lower?", options=["UPPERCASE", "lowercase"])
if not case:
    forms.alert("No Option Selected.", exitscript=True)

# 2- Rename. Each name is renamed on its own: one failure does not stop the rest.
failed = []
t = Transaction(doc, "UPPERCASE / lowercase")
t.Start()
try:
    if option in ("Families", "Families and Types"):
        for family in FilteredElementCollector(doc).OfClass(Family).WhereElementIsNotElementType().ToElements():
            name = family.Name
            try:
                family.Name = name.upper() if case == "UPPERCASE" else name.lower()
            except Exception as ex:
                failed.append((name, str(ex)))

    if option in ("Types", "Families and Types"):
        for cls in TYPE_CLASSES:
            for type_elem in FilteredElementCollector(doc).OfClass(cls).ToElements():
                name = Element.Name.GetValue(type_elem)
                try:
                    Element.Name.SetValue(type_elem, name.upper() if case == "UPPERCASE" else name.lower())
                except Exception as ex:
                    failed.append((name, str(ex)))

    t.Commit()
except Exception:
    t.RollBack()
    raise

# 3- Report
if failed:
    output.print_md("## Names not changed: **{}**".format(len(failed)))
    for name, reason in failed:
        output.print_md("- {} → {}".format(name, reason))

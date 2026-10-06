# -*- coding: utf-8 -*-
__title__   = "Split\nWalls"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Splits each selected wall into one wall per layer of its
compound structure:
1- Creates (or reuses) a wall type per layer, named
   "<Material> (<width>cm)".
2- Duplicates the original wall for each layer and offsets it
   to the layer position.
3- Deletes the original wall and joins the new walls.
________________________________________________________________
How-To:

1. Click the button and select the walls to split.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Cleanup + selection before transaction
- [11.02.2026] v1.0 First release
________________________________________________________________
Author: Mohamed Mostafa Bedair, Joven Mark Gumana, Erik Frits"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
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

class seleccion_wall(ISelectionFilter):
    def AllowElement(self, elem):
        return type(elem) == Wall

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Select the walls (before opening the transaction).
try:
    ref_wall = uidoc.Selection.PickObjects(ObjectType.Element, seleccion_wall())
    sel_wall = [doc.GetElement(r) for r in ref_wall]
except:
    forms.alert("You have to select a wall to continue.", exitscript=True)

# 2- Split each wall into its layers.
t = Transaction(doc, "Split Wall Layers")
t.Start()
try:
    for wall in sel_wall:
        wall_type = doc.GetElement(wall.GetTypeId())
        structure = wall_type.GetCompoundStructure()
        if structure is None:          # curtain / stacked walls have no layers
            continue

        current_offset = 0
        new_walls = []
        for layer in structure.GetLayers():
            layer_width    = layer.Width     # feet
            layer_width_cm = UnitUtils.ConvertFromInternalUnits(layer_width, UnitTypeId.Centimeters)
            layer_mat      = doc.GetElement(layer.MaterialId)
            layer_name     = layer_mat.Name if layer_mat else "Generic"

            # Get existing wall type or create it
            new_wall_type_name = "{} ({}cm)".format(layer_name, layer_width_cm)
            all_wall_types  = FilteredElementCollector(doc).OfClass(WallType).ToElements()
            dict_wall_types = {Element.Name.GetValue(wt): wt for wt in all_wall_types}
            if new_wall_type_name in dict_wall_types:
                new_wall_type = dict_wall_types[new_wall_type_name]
            else:
                new_wall_type = wall_type.Duplicate(new_wall_type_name)
                new_wall_type.SetCompoundStructure(CompoundStructure.CreateSimpleCompoundStructure([layer]))

            # Offset of the layer from the wall axis
            offset = (wall_type.Width - layer_width - current_offset * 2) / 2
            if not wall.Flipped:
                offset = -offset
            new_curve = wall.Location.Curve.CreateOffset(offset, XYZ.BasisZ)

            # Duplicate the existing wall (keeps its parameters)
            new_ids  = ElementTransformUtils.CopyElements(doc, List[ElementId]([wall.Id]), XYZ(0, 0, 0))
            new_wall = doc.GetElement(new_ids[0])
            new_wall.WallType      = new_wall_type
            new_wall.Location.Curve = new_curve

            current_offset += layer.Width
            new_walls.append(new_wall)

        # Delete the original wall and join the new ones
        doc.Delete(wall.Id)
        for wall_a in new_walls:
            for wall_b in new_walls:
                try:
                    JoinGeometryUtils.JoinGeometry(doc, wall_a, wall_b)
                except:
                    pass

    t.Commit()
except Exception:
    t.RollBack()
    raise

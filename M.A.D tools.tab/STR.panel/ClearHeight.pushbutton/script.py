# -*- coding: utf-8 -*-
__title__   = "Clear\nHeight"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Calculates the free space between each beam and the floor
below it, and writes the result in the parameter chosen in
the form.

- Only floors below the bottom of the beam are considered.
- The floor must overlap the beam in plan at least 0.75 m
  along the beam direction (X or Y).
- If several floors are valid, the highest one is used.
________________________________________________________________
How-To:

1. Click the button and type the parameter name where the
   clear height will be stored.
2. The parameter must be a LENGTH, INSTANCE project parameter
   assigned to the Structural Framing category; otherwise
   you'll be warned.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Parameter chosen in a form + project parameter check
- [11.02.2026] v1.0 First release
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

MIN_OVERLAP = UnitUtils.ConvertToInternalUnits(0.75, UnitTypeId.Meters)   # min longitudinal overlap beam/floor

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Form to type the parameter where the clear height is stored.
param_name = forms.ask_for_string(default="altura_libre",
                                  prompt="Parameter name where the clear height will be stored:",
                                  title="Clear Height")
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 2- Check it exists as a project parameter (instance) assigned to Structural Framing.
framing_cat = Category.GetCategory(doc, BuiltInCategory.OST_StructuralFraming)
binding     = None
iterator    = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter, data type LENGTH, '
                'for the Structural Framing category.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)
if not binding.Categories.Contains(framing_cat):
    forms.alert('The project parameter "{}" is not assigned to the Structural Framing category.'.format(param_name), exitscript=True)

# 3- Collect beams and floors and check the parameter data type.
floors = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType().ToElements()
beams  = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType().ToElements()
if not beams:
    forms.alert("There are no beams in the project.", exitscript=True)

first_param = beams[0].LookupParameter(param_name)
if not first_param or first_param.StorageType != StorageType.Double:
    forms.alert('The project parameter "{}" must be of data type LENGTH.'.format(param_name), exitscript=True)

# 4- Write the clear height of each beam.
t = Transaction(doc, "Clear Height")
t.Start()
try:
    for beam in beams:
        loc = beam.Location
        if not isinstance(loc, LocationCurve):
            continue

        # Dominant axis of the beam (X or Y)
        direction = loc.Curve.Direction
        axis_x    = abs(direction.X) >= abs(direction.Y)

        p_beam = beam.get_Parameter(BuiltInParameter.STRUCTURAL_ELEVATION_AT_BOTTOM)
        if not p_beam:
            continue
        beam_z = p_beam.AsDouble()

        bb_beam = beam.get_BoundingBox(None)
        if not bb_beam:
            continue

        best_z = None
        for floor in floors:
            p_floor = floor.get_Parameter(BuiltInParameter.STRUCTURAL_ELEVATION_AT_TOP)
            if not p_floor:
                continue
            floor_z = p_floor.AsDouble()
            if floor_z >= beam_z:
                continue

            bb_floor = floor.get_BoundingBox(None)
            if not bb_floor:
                continue

            # XY intersection, measured only along the beam direction
            overlap_x = min(bb_beam.Max.X, bb_floor.Max.X) - max(bb_beam.Min.X, bb_floor.Min.X)
            overlap_y = min(bb_beam.Max.Y, bb_floor.Max.Y) - max(bb_beam.Min.Y, bb_floor.Min.Y)
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            overlap = overlap_x if axis_x else overlap_y

            if overlap >= MIN_OVERLAP and (best_z is None or floor_z > best_z):
                best_z = floor_z

        if best_z is not None:
            param = beam.LookupParameter(param_name)
            if param and not param.IsReadOnly:
                param.Set(beam_z - best_z)

    t.Commit()
except Exception:
    t.RollBack()
    raise

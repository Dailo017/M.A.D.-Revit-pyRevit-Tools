# -*- coding: utf-8 -*-
__title__   = "Pipe\nOrientation"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Indicates whether the pipes in the project are vertical,
horizontal, or sloped, and writes the result in the
parameter chosen in the form.

- Vertical   : angle to the Z axis <= 1.0°
- Horizontal : angle to the Z axis within 90° ± 0.5°
- Sloped     : "Slope <value>" (pipe slope)
________________________________________________________________
How-To:

1. Click the button and type the parameter name where the
   result will be stored.
2. The parameter must be a TEXT, INSTANCE project parameter
   assigned to the Pipes category; otherwise you'll be warned.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Parameter chosen in a form + project parameter check
- [15.06.2024] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from math import degrees
from pyrevit import forms

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

TOL_VERTICAL   = 1.0      # degrees
TOL_HORIZONTAL = 0.5      # degrees

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Form to type the parameter where the result is stored.
param_name = forms.ask_for_string(default="test_inclinacion",
                                  prompt="Parameter name where the pipe orientation will be stored:",
                                  title="Pipe Orientation")
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 2- Check it exists as a project parameter (instance) assigned to Pipes.
pipes_cat = Category.GetCategory(doc, BuiltInCategory.OST_PipeCurves)
binding   = None
iterator  = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter, data type TEXT, '
                'for the Pipes category.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)
if not binding.Categories.Contains(pipes_cat):
    forms.alert('The project parameter "{}" is not assigned to the Pipes category.'.format(param_name), exitscript=True)

# 3- Collect the pipes and check the parameter data type.
pipes = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PipeCurves).WhereElementIsNotElementType().ToElements()
if not pipes:
    forms.alert("There are no pipes in the project.", exitscript=True)

first_param = pipes[0].LookupParameter(param_name)
if not first_param or first_param.StorageType != StorageType.String:
    forms.alert('The project parameter "{}" must be of data type TEXT.'.format(param_name), exitscript=True)

# 4- Write the orientation of each pipe.
t = Transaction(doc, "Pipe Orientation")
t.Start()
try:
    for pipe in pipes:
        param = pipe.LookupParameter(param_name)
        if not param or param.IsReadOnly:
            continue

        direction = pipe.Location.Curve.Direction
        slope     = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_SLOPE).AsValueString()

        angle_deg = degrees(direction.AngleTo(XYZ.BasisZ))
        # key: vertical pointing up and down
        angle_vertical = min(angle_deg, 180 - angle_deg)

        if angle_vertical <= TOL_VERTICAL:
            param.Set("Vertical")
        elif abs(angle_deg - 90) <= TOL_HORIZONTAL:
            param.Set("Horizontal")
        else:
            param.Set("Slope  {}%".format(slope))

    t.Commit()
except Exception:
    t.RollBack()
    raise

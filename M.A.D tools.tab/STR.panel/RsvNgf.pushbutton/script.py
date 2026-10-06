# -*- coding: utf-8 -*-
__title__   = "RSV\nNGF"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Calculates the NGF elevation of the bottom of the selected
reservations (RSV) and writes it in the parameter chosen in
the form:

    result = level elevation + offset - (RSV_H or RSV_D) / 2

RSV_H has priority; if it has no value, RSV_D is used.
The reservations must be hosted on a level.
________________________________________________________________
How-To:

1. Click the button and type the parameter name where the
   result will be stored. It must be a LENGTH, INSTANCE project
   parameter; otherwise you'll be warned.
2. Select the reservations.
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
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import forms

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document

PARAM_H = "RSV_H"
PARAM_D = "RSV_D"

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Form to type the parameter where the result is stored.
param_name = forms.ask_for_string(default="RSV_Ai_NGF",
                                  prompt="Parameter name where the NGF elevation will be stored:",
                                  title="RSV NGF")
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 2- Check it exists as an INSTANCE project parameter.
binding  = None
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter, data type LENGTH, '
                'for the categories of the reservations.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)

# 3- Select the reservations and check the parameter on them.
try:
    refs = uidoc.Selection.PickObjects(ObjectType.Element)
except:
    forms.alert("No elements were selected.", exitscript=True)
elem_select = [doc.GetElement(r) for r in refs]

params = [e.LookupParameter(param_name) for e in elem_select]
params = [p for p in params if p]
if not params:
    forms.alert('The project parameter "{}" is not assigned to the categories '
                'of the selected elements.'.format(param_name), exitscript=True)
if params[0].StorageType != StorageType.Double:
    forms.alert('The project parameter "{}" must be of data type LENGTH.'.format(param_name), exitscript=True)

# 4- Calculate and write the result
done, skipped = 0, 0
t = Transaction(doc, "RSV NGF")
t.Start()
try:
    for elem in elem_select:
        param_result = elem.LookupParameter(param_name)
        p_level      = elem.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
        p_offset     = elem.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM)
        level        = doc.GetElement(p_level.AsElementId()) if p_level else None
        if not param_result or param_result.IsReadOnly or not level or not p_offset:
            skipped += 1        # nowhere to write, or not hosted on a level
            continue

        level_elev = level.get_Parameter(BuiltInParameter.LEVEL_ELEV).AsDouble()
        offset     = p_offset.AsDouble()

        # Priority: RSV_H, then RSV_D, otherwise skip
        param_h = elem.LookupParameter(PARAM_H)
        param_d = elem.LookupParameter(PARAM_D)
        if param_h and param_h.HasValue:
            half = param_h.AsDouble() / 2
        elif param_d and param_d.HasValue:
            half = param_d.AsDouble() / 2
        else:
            skipped += 1
            continue

        param_result.Set(level_elev + offset - half)
        done += 1

    t.Commit()
except Exception:
    t.RollBack()
    raise

if skipped:
    forms.alert("Updated: {}\nSkipped (no level, no {}/{} or no parameter): {}".format(
        done, PARAM_H, PARAM_D, skipped))

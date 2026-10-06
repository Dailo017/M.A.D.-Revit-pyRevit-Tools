# -*- coding: utf-8 -*-
__title__   = "Host\nParameter"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Copies the value of a parameter from each duct / pipe to its
insulation and lining (same parameter name on both).
Text, integer and number/length values are copied.
________________________________________________________________
How-To:

1. Click the button and type the parameter name. It must be an
   INSTANCE project parameter assigned to the insulation /
   lining categories (and to the hosts); otherwise you'll be
   warned.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Project parameter check + elements without
                    the parameter are skipped
- [01.04.2026] v1.0 First release
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

INSULATION_CATEGORIES = [BuiltInCategory.OST_PipeInsulations, BuiltInCategory.OST_DuctInsulations,
                         BuiltInCategory.OST_DuctLinings]

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Form to type the parameter to copy.
param_name = forms.ask_for_string(default='param_name', prompt='Write The Parameter Name:',
                                  title='Parameter Name')
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 2- Check it exists as an INSTANCE project parameter assigned to insulations / linings.
binding  = None
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter for the ducts / pipes and '
                'their insulation and lining categories.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)
if not any(binding.Categories.Contains(Category.GetCategory(doc, bic)) for bic in INSULATION_CATEGORIES):
    forms.alert('The project parameter "{}" is not assigned to any insulation '
                'or lining category.'.format(param_name), exitscript=True)

# 3- Copy host -> insulation / lining
copied, skipped = 0, 0
t = Transaction(doc, 'Host Parameter')
t.Start()
try:
    for iso in FilteredElementCollector(doc).OfClass(InsulationLiningBase).WhereElementIsNotElementType().ToElements():
        host   = doc.GetElement(iso.HostElementId)
        source = host.LookupParameter(param_name) if host else None
        target = iso.LookupParameter(param_name)
        if not source or not target or target.IsReadOnly:
            skipped += 1
            continue

        if source.StorageType == StorageType.String:
            target.Set(source.AsString() or "")
        elif source.StorageType == StorageType.Integer:
            target.Set(source.AsInteger())
        elif source.StorageType == StorageType.Double:
            target.Set(source.AsDouble())
        else:
            skipped += 1
            continue
        copied += 1

    t.Commit()
except Exception:
    t.RollBack()
    raise

forms.alert("Copied: {}\nSkipped (parameter missing or not copyable): {}".format(copied, skipped))

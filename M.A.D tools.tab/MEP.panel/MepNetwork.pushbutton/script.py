# -*- coding: utf-8 -*-
__title__   = "MEP\nNetwork"
__doc__     = """Version = 1.1
Date    = 05.10.2026
________________________________________________________________
Description:

Creates a network of ducts or pipes from detail/model lines:
1- Creates a placeholder on each selected line.
2- Connects the placeholders that meet at the same point
   (elbow = 2, tee = 3, cross = 4).
3- Converts the placeholders into real ducts / pipes.
________________________________________________________________
How-To:

1. Open a floor plan (the network is created on its level).
2. Click the button and choose Ducts or Pipes, then the type
   and the system type.
3. Select the lines.
________________________________________________________________
Last Updates:
- [05.10.2026] v1.1 Ducts and Pipes share the same code + only
                    matching system types are listed
- [29.06.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import Duct, DuctType, MechanicalSystemType, MechanicalUtils
from Autodesk.Revit.DB.Plumbing import Pipe, PipeType, PipingSystemType, PlumbingUtils
from Autodesk.Revit.UI.Selection import ObjectType
from rpw.ui.forms import FlexForm, Label, ComboBox, Separator, Button
from pyrevit import forms, script

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

output = script.get_output()

TOL = 0.001   # feet

# Everything that changes between ducts and pipes
MEP_OPTIONS = {
    'Ducts': {'type_cls': DuctType, 'system_cls': MechanicalSystemType,
              'create': Duct.CreatePlaceholder,
              'elbow':  MechanicalUtils.ConnectDuctPlaceholdersAtElbow,
              'tee':    MechanicalUtils.ConnectDuctPlaceholdersAtTee,
              'cross':  MechanicalUtils.ConnectDuctPlaceholdersAtCross,
              'convert': MechanicalUtils.ConvertDuctPlaceholders},
    'Pipes': {'type_cls': PipeType, 'system_cls': PipingSystemType,
              'create': Pipe.CreatePlaceholder,
              'elbow':  PlumbingUtils.ConnectPipePlaceholdersAtElbow,
              'tee':    PlumbingUtils.ConnectPipePlaceholdersAtTee,
              'cross':  PlumbingUtils.ConnectPipePlaceholdersAtCross,
              'convert': PlumbingUtils.ConvertPipePlaceholders},
}

def point_key(pt):
    return (round(pt.X / TOL), round(pt.Y / TOL), round(pt.Z / TOL))

def get_direction(mep):
    curve = mep.Location.Curve
    return (curve.GetEndPoint(1) - curve.GetEndPoint(0)).Normalize()

def is_parallel(v1, v2):
    return abs(abs(v1.DotProduct(v2)) - 1.0) < 0.01

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- The active view must have a level.
level = doc.ActiveView.GenLevel
if not level:
    forms.alert("Active view has no level (use a floor plan).", exitscript=True)

# 2- Form: Ducts or Pipes
form = FlexForm('MEP Network', [Label('Pick MEP Type:'),
                                ComboBox('mep', {'Ducts': 'Ducts', 'Pipes': 'Pipes'}),
                                Separator(), Button('Select')])
if not form.show():
    script.exit()
opt = MEP_OPTIONS[form.values['mep']]

# 3- Form: type and system type
types   = {Element.Name.GetValue(e): e.Id for e in FilteredElementCollector(doc).OfClass(opt['type_cls']).ToElements()}
systems = {Element.Name.GetValue(e): e.Id for e in FilteredElementCollector(doc).OfClass(opt['system_cls']).ToElements()}
if not types or not systems:
    forms.alert("There are no {} types or system types in this project.".format(form.values['mep'].lower()), exitscript=True)

form = FlexForm('MEP Network', [Label('Pick Type:'), ComboBox('type', types),
                                Label('Pick System Type:'), ComboBox('system', systems),
                                Separator(), Button('Select')])
if not form.show():
    script.exit()
type_id, system_type_id = form.values['type'], form.values['system']

# 4- Select the lines
try:
    refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select the lines")
except:
    forms.alert("No lines were selected.", exitscript=True)
lines = [doc.GetElement(r) for r in refs]

# 5- Placeholders, connections and conversion
t = Transaction(doc, "Create MEP Network")
t.Start()
try:
    place_holders = []
    for line in lines:
        try:
            curve = line.GeometryCurve
            place_holders.append(opt['create'](doc, system_type_id, type_id, level.Id,
                                               curve.GetEndPoint(0), curve.GetEndPoint(1)))
        except Exception:
            pass        # not a line

    # Group placeholders by shared end point
    nodes = {}
    for ph in place_holders:
        curve = ph.Location.Curve
        for i in (0, 1):
            nodes.setdefault(point_key(curve.GetEndPoint(i)), []).append(ph)

    # Connect them
    for meps in nodes.values():
        try:
            if len(meps) == 2:                                  # ELBOW
                if not is_parallel(get_direction(meps[0]), get_direction(meps[1])):
                    opt['elbow'](doc, meps[0].Id, meps[1].Id)
            elif len(meps) == 3:                                # TEE
                pair = [(a, b) for a in meps for b in meps
                        if a.Id != b.Id and is_parallel(get_direction(a), get_direction(b))]
                if pair:
                    opt['tee'](doc, pair[0][0].Id, pair[0][1].Id)
            elif len(meps) == 4:                                # CROSS
                opt['cross'](doc, meps[0].Id, meps[1].Id)
        except Exception as ex:
            output.print_md("- Connection error: {}".format(ex))

    # Convert to real ducts / pipes
    try:
        opt['convert'](doc, List[ElementId]([ph.Id for ph in place_holders]))
    except Exception as ex:
        output.print_md("- Conversion error: {}".format(ex))

    t.Commit()
except Exception:
    t.RollBack()
    raise

forms.alert("{} of {} lines converted.".format(len(place_holders), len(lines)))

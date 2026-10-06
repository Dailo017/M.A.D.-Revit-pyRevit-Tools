# -*- coding: utf-8 -*-
__title__   = "Copy Room\nName"
__doc__     = """Version = 2.1
Date    = 05.10.2026
________________________________________________________________
Description:

Copies the name of the room (from a linked model) where each
plumbing fixture, plumbing equipment and pipe accessory is
located, into the parameter chosen in the form.

If the element is not inside any room, the room whose boundary
is closer than 15 cm (TOLERANCE_M) is used; otherwise
"Outside Room" is written.
________________________________________________________________
How-To:

1. Click the button and type the parameter name where the room
   name will be stored. It must be a TEXT, INSTANCE project
   parameter assigned to Plumbing Fixtures, Plumbing Equipment
   and Pipe Accessories; otherwise you'll be warned.
2. Select the linked model with the rooms.
________________________________________________________________
Last Updates:
- [05.10.2026] v2.1 Parameter chosen in a form + project parameter check
- [03.03.2026] v2.0 15 cm tolerance to the room boundary
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

CATEGORIES = {BuiltInCategory.OST_PlumbingFixtures:  "Plumbing Fixtures",
              BuiltInCategory.OST_PlumbingEquipment: "Plumbing Equipment",
              BuiltInCategory.OST_PipeAccessory:     "Pipe Accessories"}
TOLERANCE_M  = 0.15
OUTSIDE_TEXT = "Outside Room"

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Form to type the parameter where the room name is stored.
param_name = forms.ask_for_string(default="RoomHost",
                                  prompt="Parameter name where the room name will be stored:",
                                  title="Copy Room Name")
if not param_name or not param_name.strip():
    forms.alert("No parameter name was entered.", exitscript=True)
param_name = param_name.strip()

# 2- Check it exists as an INSTANCE project parameter assigned to the categories.
binding  = None
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    if iterator.Key.Name == param_name:
        binding = iterator.Current
        break

if binding is None:
    forms.alert('"{}" is not created as a project parameter.\n\n'
                'Create it as an INSTANCE parameter, data type TEXT, for '
                'Plumbing Fixtures, Plumbing Equipment and Pipe Accessories.'.format(param_name), exitscript=True)
if not isinstance(binding, InstanceBinding):
    forms.alert('The project parameter "{}" is a TYPE parameter.\n\n'
                'It must be an INSTANCE parameter.'.format(param_name), exitscript=True)
missing = [name for bic, name in CATEGORIES.items() if not binding.Categories.Contains(Category.GetCategory(doc, bic))]
if missing:
    forms.alert('The project parameter "{}" is not assigned to: {}.'.format(param_name, ", ".join(missing)), exitscript=True)

# 3- Collect the elements and check the parameter data type.
multi_filter = LogicalOrFilter([ElementCategoryFilter(bic) for bic in CATEGORIES])
elementos = FilteredElementCollector(doc).WherePasses(multi_filter).WhereElementIsNotElementType().ToElements()
if not elementos:
    forms.alert("There are no plumbing fixtures, equipment or pipe accessories in the project.", exitscript=True)

first_param = elementos[0].LookupParameter(param_name)
if not first_param or first_param.StorageType != StorageType.String:
    forms.alert('The project parameter "{}" must be of data type TEXT.'.format(param_name), exitscript=True)

# 4- Select the linked model with the rooms
all_rvt_links  = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()
dict_rvt_links = {lnk.GetLinkDocument().Title: lnk for lnk in all_rvt_links if lnk.GetLinkDocument()}
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

habitaciones = FilteredElementCollector(linked_doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()
tolerancia   = UnitUtils.ConvertToInternalUnits(TOLERANCE_M, UnitTypeId.Meters)
opciones     = SpatialElementBoundaryOptions()

# 5- Write the room name in each element
t = Transaction(doc, "Copy Room Name with Tolerance")
t.Start()
try:
    for elemento in elementos:
        loc = elemento.Location
        if not isinstance(loc, LocationPoint):
            continue
        param = elemento.LookupParameter(param_name)
        if not param or param.IsReadOnly:
            continue

        punto_link = transform.Inverse.OfPoint(loc.Point)

        # Quick attempt: point inside a room
        habitacion = linked_doc.GetRoomAtPoint(punto_link)

        # Otherwise: room whose boundary is closer than the tolerance
        if not habitacion:
            for room in habitaciones:
                for boundary_list in (room.GetBoundarySegments(opciones) or []):
                    for segment in boundary_list:
                        resultado = segment.GetCurve().Project(punto_link)
                        if resultado and resultado.Distance <= tolerancia:
                            habitacion = room
                            break
                    if habitacion:
                        break
                if habitacion:
                    break

        param.Set(Element.Name.GetValue(habitacion) if habitacion else OUTSIDE_TEXT)

    t.Commit()
except Exception:
    t.RollBack()
    raise

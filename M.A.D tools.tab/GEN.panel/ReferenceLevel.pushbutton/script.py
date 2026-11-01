# -*- coding: utf-8 -*-
__title__   = "Reference\nLevel"
__doc__     = """Version = 2.2
Date    = 01.11.2026
________________________________________________________________
Description:

Changes the reference level of the selected elements WITHOUT
moving them: the offset is recalculated so the elements keep
their current elevation.

Works with MEP elements (pipes, ducts, trays, conduits,
fittings, equipment, lighting, devices), walls, shafts,
floors, foundations, columns, beams, ceilings, roofs,
stairs, generic models, families and model groups.
Curtain panels, wall foundations and wall-hosted families take
their host's level: they follow it. Beams drawn on their level
whose end joins Revit would break are left untouched.

Safety: the elements, what they host and what they are
connected to are compared with the original. Misaligned MEP
joints may be re-aligned by Revit (up to 5 mm); anything that
would move more, or that gives a Revit error (disconnection,
line too short...), is left exactly as it was.
________________________________________________________________
How-To:

1. Select the elements (before or after clicking the button).
2. Choose the new reference level.
3. The elements that could not be changed stay selected.
________________________________________________________________
Last Updates:
- [01.11.2026] v2.2 Curtain panels / wall foundations follow their
                    host (not reported as not changed)
- [01.11.2026] v2.1 Much faster, MEP connections kept, rollback
                    on any Revit error, joints < 5 mm re-aligned,
                    elements not changed stay selected
- [01.11.2026] v2.0 Architectural/structural elements + groups,
                    geometry check (nothing moves)
- [05.10.2026] v1.1 Cleanup + cancel handling
- [11.02.2026] v1.0 First release
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
from pyrevit import forms

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document #type:Document

B = BuiltInParameter
# (level parameter, [offsets measured from that level]) - first valid pair is used
PAIRS = [
    (B.RBS_START_LEVEL_PARAM,              [B.RBS_OFFSET_PARAM]),                 # Pipes, ducts, trays...
    (B.WALL_BASE_CONSTRAINT,               [B.WALL_BASE_OFFSET]),                 # Walls
    (B.FAMILY_BASE_LEVEL_PARAM,            [B.FAMILY_BASE_LEVEL_OFFSET_PARAM]),   # Columns
    (B.INSTANCE_REFERENCE_LEVEL_PARAM,     [B.STRUCTURAL_BEAM_END0_ELEVATION,
                                            B.STRUCTURAL_BEAM_END1_ELEVATION]),   # Beams
    (B.LEVEL_PARAM,                        [B.FLOOR_HEIGHTABOVELEVEL_PARAM]),     # Floors, slab foundations
    (B.LEVEL_PARAM,                        [B.CEILING_HEIGHTABOVELEVEL_PARAM]),   # Ceilings
    (B.ROOF_BASE_LEVEL_PARAM,              [B.ROOF_LEVEL_OFFSET_PARAM]),          # Roofs
    (B.STAIRS_BASE_LEVEL,                  [B.STAIRS_BASE_OFFSET]),               # Stairs
    (B.STAIRS_BASE_LEVEL_PARAM,            [B.STAIRS_BASE_OFFSET]),
    (B.GROUP_LEVEL,                        [B.GROUP_OFFSET_FROM_LEVEL]),          # Model groups
    (B.FAMILY_LEVEL_PARAM,                 [B.INSTANCE_ELEVATION_PARAM]),         # Families, isolated foundations
    (B.FAMILY_LEVEL_PARAM,                 [B.INSTANCE_FREE_HOST_OFFSET_PARAM]),
    (B.FAMILY_LEVEL_PARAM,                 [B.FLOOR_HEIGHTABOVELEVEL_PARAM]),
    (B.INSTANCE_REFERENCE_LEVEL_PARAM,     [B.INSTANCE_ELEVATION_PARAM]),
    (B.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM, []),                                   # Wall/face hosted families
]
TOL = 1e-6           # feet: below this nothing moved
FIX = 5 / 304.8      # feet: Revit may re-align a misaligned joint up to 5 mm
BAD = ("moved", "error")

# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝
#==================================================
def writable(el, bip):
    p = el.get_Parameter(bip)
    return p if p and not p.IsReadOnly else None

def find_pair(el):
    """Return (level_param, [offset_params]) or None."""
    for lv_bip, off_bips in PAIRS:
        lv_p = writable(el, lv_bip)
        if not lv_p or lv_p.StorageType != StorageType.ElementId:
            continue
        offs = [writable(el, b) for b in off_bips]
        if not all(offs):
            continue
        if offs and not isinstance(doc.GetElement(lv_p.AsElementId()), Level):
            continue
        return lv_p, offs
    return None

def unlock_beam(el):
    """A horizontal beam drawn on its level has the reference level locked.
    Tilting it for a moment unlocks it; the end offset is then restored."""
    lv = el.get_Parameter(B.INSTANCE_REFERENCE_LEVEL_PARAM)
    e1 = writable(el, B.STRUCTURAL_BEAM_END1_ELEVATION)
    if lv and lv.IsReadOnly and e1:
        v = e1.AsDouble()
        e1.Set(v + 0.01)
        doc.Regenerate()
        e1.Set(v)

def connected(el):
    """MEP elements connected to el."""
    try:
        cm = el.MEPModel.ConnectorManager if isinstance(el, FamilyInstance) else el.ConnectorManager
        return [r.Owner for c in cm.Connectors for r in c.AllRefs
                if r.Owner.Id != el.Id and not isinstance(r.Owner, MEPSystem)]
    except Exception:
        return []

def shift(w, before):
    """How far the element moved (feet). Deleted = infinite."""
    if not w.IsValidObject:
        return float("inf")
    after = w.get_BoundingBox(None)
    if before is None or after is None:
        return 0.0 if before is None and after is None else float("inf")
    return max(before.Min.DistanceTo(after.Min), before.Max.DistanceTo(after.Max))

def set_level(el):
    """Set the new level (and the offset, only if Revit did not keep the
    elevation by itself). Returns the level parameter, or a status."""
    if el.GroupId != ElementId.InvalidElementId:
        return "skipped"
    unlock_beam(el)
    pair = find_pair(el)
    if not pair:
        return "skipped"
    lv_p, offs = pair
    if lv_p.AsElementId() == new_level.Id:
        return "same"

    old    = doc.GetElement(lv_p.AsElementId())
    values = [p.AsDouble() + old.ProjectElevation - new_level.ProjectElevation for p in offs]
    lv_p.Set(new_level.Id)
    for p, v in zip(offs, values):
        if abs(p.AsDouble() - v) > TOL:  # pipes, fittings... are already right: don't touch them
            p.Set(v)
    return lv_p

class RollbackOnError(IFailuresPreprocessor):
    """Any Revit error (disconnection, line too short...) cancels the block."""
    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() != FailureSeverity.Warning:
                return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue

def try_batch(els):
    """Change all elements at once (one regeneration). Kept only if nothing
    moved more than 5 mm and Revit gives no error; one status per element."""
    watch  = [[el] + hosted.get(el.Id, []) + connected(el) for el in els]
    unique = dict((w.Id, w) for ws in watch for w in ws)   # each box measured once
    watch  = [[w.Id for w in ws] for ws in watch]
    before = dict((i, w.get_BoundingBox(None)) for i, w in unique.items())

    t = Transaction(doc, "Reference Level")
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(RollbackOnError())
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    res = []
    for el in els:
        try:
            res.append(set_level(el))
        except Exception:
            res.append("error")
    doc.Regenerate()

    moved = dict((i, shift(w, before[i])) for i, w in unique.items())
    for i, r in enumerate(res):
        if isinstance(r, Parameter):
            worst = max(moved[w] for w in watch[i])
            if worst > FIX:
                res[i] = "moved"
            elif r.AsElementId() != new_level.Id:   # Revit ignored it (e.g. wall hosted)
                res[i] = "skipped"
            elif worst > TOL:
                res[i] = "fixed"                    # joint re-aligned (< 5 mm)
            else:
                res[i] = "done"

    if any(s in BAD for s in res):
        t.RollBack()
    elif t.Commit() != TransactionStatus.Committed:      # Revit error: block rolled back
        res = ["error" if s in ("done", "fixed") else s for s in res]
    return res

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# 1- Elements: current selection, or pick
ids = list(uidoc.Selection.GetElementIds())
if not ids:
    try:
        ids = [r.ElementId for r in uidoc.Selection.PickObjects(ObjectType.Element)]
    except:
        forms.alert("No elements were selected.", exitscript=True)
elems = [doc.GetElement(i) for i in ids]

# 2- Level (sorted by elevation)
levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.ProjectElevation)
res = forms.SelectFromList.show([l.Name for l in levels], button_name='Select Level')
if not res:
    forms.alert("No level selected.", exitscript=True)
new_level = [l for l in levels if l.Name == res][0]

# 3- Elements hosted by others (face based families can move if their host changes)
hosted = {}
if any(isinstance(el, HostObject) for el in elems):   # walls, floors, ceilings, roofs...
    for fi in FilteredElementCollector(doc).OfClass(FamilyInstance):
        if fi.Host:
            hosted.setdefault(fi.Host.Id, []).append(fi)

# 4- Blocks of elements at once; the ones that cause trouble are retried one by one
status = []   # (element, status)
tg = TransactionGroup(doc, "Reference Level")   # one single Undo
tg.Start()
singles = []
with forms.ProgressBar(title="Changing reference level... ({value} of {max_value})") as pb:
    for k in range(0, len(elems), 200):   # blocks of 200: a problem only redoes its block
        batch = elems[k:k + 200]
        while batch:
            res = try_batch(batch)
            bad = [el for el, s in zip(batch, res) if s in BAD]
            if not bad:
                status += zip(batch, res)
                break
            singles += bad
            batch = [el for el, s in zip(batch, res) if s not in BAD]
        pb.update_progress(len(status), len(elems))
    for el in singles:
        status += zip([el], try_batch([el]))
        pb.update_progress(len(status), len(elems))
tg.Assimilate()

# 5- Curtain panels, wall foundations, wall hosted families... take the level of their host
def follows(el):
    host = doc.GetElement(el.WallId) if isinstance(el, WallFoundation) else el
    return host.LevelId == new_level.Id
status = [(el, "follows" if s == "skipped" and follows(el) else s) for el, s in status]

# 6- Report: the elements that were not changed stay selected
not_changed = [el.Id for el, s in status if s not in ("done", "fixed", "same", "follows")]
uidoc.Selection.SetElementIds(List[ElementId](not_changed))

count = dict((k, sum(1 for el, s in status if s == k)) for k in ("done", "fixed", "same", "follows", "skipped", "moved", "error"))
msg = "Level '{}': {} element(s) changed.".format(new_level.Name, count["done"] + count["fixed"])
if count["fixed"]:   msg += "\n({} of them with a misaligned joint re-aligned, less than 5 mm.)".format(count["fixed"])
if count["follows"]: msg += "\n{} follow their host (curtain panels, wall foundations...): now on that level too.".format(count["follows"])
if count["same"]:    msg += "\n{} already on that level.".format(count["same"])
if count["skipped"]: msg += "\n{} with no editable level (wall hosted, inside a group...): skipped.".format(count["skipped"])
if count["moved"]:   msg += ("\n{} would have moved something more than 5 mm: left untouched."
                             "\n(Beams drawn on their level: Revit would break their end joins.)").format(count["moved"])
if count["error"]:   msg += "\n{} gave a Revit error (line too short, disconnection...): left untouched.".format(count["error"])
if not_changed:      msg += "\n\nThe {} element(s) not changed are now selected.".format(len(not_changed))
forms.alert(msg)

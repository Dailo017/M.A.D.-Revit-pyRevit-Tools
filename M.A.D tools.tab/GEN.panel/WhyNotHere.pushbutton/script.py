# -*- coding: utf-8 -*-
__title__ = "Why Not Here?"
__persistentengine__ = True
__doc__ = """Version = 0.3.15
Date    = 27.06.2026
Target Revit Versions = 2024+
pyRevit Version       = 5.x
________________________________________________________________
Description:
Pick or use one host-model element, choose a target graphical view, and show
visibility diagnostics in a modeless WPF form.

The report is grouped into confirmed blockers, possible issues, and checks that
passed. Direct fixes are offered only for scoped, reversible view settings.

________________________________________________________________
How-To:
1. Select one element or run the tool and pick one visible host-model element.
2. Use the active view or choose a target graphical view.
3. Analyze, review issue cards, and optionally run safe fixes.
4. Recheck after changes.

________________________________________________________________
Scope:
- One picked or selected host-model element.
- One target graphical model view.
- Linked-model elements and complex edge cases are not supported in v1.
- Production views are never changed silently.

________________________________________________________________
Icon Decision:
Existing icon assets are preserved. No new icons were generated for this WPF
refactor or simplification. The modeless WPF form clears pyRevit's injected
window icon so the title bar uses the default Revit icon, matching Insulation
Phase Matcher.

________________________________________________________________
Revert Snapshot:
Before this refactor, the working bundle was copied to:
tmp/revert-snapshots/WhyNotHere.pushbutton-before-wpf-20260625-205216/

________________________________________________________________
Last Updates:
- [27.06.2026] v0.3.17 Split blocker and possible issue header statuses.
- [27.06.2026] v0.3.16 Expand and emphasize possible issues whenever they exist.
- [27.06.2026] v0.3.15 Highlight possible-issue results in the header and collapsed possible section.
- [27.06.2026] v0.3.14 Replace pipe-only Architectural cut-plane check with broad, inferred MEP above-cut diagnostic.
- [27.06.2026] v0.3.13 Make discipline diagnostic evidence-first so missed gates are visible in Possible/Passed cards.
- [27.06.2026] v0.3.12 Broaden Architectural discipline pipe check to pipe-related categories and bounding-box fallback.
- [27.06.2026] v0.3.11 Add Architectural discipline pipe-above-cut-plane diagnostic with Coordination fix and undo.
- [26.06.2026] v0.3.10 Use element location elevation for pipe-like view range diagnostics before bounding-box fallback.
- [26.06.2026] v0.3.9 Add explicit 2D crop expansion fix with undo for confirmed crop-region blockers.
- [26.06.2026] v0.3.8 Clarify first-screen wording around the view where the element is missing.
- [26.06.2026] v0.3.7 Refresh results UI with target summary, section reorder, status markers, and subtle severity tinting.
- [26.06.2026] v0.3.6 Add automatic least-change view range adjustment for confirmed view range blockers.
- [26.06.2026] v0.3.5 Remove duplicate close button, add Back, explain possible issues, and add a guarded View Range shortcut.
- [26.06.2026] v0.3.4 Activate the target view after successful fix actions so users land where the element should now be visible.
- [26.06.2026] v0.3.3 Simplify unused code and centralize fix/undo action dispatch.
- [26.06.2026] v0.3.2 Use default Revit title-bar icon for the modeless WPF window, matching Insulation Phase Matcher.
- [25.06.2026] v0.3.1 Match Insulation Matcher modeless lifecycle: persistent engine, retained state, queued ExternalEvent requests, dispatcher callbacks.
- [25.06.2026] v0.3 Make WPF window modeless, remove manual actions, and hide passed checks.
- [25.06.2026] v0.2.2 Add WarningBar selection prompt, view range check, and safer manual actions.
- [25.06.2026] v0.2.1 Remove active-view target option and post settings commands after modal close.
- [25.06.2026] v0.2 Refactor to modal WPF diagnostics UI.
- [25.06.2026] v0.1.6 Include dependent element ids when unhiding and clearing overrides.
- [25.06.2026] v0.1.5 Clear element graphic overrides after API unhide.
- [25.06.2026] v0.1.4 Refresh active view and rebuild graphics during unhide action.
- [25.06.2026] v0.1.3 Regenerate and clear selection after unhide to avoid selected-element graphics.
- [25.06.2026] v0.1.2 Fix individual hide check to use Element.IsHidden(view).
- [25.06.2026] v0.1.1 Pick element after launch and remove unreliable host-model document check.
- [25.06.2026] v0.1 Initial tool.

________________________________________________________________
Author: Dimitris Koumantakis"""

import os
import traceback
from collections import deque

import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System

from System.Collections.Generic import List
from System.Windows import CornerRadius, FontWeights, HorizontalAlignment, Thickness, TextWrapping, Visibility
from System.Windows.Controls import Border, Button, Dock, DockPanel, Orientation, StackPanel, TextBlock
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import Brushes

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Options,
    OverrideGraphicSettings,
    ParameterFilterElement,
    PlanViewPlane,
    SelectionFilterElement,
    Transaction,
    TransactionStatus,
    View,
    View3D,
    ViewPlan,
    ViewType,
    WorksetDefaultVisibilitySettings,
    WorksetVisibility,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.UI.Selection import ObjectType

from pyrevit import forms, script


uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document if uidoc else None
output = None
logger = script.get_logger()

try:
    _WNH_STATE
except NameError:
    _WNH_STATE = {
        "handler": None,
        "ext_event": None,
        "ui": None
    }


# -----------------------------------------------------------------------------
# Constants and simple models
# -----------------------------------------------------------------------------

TOOL_NAME = __title__
TARGET_REVIT_VERSIONS = "2024+"
TARGET_PYREVIT_VERSION = "5.x"
XAML_FILE = os.path.join(os.path.dirname(__file__), "WhyNotHere.xaml")

ACTION_UNHIDE_ELEMENT = "unhide_element"
ACTION_SHOW_CATEGORY = "show_category"
ACTION_SHOW_FILTER = "show_filter"
ACTION_SHOW_WORKSET = "show_workset"
ACTION_ADJUST_VIEW_RANGE = "adjust_view_range"
ACTION_EXPAND_CROP_REGION = "expand_crop_region"

ACTION_LABELS = {
    ACTION_UNHIDE_ELEMENT: "Fix: Unhide Element",
    ACTION_SHOW_CATEGORY: "Fix: Show Category",
    ACTION_SHOW_FILTER: "Fix: Show Filter",
    ACTION_SHOW_WORKSET: "Fix: Show Workset",
    ACTION_ADJUST_VIEW_RANGE: "Adjust View Range Automatically",
    ACTION_EXPAND_CROP_REGION: "Expand Crop to Include Element",
}

VIEW_RANGE_CLEARANCE_FEET = 1.0 / 304.8
ELEVATION_TOLERANCE_FEET = 1.0 / 304.8
CROP_CLEARANCE_MM = 300.0
CROP_CLEARANCE_FEET = CROP_CLEARANCE_MM / 304.8
DISCIPLINE_ARCHITECTURAL_VALUE = 1
DISCIPLINE_COORDINATION_VALUE = 4095

SUPPORTED_TARGET_VIEW_TYPES = set([
    ViewType.FloorPlan,
    ViewType.CeilingPlan,
    ViewType.EngineeringPlan,
    ViewType.AreaPlan,
    ViewType.Elevation,
    ViewType.Section,
    ViewType.ThreeD,
])

REQUIRED_RESOURCE_KEYS = [
    "Brush.Accent",
    "Brush.Text",
    "Brush.Subtext",
    "Brush.Success",
    "Brush.Warning",
    "Brush.Danger",
    "Brush.Border",
    "Brush.Surface",
    "Brush.BlockerSurface",
    "Brush.BlockerBorder",
    "Brush.SuccessSurface",
    "Brush.SuccessBorder",
    "Brush.PossibleSurface",
    "Brush.PossibleBorder",
    "Button.Primary",
    "Button.Secondary",
]


class CheckResult(object):
    def __init__(
        self,
        group,
        title,
        explanation,
        evidence=None,
        recommendation=None,
        action_name=None,
        action_data=None
    ):
        self.group = group
        self.title = title
        self.explanation = explanation
        self.evidence = evidence or ""
        self.recommendation = recommendation or ""
        self.action_name = action_name
        self.action_data = action_data
        self.fixed = False
        self.fix_message = ""


class ViewChoice(object):
    def __init__(self, view):
        self.view = view
        self.display_name = "{0}  [{1}]".format(view.Name, view.ViewType)

    def __str__(self):
        return self.display_name

    def ToString(self):
        return self.display_name


# -----------------------------------------------------------------------------
# Revit helpers
# -----------------------------------------------------------------------------

def require_active_document():
    if doc is None:
        forms.alert(
            "No active Revit document was found. Open a project and run this tool again.",
            exitscript=True
        )
    return doc


def get_element_id_value(element_id):
    try:
        return element_id.IntegerValue
    except Exception:
        try:
            return element_id.Value
        except Exception:
            return int(str(element_id))


def ids_are_equal(first_id, second_id):
    if first_id is None or second_id is None:
        return False
    return get_element_id_value(first_id) == get_element_id_value(second_id)


def id_is_valid(element_id):
    if element_id is None:
        return False
    return get_element_id_value(element_id) != get_element_id_value(ElementId.InvalidElementId)


def make_id_list(element_id):
    ids = List[ElementId]()
    ids.Add(element_id)
    return ids


def make_id_list_from_ids(element_ids):
    ids = List[ElementId]()
    for element_id in element_ids:
        if id_is_valid(element_id):
            ids.Add(element_id)
    return ids


def make_empty_id_list():
    return List[ElementId]()


def clear_selection():
    uidoc.Selection.SetElementIds(make_empty_id_list())


def refresh_active_view():
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass


def activate_target_view(target_view):
    try:
        if target_view and (uidoc.ActiveView is None or not ids_are_equal(uidoc.ActiveView.Id, target_view.Id)):
            uidoc.ActiveView = target_view
    except Exception:
        pass


def get_element_and_dependent_ids(element):
    element_ids = [element.Id]
    try:
        dependent_ids = list(element.GetDependentElements(None))
    except Exception:
        dependent_ids = []

    for dependent_id in dependent_ids:
        if id_is_valid(dependent_id):
            element_ids.append(dependent_id)
    return element_ids


def run_in_transaction(revit_doc, transaction_name, action_func):
    transaction = Transaction(revit_doc, transaction_name)
    try:
        start_status = transaction.Start()
        if start_status != TransactionStatus.Started:
            raise Exception("Could not start transaction: {0}".format(transaction_name))

        result = action_func()

        commit_status = transaction.Commit()
        if commit_status != TransactionStatus.Committed:
            raise Exception("Could not commit transaction: {0}".format(transaction_name))

        return result
    except Exception:
        if transaction.HasStarted() and transaction.GetStatus() == TransactionStatus.Started:
            transaction.RollBack()
        raise


def get_name(revit_doc, element_id):
    if not id_is_valid(element_id):
        return "None"
    element = revit_doc.GetElement(element_id)
    if element is None:
        return "Missing element {0}".format(get_element_id_value(element_id))
    try:
        return element.Name
    except Exception:
        return str(element)


def get_element_label(element):
    category_name = "No category"
    if element and element.Category:
        category_name = element.Category.Name
    return "{0} - ID {1}".format(category_name, get_element_id_value(element.Id))


def get_initial_element(revit_doc):
    selected_ids = list(uidoc.Selection.GetElementIds())
    if len(selected_ids) == 1:
        element = revit_doc.GetElement(selected_ids[0])
        if element is not None and element.Category is not None:
            return element

    try:
        with forms.WarningBar(title="Pick one element to investigate"):
            picked_reference = uidoc.Selection.PickObject(
                ObjectType.Element,
                "Pick one visible host-model element to investigate."
            )
    except OperationCanceledException:
        forms.alert("Element pick canceled. Nothing was changed.", exitscript=True)

    element = revit_doc.GetElement(picked_reference.ElementId)
    if element is None:
        forms.alert("The picked element could not be found.", exitscript=True)
    if element.Category is None:
        forms.alert(
            "The picked item has no category and is not supported by this tool.",
            exitscript=True
        )
    return element


def view_can_be_target(view):
    if view is None:
        return False
    if view.IsTemplate:
        return False
    if view.ViewType not in SUPPORTED_TARGET_VIEW_TYPES:
        return False
    try:
        if view.CanBePrinted is False:
            return False
    except Exception:
        pass
    return True


def collect_target_views(revit_doc):
    views = []
    active_view_id = uidoc.ActiveView.Id if uidoc and uidoc.ActiveView else None
    collector = FilteredElementCollector(revit_doc).OfClass(View)
    for view in collector:
        if active_view_id and ids_are_equal(view.Id, active_view_id):
            continue
        if view_can_be_target(view):
            views.append(ViewChoice(view))
    views.sort(key=lambda item: item.display_name.lower())
    return views


# -----------------------------------------------------------------------------
# Visibility diagnostics
# -----------------------------------------------------------------------------

def check_element_hidden(element, target_view):
    try:
        if element.IsHidden(target_view):
            return CheckResult(
                "confirmed",
                "Element hidden in view",
                "This element is hidden individually in the target view.",
                "Element ID: {0}".format(get_element_id_value(element.Id)),
                "Unhide the element in this view.",
                ACTION_UNHIDE_ELEMENT,
                element.Id
            )
        return CheckResult(
            "passed",
            "Element is not individually hidden",
            "The target view does not individually hide this element.",
            "Checked with Element.IsHidden(target_view).",
            "No correction needed."
        )
    except Exception as err:
        return CheckResult(
            "possible",
            "Could not check individual hide",
            "Revit could not confirm whether this element is individually hidden.",
            str(err),
            "Check Hide in View / Element Graphics manually."
        )


def check_category_hidden(element, target_view):
    category = element.Category
    try:
        if target_view.GetCategoryHidden(category.Id):
            return CheckResult(
                "confirmed",
                "Hidden category",
                "{0} elements are hidden in this view.".format(category.Name),
                "Category: {0}".format(category.Name),
                "Show this category in the target view.",
                ACTION_SHOW_CATEGORY,
                category.Id
            )
        return CheckResult(
            "passed",
            "Category is visible",
            "The element category is visible in the target view.",
            "Category: {0}".format(category.Name),
            "No correction needed."
        )
    except Exception as err:
        return CheckResult(
            "possible",
            "Could not check category visibility",
            "Revit could not confirm category visibility.",
            str(err),
            "Open Visibility/Graphics and confirm the category manually."
        )


def filter_applies_to_element(revit_doc, filter_element, element):
    if isinstance(filter_element, SelectionFilterElement):
        try:
            for selected_id in filter_element.GetElementIds():
                if ids_are_equal(selected_id, element.Id):
                    return True
        except Exception:
            pass
        return False

    if isinstance(filter_element, ParameterFilterElement):
        try:
            category_ids = list(filter_element.GetCategories())
            category_match = False
            for category_id in category_ids:
                if ids_are_equal(category_id, element.Category.Id):
                    category_match = True
                    break
            if not category_match:
                return False
        except Exception:
            pass

        try:
            element_filter = filter_element.GetElementFilter()
            return element_filter.PassesFilter(revit_doc, element.Id)
        except Exception:
            return True

    return False


def check_view_filters(revit_doc, element, target_view):
    results = []
    try:
        filter_ids = list(target_view.GetFilters())
    except Exception as err:
        return [CheckResult(
            "possible",
            "Could not check view filters",
            "Revit could not list filters on the target view.",
            str(err),
            "Open Visibility/Graphics and review view filters manually."
        )]

    invisible_matching_filters = []
    visible_matching_filters = []
    for filter_id in filter_ids:
        filter_element = revit_doc.GetElement(filter_id)
        if filter_element is None:
            continue
        if filter_applies_to_element(revit_doc, filter_element, element):
            try:
                is_visible = target_view.GetFilterVisibility(filter_id)
            except Exception:
                is_visible = True
            if is_visible:
                visible_matching_filters.append(filter_element)
            else:
                invisible_matching_filters.append(filter_element)

    for filter_element in invisible_matching_filters:
        results.append(CheckResult(
            "confirmed",
            "View filter hides the element",
            "A view filter applies to this element and is set to invisible.",
            "Filter: {0}".format(filter_element.Name),
            "Show this filter in the target view or adjust its rules.",
            ACTION_SHOW_FILTER,
            filter_element.Id
        ))

    if invisible_matching_filters:
        return results

    if visible_matching_filters:
        names = ", ".join([item.Name for item in visible_matching_filters])
        return [CheckResult(
            "passed",
            "Matching view filters are visible",
            "Matching filters are not hiding this element.",
            names,
            "No correction needed."
        )]

    return [CheckResult(
        "passed",
        "No hiding view filter found",
        "No invisible target-view filter was found for this element.",
        "Checked {0} filter(s).".format(len(filter_ids)),
        "No correction needed."
    )]


def check_workset(revit_doc, element, target_view):
    if not revit_doc.IsWorkshared:
        return CheckResult(
            "passed",
            "Worksharing is not enabled",
            "This model is not workshared, so workset visibility is not blocking the element.",
            "",
            "No correction needed."
        )

    try:
        workset_id = element.WorksetId
        workset_table = revit_doc.GetWorksetTable()
        workset = workset_table.GetWorkset(workset_id)
    except Exception as err:
        return CheckResult(
            "possible",
            "Could not check workset",
            "Revit could not read the element workset.",
            str(err),
            "Check workset visibility manually."
        )

    try:
        view_visibility = target_view.GetWorksetVisibility(workset_id)
        if view_visibility == WorksetVisibility.Hidden:
            return CheckResult(
                "confirmed",
                "Workset hidden in target view",
                "The element workset is hidden in the target view.",
                "Workset: {0}".format(workset.Name),
                "Show this workset in the target view.",
                ACTION_SHOW_WORKSET,
                workset_id
            )
    except Exception:
        view_visibility = None

    try:
        default_visibility = WorksetDefaultVisibilitySettings.GetWorksetDefaultVisibilitySettings(revit_doc)
        if view_visibility == WorksetVisibility.UseGlobalSetting:
            if not default_visibility.IsWorksetVisible(workset_id):
                return CheckResult(
                    "confirmed",
                    "Workset hidden by default visibility",
                    "The element workset is hidden by the model's default workset visibility.",
                    "Workset: {0}".format(workset.Name),
                    "Show this workset in the target view.",
                    ACTION_SHOW_WORKSET,
                    workset_id
                )
    except Exception:
        pass

    try:
        if hasattr(workset, "IsOpen") and not workset.IsOpen:
            return CheckResult(
                "confirmed",
                "Workset is closed",
                "The element workset is closed in this session.",
                "Workset: {0}".format(workset.Name),
                "Open the workset before expecting this element to display."
            )
    except Exception:
        pass

    return CheckResult(
        "passed",
        "Workset is not hidden",
        "The element workset does not appear to be hidden in the target view.",
        "Workset: {0}".format(workset.Name),
        "No correction needed."
    )


def get_parameter_element_id(element, built_in_parameter):
    try:
        parameter = element.get_Parameter(built_in_parameter)
        if parameter and parameter.HasValue:
            return parameter.AsElementId()
    except Exception:
        pass
    return ElementId.InvalidElementId


def get_built_in_parameter(parameter_name):
    try:
        return getattr(BuiltInParameter, parameter_name)
    except Exception:
        return None


def get_phase_order(revit_doc):
    result = {}
    try:
        phases = list(revit_doc.Phases)
        for index, phase in enumerate(phases):
            result[get_element_id_value(phase.Id)] = index
    except Exception:
        pass
    return result


def check_phase(revit_doc, element, target_view):
    view_phase_id = get_parameter_element_id(target_view, BuiltInParameter.VIEW_PHASE)
    phase_filter_id = get_parameter_element_id(target_view, BuiltInParameter.VIEW_PHASE_FILTER)
    created_phase_id = get_parameter_element_id(element, BuiltInParameter.PHASE_CREATED)
    demolished_phase_id = get_parameter_element_id(element, BuiltInParameter.PHASE_DEMOLISHED)

    if not id_is_valid(view_phase_id):
        return CheckResult(
            "possible",
            "Target view phase not available",
            "The target view phase could not be read.",
            "",
            "Open the view phase settings manually."
        )

    phase_order = get_phase_order(revit_doc)
    view_order = phase_order.get(get_element_id_value(view_phase_id))
    created_order = phase_order.get(get_element_id_value(created_phase_id))
    demolished_order = phase_order.get(get_element_id_value(demolished_phase_id))

    view_phase_name = get_name(revit_doc, view_phase_id)
    created_phase_name = get_name(revit_doc, created_phase_id)
    demolished_phase_name = get_name(revit_doc, demolished_phase_id)
    phase_filter_name = get_name(revit_doc, phase_filter_id)

    if view_order is not None and created_order is not None and created_order > view_order:
        return CheckResult(
            "confirmed",
            "Element is created after the view phase",
            "The selected element belongs to a later project phase than the view is showing.",
            "Element was created in '{0}', but the target view is set to '{1}'.".format(
                created_phase_name,
                view_phase_name
            ),
            "Use a view set to the element's phase, or review the target view's Phase setting."
        )

    if view_order is not None and demolished_order is not None and demolished_order <= view_order:
        return CheckResult(
            "possible",
            "Element may be demolished for this view phase",
            "The element demolition phase may affect visibility in this target view.",
            "Demolished: {0}; view phase: {1}; phase filter: {2}".format(
                demolished_phase_name,
                view_phase_name,
                phase_filter_name
            ),
            "Review the view phase and phase filter."
        )

    if id_is_valid(created_phase_id) or id_is_valid(demolished_phase_id):
        return CheckResult(
            "passed",
            "No obvious phase blocker",
            "The element phase data does not show an obvious conflict with the target view phase.",
            "View phase: {0}".format(view_phase_name),
            "No correction needed."
        )

    return CheckResult(
        "possible",
        "Element phase data not available",
        "This element does not expose normal phase-created or phase-demolished parameters.",
        "",
        "Confirm phase behavior manually if the element is still missing."
    )


def check_design_option(revit_doc, element, target_view):
    design_option_parameter = get_built_in_parameter("DESIGN_OPTION_ID")
    view_option_parameter = get_built_in_parameter("VIEWER_OPTION_VISIBILITY")

    if design_option_parameter is None:
        return CheckResult(
            "possible",
            "Could not check design option",
            "This Revit API did not expose the expected design option parameter.",
            "",
            "Review design option settings manually."
        )

    element_option_id = get_parameter_element_id(element, design_option_parameter)
    if not id_is_valid(element_option_id):
        return CheckResult(
            "passed",
            "Element is not in a design option",
            "The element does not appear to belong to a design option.",
            "",
            "No correction needed."
        )

    try:
        if view_option_parameter is None:
            view_option_id = ElementId.InvalidElementId
        else:
            view_option_id = get_parameter_element_id(target_view, view_option_parameter)
    except Exception:
        view_option_id = ElementId.InvalidElementId

    element_option_name = get_name(revit_doc, element_option_id)
    if id_is_valid(view_option_id) and not ids_are_equal(view_option_id, element_option_id):
        return CheckResult(
            "confirmed",
            "Different design option",
            "The element belongs to a different design option than the target view.",
            "Element option: {0}".format(element_option_name),
            "Change the target view design option or inspect an appropriate view."
        )

    return CheckResult(
        "possible",
        "Design option may affect visibility",
        "The element belongs to a design option.",
        "Element option: {0}".format(element_option_name),
        "Confirm the target view design option settings."
    )


def internal_feet_to_mm(value):
    return value * 304.8


def format_mm(value):
    return "{0:.0f} mm".format(internal_feet_to_mm(value))


def get_view_range_plane_elevation(revit_doc, plan_view_range, plane):
    level_id = plan_view_range.GetLevelId(plane)
    offset = plan_view_range.GetOffset(plane)
    level = revit_doc.GetElement(level_id) if id_is_valid(level_id) else None
    if level is None:
        return None
    try:
        return level.Elevation + offset
    except Exception:
        return None


def get_view_range_plane_info(revit_doc, plan_view_range, plane):
    level_id = plan_view_range.GetLevelId(plane)
    offset = plan_view_range.GetOffset(plane)
    level = revit_doc.GetElement(level_id) if id_is_valid(level_id) else None
    if level is None:
        return None

    try:
        return {
            "plane": plane,
            "level_id": level_id,
            "level_elevation": level.Elevation,
            "offset": offset,
            "elevation": level.Elevation + offset,
        }
    except Exception:
        return None


def get_lower_view_range_plane_info(revit_doc, plan_view_range):
    bottom = get_view_range_plane_info(revit_doc, plan_view_range, PlanViewPlane.BottomClipPlane)
    depth = get_view_range_plane_info(revit_doc, plan_view_range, PlanViewPlane.ViewDepthPlane)

    if bottom is None:
        return depth
    if depth is None:
        return bottom
    if depth["elevation"] <= bottom["elevation"]:
        return depth
    return bottom


def make_view_range_action_data(direction, plane_info, previous_offset, new_offset):
    return {
        "direction": direction,
        "plane": plane_info["plane"],
        "previous_offset": previous_offset,
        "new_offset": new_offset,
        "previous_elevation": plane_info["elevation"],
        "new_elevation": plane_info["level_elevation"] + new_offset,
    }


def get_element_location_curve_z_extents(element):
    """Return Z extents from a linear element's placement curve when available."""
    try:
        location = element.Location
    except Exception:
        location = None

    if location is None:
        return None

    try:
        curve = location.Curve
    except Exception:
        curve = None

    if curve is not None:
        try:
            start = curve.GetEndPoint(0)
            end = curve.GetEndPoint(1)
            return min(start.Z, end.Z), max(start.Z, end.Z), "Location line"
        except Exception:
            pass

    return None


def get_element_bounding_box_z_extents(element):
    try:
        element_box = element.get_BoundingBox(None)
    except Exception:
        element_box = None

    if element_box is None:
        return None

    try:
        return element_box.Min.Z, element_box.Max.Z, "Bounding box"
    except Exception:
        return None


def format_optional_mm(value):
    if value is None:
        return "Not available"
    return format_mm(value)


def get_parameter_as_integer(parameter):
    try:
        if parameter and parameter.HasValue:
            return parameter.AsInteger()
    except Exception:
        pass
    return None


def get_parameter_raw_label(parameter):
    value = get_parameter_as_integer(parameter)
    return "None" if value is None else str(value)


def get_parameter_value_label(parameter):
    try:
        if parameter and parameter.HasValue:
            label = parameter.AsValueString()
            if label:
                return label
    except Exception:
        pass
    value = get_parameter_as_integer(parameter)
    if value == DISCIPLINE_ARCHITECTURAL_VALUE:
        return "Architectural"
    if value == DISCIPLINE_COORDINATION_VALUE:
        return "Coordination"
    if value is None:
        return "Unknown"
    return str(value)


def get_category_label(element):
    try:
        if element and element.Category:
            return element.Category.Name
    except Exception:
        pass
    return "None"


def get_view_discipline_enum_value(member_name):
    try:
        import Autodesk.Revit.DB as RevitDB
        view_discipline = getattr(RevitDB, "ViewDiscipline", None)
        if view_discipline is None:
            return None
        enum_value = getattr(view_discipline, member_name)
        return int(enum_value)
    except Exception:
        return None


def get_view_discipline_parameter(target_view):
    discipline_parameter = get_built_in_parameter("VIEW_DISCIPLINE")
    if discipline_parameter is not None:
        try:
            parameter = target_view.get_Parameter(discipline_parameter)
            if parameter is not None:
                return parameter
        except Exception:
            pass

    try:
        return target_view.LookupParameter("Discipline")
    except Exception:
        return None


def get_view_discipline_name(parameter):
    label = get_parameter_value_label(parameter)
    label_lower = label.lower()
    if "architectural" in label_lower:
        return "Architectural"
    if "structural" in label_lower:
        return "Structural"
    if "mechanical" in label_lower:
        return "Mechanical"
    if "electrical" in label_lower:
        return "Electrical"
    if "plumbing" in label_lower:
        return "Plumbing"
    if "coordination" in label_lower:
        return "Coordination"

    value = get_parameter_as_integer(parameter)
    discipline_names = [
        "Architectural",
        "Structural",
        "Mechanical",
        "Electrical",
        "Plumbing",
        "Coordination",
    ]
    for discipline_name in discipline_names:
        enum_value = get_view_discipline_enum_value(discipline_name)
        if enum_value is not None and value == enum_value:
            return discipline_name

    if value == DISCIPLINE_ARCHITECTURAL_VALUE:
        return "Architectural"
    if value == DISCIPLINE_COORDINATION_VALUE:
        return "Coordination"
    return "Unknown"


def get_category_id_value(element):
    try:
        if element and element.Category:
            return get_element_id_value(element.Category.Id)
    except Exception:
        pass
    return None


def get_element_class_label(element):
    try:
        return element.GetType().Name
    except Exception:
        try:
            return element.__class__.__name__
        except Exception:
            return "Unknown"


def get_built_in_category_value(category_name):
    try:
        return int(getattr(BuiltInCategory, category_name))
    except Exception:
        try:
            return get_element_id_value(ElementId(getattr(BuiltInCategory, category_name)))
        except Exception:
            return None


MEP_DISCIPLINE_SENSITIVE_BIC_NAMES = [
    "OST_DuctCurves",
    "OST_FlexDuctCurves",
    "OST_DuctFitting",
    "OST_DuctAccessory",
    "OST_DuctTerminal",
    "OST_MechanicalEquipment",
    "OST_MechanicalControlDevices",
    "OST_DuctSystem",
    "OST_DuctInsulations",
    "OST_DuctLinings",
    "OST_FabricationDuctwork",
    "OST_FabricationContainment",
    "OST_FabricationHangers",
    "OST_PipeCurves",
    "OST_FlexPipeCurves",
    "OST_PipeFitting",
    "OST_PipeAccessory",
    "OST_PlumbingFixtures",
    "OST_PlumbingEquipment",
    "OST_Sprinklers",
    "OST_PipingSystem",
    "OST_PipeInsulations",
    "OST_PlaceHolderPipes",
    "OST_FabricationPipework",
    "OST_CableTray",
    "OST_CableTrayFitting",
    "OST_Conduit",
    "OST_ConduitFitting",
    "OST_ElectricalEquipment",
    "OST_ElectricalFixtures",
    "OST_LightingFixtures",
    "OST_LightingDevices",
    "OST_FireAlarmDevices",
    "OST_DataDevices",
    "OST_CommunicationDevices",
    "OST_SecurityDevices",
    "OST_TelephoneDevices",
    "OST_NurseCallDevices",
    "OST_ElectricalCircuit",
    "OST_ElectricalInternalCircuits",
]

MEP_DISCIPLINE_SENSITIVE_CATEGORY_NAMES = set([
    "ducts",
    "flex ducts",
    "duct fittings",
    "duct accessories",
    "air terminals",
    "mechanical equipment",
    "mechanical control devices",
    "duct systems",
    "duct insulations",
    "duct linings",
    "mep fabrication ductwork",
    "mep fabrication hangers",
    "pipes",
    "flex pipes",
    "pipe fittings",
    "pipe accessories",
    "pipe placeholders",
    "plumbing fixtures",
    "plumbing equipment",
    "sprinklers",
    "piping systems",
    "pipe insulations",
    "mep fabrication pipework",
    "cable trays",
    "cable tray fittings",
    "conduits",
    "conduit fittings",
    "electrical equipment",
    "electrical fixtures",
    "lighting fixtures",
    "lighting devices",
    "fire alarm devices",
    "data devices",
    "communication devices",
    "security devices",
    "telephone devices",
    "nurse call devices",
    "electrical circuits",
    "electrical spare/space circuits",
    "switch systems",
])

MEP_DISCIPLINE_TARGET_VIEW_TYPES = set([
    ViewType.FloorPlan,
    ViewType.CeilingPlan,
    ViewType.EngineeringPlan,
])


def is_plan_view_with_view_range(target_view):
    if not isinstance(target_view, ViewPlan):
        return False
    try:
        return target_view.ViewType in MEP_DISCIPLINE_TARGET_VIEW_TYPES
    except Exception:
        return False


def is_mep_discipline_sensitive_category(element, revit_doc=None):
    category_id = get_category_id_value(element)
    if category_id is not None:
        for bic_name in MEP_DISCIPLINE_SENSITIVE_BIC_NAMES:
            bic_value = get_built_in_category_value(bic_name)
            if bic_value is not None and category_id == bic_value:
                return {
                    "is_mep": True,
                    "confidence": "inferred / strong",
                    "source": "BuiltInCategory {0}".format(bic_name),
                }

    try:
        category_name = element.Category.Name.strip().lower() if element.Category else ""
    except Exception:
        category_name = ""

    if category_name in MEP_DISCIPLINE_SENSITIVE_CATEGORY_NAMES:
        return {
            "is_mep": True,
            "confidence": "inferred / medium",
            "source": "Category name '{0}'".format(get_category_label(element)),
        }

    return {
        "is_mep": False,
        "confidence": "not matched",
        "source": "Category is not in the supported MEP category list",
    }


def get_box_z_extents_with_transform(box):
    try:
        transform = box.Transform
    except Exception:
        transform = None

    z_values = []
    for corner in get_bbox_corners(box):
        try:
            point = transform.OfPoint(corner) if transform else corner
            z_values.append(point.Z)
        except Exception:
            pass
    if not z_values:
        return None
    return min(z_values), max(z_values)


def collect_geometry_z_values(geometry_element, z_values):
    if geometry_element is None:
        return

    for geometry_object in geometry_element:
        try:
            box = geometry_object.GetBoundingBox()
        except Exception:
            box = None
        if box is not None:
            extents = get_box_z_extents_with_transform(box)
            if extents:
                z_values.append(extents[0])
                z_values.append(extents[1])

        try:
            instance_geometry = geometry_object.GetInstanceGeometry()
        except Exception:
            instance_geometry = None
        if instance_geometry is not None:
            collect_geometry_z_values(instance_geometry, z_values)


def get_element_geometry_z_extents(element):
    try:
        options = Options()
        options.IncludeNonVisibleObjects = False
        geometry = element.get_Geometry(options)
    except Exception:
        geometry = None

    z_values = []
    try:
        collect_geometry_z_values(geometry, z_values)
    except Exception:
        return None

    if z_values:
        return min(z_values), max(z_values), "Geometry", "calculated"
    return None


def get_element_z_extents_for_mep_discipline(element):
    box_extents = get_element_bounding_box_z_extents(element)
    if box_extents:
        min_z, max_z, source = box_extents
        return {
            "has_valid_extents": True,
            "min_z": min_z,
            "max_z": max_z,
            "source": source,
            "confidence": "calculated",
        }

    geometry_extents = get_element_geometry_z_extents(element)
    if geometry_extents:
        min_z, max_z, source, confidence = geometry_extents
        return {
            "has_valid_extents": True,
            "min_z": min_z,
            "max_z": max_z,
            "source": source,
            "confidence": confidence,
        }

    curve_extents = get_element_location_curve_z_extents(element)
    if curve_extents:
        min_z, max_z, source = curve_extents
        return {
            "has_valid_extents": True,
            "min_z": min_z,
            "max_z": max_z,
            "source": source,
            "confidence": "approximate",
        }

    return {
        "has_valid_extents": False,
        "min_z": None,
        "max_z": None,
        "source": "Not available",
        "confidence": "unknown",
    }


def get_view_range_absolute_planes(revit_doc, target_view):
    if not is_plan_view_with_view_range(target_view):
        return None

    try:
        view_range = target_view.GetViewRange()
    except Exception:
        return None

    top_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.TopClipPlane)
    cut_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.CutPlane)
    bottom_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.BottomClipPlane)
    depth_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.ViewDepthPlane)

    if top_info is None or cut_info is None:
        return None

    return {
        "top": top_info,
        "cut": cut_info,
        "bottom": bottom_info,
        "depth": depth_info,
    }


def classify_vertical_position(min_z, max_z, cut_z, top_z, bottom_z, view_depth_z, tolerance):
    if min_z is None or max_z is None or cut_z is None or top_z is None:
        return "unknown"
    if min_z > top_z + tolerance:
        return "above_top"
    if max_z > top_z + tolerance:
        return "partially_above_top"
    if min_z > cut_z + tolerance and max_z <= top_z + tolerance:
        return "entirely_above_cut_inside_top"
    if min_z <= cut_z + tolerance and max_z >= cut_z - tolerance:
        return "intersects_cut"
    if view_depth_z is not None and max_z < view_depth_z - tolerance:
        return "below_view_depth"
    if bottom_z is not None and max_z < bottom_z - tolerance:
        return "below_bottom"
    if max_z < cut_z - tolerance:
        return "entirely_below_cut"
    return "unknown"


def make_mep_above_cut_evidence(target_view, element, discipline_parameter, mep_info, z_info, planes, vertical_case):
    discipline_label = get_parameter_value_label(discipline_parameter) if discipline_parameter else "Not available"
    discipline_raw = get_parameter_raw_label(discipline_parameter) if discipline_parameter else "None"
    category_name = get_category_label(element)
    category_id = get_category_id_value(element)
    category_id_label = "None" if category_id is None else str(category_id)
    element_class = get_element_class_label(element)

    if z_info and z_info.get("has_valid_extents"):
        element_min = format_mm(z_info.get("min_z"))
        element_max = format_mm(z_info.get("max_z"))
        elevation_source = z_info.get("source", "Unknown")
        z_confidence = z_info.get("confidence", "unknown")
    else:
        element_min = "Not available"
        element_max = "Not available"
        elevation_source = "Not available"
        z_confidence = "unknown"

    cut_info = planes.get("cut") if planes else None
    top_info = planes.get("top") if planes else None

    return "; ".join([
        "Target view type: {0}".format(target_view.ViewType),
        "View discipline: {0} (raw: {1})".format(discipline_label, discipline_raw),
        "Element category: {0} (id: {1})".format(category_name, category_id_label),
        "Element class: {0}".format(element_class),
        "MEP category match: {0}".format(mep_info.get("source", "Unknown")),
        "MEP confidence: {0}".format(mep_info.get("confidence", "unknown")),
        "Element min elevation: {0}".format(element_min),
        "Element max elevation: {0}".format(element_max),
        "Elevation source: {0} ({1})".format(elevation_source, z_confidence),
        "Cut Plane elevation: {0}".format(format_optional_mm(cut_info["elevation"]) if cut_info else "Not available"),
        "Top Plane elevation: {0}".format(format_optional_mm(top_info["elevation"]) if top_info else "Not available"),
        "Vertical case: {0}".format(vertical_case),
        "Inference: Revit API does not expose a direct hidden-by-View-Discipline reason",
    ])


def check_mep_above_cut_plane_discipline_issue(revit_doc, element, target_view):
    discipline_parameter = get_view_discipline_parameter(target_view)

    if not is_plan_view_with_view_range(target_view):
        return CheckResult(
            "passed",
            "MEP above-cut discipline check does not apply",
            "The target view is not a plan view where Plan View Range is relevant.",
            "View type: {0}".format(target_view.ViewType),
            "No correction needed."
        )

    mep_info = is_mep_discipline_sensitive_category(element, revit_doc)
    if not mep_info.get("is_mep"):
        return CheckResult(
            "passed",
            "MEP above-cut discipline check does not apply",
            "The selected element is not in a supported MEP discipline-sensitive category.",
            "Element category: {0}; category match: {1}".format(get_category_label(element), mep_info.get("source")),
            "No correction needed."
        )

    planes = get_view_range_absolute_planes(revit_doc, target_view)
    if planes is None:
        return CheckResult(
            "possible",
            "Could not check MEP above-cut condition",
            "Revit did not return a usable Plan View Range with Cut Plane and Top Plane elevations.",
            "Element category: {0}; MEP match: {1}".format(get_category_label(element), mep_info.get("source")),
            "Review View Range and View Discipline manually."
        )

    z_info = get_element_z_extents_for_mep_discipline(element)
    if not z_info.get("has_valid_extents"):
        return CheckResult(
            "possible",
            "Could not check MEP above-cut condition",
            "Revit did not return usable element vertical extents.",
            make_mep_above_cut_evidence(target_view, element, discipline_parameter, mep_info, z_info, planes, "unknown"),
            "Review View Range, View Discipline, and the element elevation manually."
        )

    bottom_info = planes.get("bottom")
    depth_info = planes.get("depth")
    bottom_z = bottom_info["elevation"] if bottom_info else None
    depth_z = depth_info["elevation"] if depth_info else None
    vertical_case = classify_vertical_position(
        z_info.get("min_z"),
        z_info.get("max_z"),
        planes["cut"]["elevation"],
        planes["top"]["elevation"],
        bottom_z,
        depth_z,
        ELEVATION_TOLERANCE_FEET
    )
    evidence = make_mep_above_cut_evidence(target_view, element, discipline_parameter, mep_info, z_info, planes, vertical_case)

    if vertical_case == "above_top":
        return CheckResult(
            "passed",
            "MEP above-cut discipline check does not apply",
            "The element is above the Top Plane, so the ordinary View Range check should explain this condition.",
            evidence,
            "No correction needed."
        )

    if vertical_case != "entirely_above_cut_inside_top":
        return CheckResult(
            "passed",
            "MEP element is not entirely above the Cut Plane",
            "The element does not sit entirely above the Cut Plane while remaining below the Top Plane.",
            evidence,
            "No correction needed."
        )

    discipline_name = get_view_discipline_name(discipline_parameter)

    if discipline_name in ["Architectural", "Structural"]:
        return CheckResult(
            "possible",
            "Above Cut Plane in {0} View".format(discipline_name),
            "Likely discipline-dependent visibility condition. The element lies above the view's Cut Plane but below its Top Plane. At this position, visibility of MEP elements can depend on the view discipline. This result is inferred from category, vertical extents, view range, and discipline; the Revit API does not directly report a \"hidden by View Discipline\" reason.",
            evidence,
            "Review View Discipline and View Range. Use an appropriate MEP or Coordination view, consider a Plan Region where appropriate, and check whether the element elevation is correct."
        )

    if discipline_name in ["Mechanical", "Electrical", "Plumbing", "Coordination"]:
        return CheckResult(
            "passed",
            "Above Cut Plane - Discipline Usually Allows MEP Display",
            "The element is above the Cut Plane, but this position alone does not normally explain invisibility in a {0} view. Continue checking other visibility conditions.".format(discipline_name),
            evidence,
            "No correction needed."
        )

    return CheckResult(
        "possible",
        "Above Cut Plane with Unknown View Discipline",
        "The element is above the Cut Plane and below the Top Plane, but the target view Discipline could not be classified safely.",
        evidence,
        "Review the target view Discipline manually."
    )


def check_plan_view_range(revit_doc, element, target_view):
    if not isinstance(target_view, ViewPlan):
        return CheckResult(
            "passed",
            "View range does not apply",
            "The target view is not a plan view with a normal view range.",
            "View type: {0}".format(target_view.ViewType),
            "No correction needed."
        )

    try:
        element_box = element.get_BoundingBox(None)
    except Exception:
        element_box = None

    if element_box is None:
        return CheckResult(
            "possible",
            "Could not check view range",
            "Revit did not return a model bounding box for this element.",
            "",
            "Open View Range and compare it manually."
        )

    try:
        view_range = target_view.GetViewRange()
        top_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.TopClipPlane)
        bottom_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.BottomClipPlane)
        depth_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.ViewDepthPlane)
        top_elevation = top_info["elevation"] if top_info else None
        bottom_elevation = bottom_info["elevation"] if bottom_info else None
        depth_elevation = depth_info["elevation"] if depth_info else None
    except Exception as err:
        return CheckResult(
            "possible",
            "Could not check view range",
            "Revit could not read the target view range.",
            str(err),
            "Open View Range and compare it manually."
        )

    lower_candidates = []
    if bottom_elevation is not None:
        lower_candidates.append(bottom_elevation)
    if depth_elevation is not None:
        lower_candidates.append(depth_elevation)
    lower_elevation = min(lower_candidates) if lower_candidates else None

    evidence_parts = [
        "Element min: {0}".format(format_mm(element_box.Min.Z)),
        "Element max: {0}".format(format_mm(element_box.Max.Z)),
    ]
    location_z_extents = get_element_location_curve_z_extents(element)
    if location_z_extents:
        location_min_z, location_max_z, location_label = location_z_extents
        evidence_parts.append("{0} min: {1}".format(location_label, format_mm(location_min_z)))
        evidence_parts.append("{0} max: {1}".format(location_label, format_mm(location_max_z)))
    else:
        location_min_z = None
        location_max_z = None
        location_label = None
    if top_elevation is not None:
        evidence_parts.append("View top: {0}".format(format_mm(top_elevation)))
    if lower_elevation is not None:
        evidence_parts.append("View lower/depth: {0}".format(format_mm(lower_elevation)))
    evidence = "; ".join(evidence_parts)

    if location_label and top_elevation is not None and location_min_z > top_elevation:
        return CheckResult(
            "confirmed",
            "Outside view range",
            "The element's {0} is above the target plan view's top plane.".format(location_label.lower()),
            evidence,
            "Adjust the target view range to include the element.",
            ACTION_ADJUST_VIEW_RANGE,
            {"direction": "raise_top"}
        )

    if location_label and lower_elevation is not None and location_max_z < lower_elevation:
        return CheckResult(
            "confirmed",
            "Outside view range",
            "The element's {0} is below the target plan view's lower view range.".format(location_label.lower()),
            evidence,
            "Adjust the target view range to include the element.",
            ACTION_ADJUST_VIEW_RANGE,
            {"direction": "lower_range"}
        )

    if top_elevation is not None and element_box.Min.Z > top_elevation:
        return CheckResult(
            "confirmed",
            "Outside view range",
            "The element is above the target plan view's top plane.",
            evidence,
            "Adjust the target view range to include the element.",
            ACTION_ADJUST_VIEW_RANGE,
            {"direction": "raise_top"}
        )

    if lower_elevation is not None and element_box.Max.Z < lower_elevation:
        return CheckResult(
            "confirmed",
            "Outside view range",
            "The element is below the target plan view's lower view range.",
            evidence,
            "Adjust the target view range to include the element.",
            ACTION_ADJUST_VIEW_RANGE,
            {"direction": "lower_range"}
        )

    if top_elevation is None or lower_elevation is None:
        return CheckResult(
            "possible",
            "View range may affect visibility",
            "The target view range could only be partially read.",
            evidence,
            "Open View Range and confirm the top, bottom, and view depth settings."
        )

    return CheckResult(
        "passed",
        "Inside view range",
        "The element vertical extents intersect the target plan view range.",
        evidence,
        "No correction needed."
    )


def get_bbox_corners(box):
    return [
        XYZ(box.Min.X, box.Min.Y, box.Min.Z),
        XYZ(box.Min.X, box.Min.Y, box.Max.Z),
        XYZ(box.Min.X, box.Max.Y, box.Min.Z),
        XYZ(box.Min.X, box.Max.Y, box.Max.Z),
        XYZ(box.Max.X, box.Min.Y, box.Min.Z),
        XYZ(box.Max.X, box.Min.Y, box.Max.Z),
        XYZ(box.Max.X, box.Max.Y, box.Min.Z),
        XYZ(box.Max.X, box.Max.Y, box.Max.Z),
    ]


def boxes_intersect(model_box, view_box):
    try:
        inverse = view_box.Transform.Inverse
    except Exception:
        inverse = None

    xs = []
    ys = []
    zs = []
    for corner in get_bbox_corners(model_box):
        point = inverse.OfPoint(corner) if inverse else corner
        xs.append(point.X)
        ys.append(point.Y)
        zs.append(point.Z)

    model_min = XYZ(min(xs), min(ys), min(zs))
    model_max = XYZ(max(xs), max(ys), max(zs))
    if model_max.X < view_box.Min.X or model_min.X > view_box.Max.X:
        return False
    if model_max.Y < view_box.Min.Y or model_min.Y > view_box.Max.Y:
        return False
    if model_max.Z < view_box.Min.Z or model_min.Z > view_box.Max.Z:
        return False
    return True


def get_box_points_in_box_space(model_box, target_box):
    try:
        inverse = target_box.Transform.Inverse
    except Exception:
        inverse = None

    points = []
    for corner in get_bbox_corners(model_box):
        points.append(inverse.OfPoint(corner) if inverse else corner)
    return points


def get_points_extents(points):
    xs = [point.X for point in points]
    ys = [point.Y for point in points]
    zs = [point.Z for point in points]
    return XYZ(min(xs), min(ys), min(zs)), XYZ(max(xs), max(ys), max(zs))


def check_crop_or_section_box(element, target_view):
    try:
        element_box = element.get_BoundingBox(None)
    except Exception:
        element_box = None

    if element_box is None:
        return CheckResult(
            "possible",
            "Element bounding box not available",
            "Revit did not return a model bounding box for this element.",
            "",
            "Try opening the target view and using Zoom to Selection."
        )

    if isinstance(target_view, View3D):
        try:
            if target_view.IsSectionBoxActive:
                section_box = target_view.GetSectionBox()
                if not boxes_intersect(element_box, section_box):
                    return CheckResult(
                        "confirmed",
                        "Outside the 3D section box",
                        "The element bounding box is outside the target view section box.",
                        "Target view: {0}".format(target_view.Name),
                        "Adjust the 3D section box."
                    )
                return CheckResult(
                    "passed",
                    "Inside the 3D section box",
                    "The element bounding box intersects the target view section box.",
                    "Target view: {0}".format(target_view.Name),
                    "No correction needed."
                )
        except Exception as err:
            return CheckResult(
                "possible",
                "Could not check 3D section box",
                "Revit could not compare the element with the section box.",
                str(err),
                "Review the section box manually."
            )

    try:
        if hasattr(target_view, "CropBoxActive") and target_view.CropBoxActive:
            crop_box = target_view.CropBox
            if not boxes_intersect(element_box, crop_box):
                return CheckResult(
                    "confirmed",
                    "Outside the crop region",
                    "The element bounding box is outside the target view crop region.",
                    "Target view: {0}".format(target_view.Name),
                    "Expand the target view crop boundary so it includes the selected element with a 300 mm margin. This may reveal more of the model in this view.",
                    ACTION_EXPAND_CROP_REGION
                )
            return CheckResult(
                "passed",
                "Inside the crop region",
                "The element bounding box intersects the target view crop region.",
                "Target view: {0}".format(target_view.Name),
                "No correction needed."
            )
    except Exception as err:
        return CheckResult(
            "possible",
            "Could not check crop region",
            "Revit could not compare the element with the crop region.",
            str(err),
            "Review the crop region manually."
        )

    return CheckResult(
        "passed",
        "No active crop or section blocker found",
        "The target view has no active crop or section condition that obviously excludes the element.",
        "",
        "No correction needed."
    )


def check_view_specific(revit_doc, element, target_view):
    try:
        owner_view_id = element.OwnerViewId
    except Exception:
        owner_view_id = ElementId.InvalidElementId

    if not id_is_valid(owner_view_id):
        return CheckResult(
            "passed",
            "Element can appear in other views",
            "This is a model element, not a view-only annotation or detail item.",
            "",
            "No correction needed."
        )

    if ids_are_equal(owner_view_id, target_view.Id):
        return CheckResult(
            "passed",
            "Element belongs to the target view",
            "This view-only annotation or detail item belongs to the target view.",
            "Owner view: {0}".format(target_view.Name),
            "No correction needed."
        )

    return CheckResult(
        "confirmed",
        "Element belongs to another view",
        "This view-only annotation or detail item belongs to another view.",
        "Owner view: {0}".format(get_name(revit_doc, owner_view_id)),
        "Use the owner view or recreate the annotation/detail item in the target view."
    )


def analyze_visibility(revit_doc, element, target_view):
    results = []
    results.append(check_view_specific(revit_doc, element, target_view))
    results.append(check_element_hidden(element, target_view))
    results.append(check_category_hidden(element, target_view))
    results.extend(check_view_filters(revit_doc, element, target_view))
    results.append(check_workset(revit_doc, element, target_view))
    results.append(check_phase(revit_doc, element, target_view))
    results.append(check_design_option(revit_doc, element, target_view))
    results.append(check_plan_view_range(revit_doc, element, target_view))
    results.append(check_mep_above_cut_plane_discipline_issue(revit_doc, element, target_view))
    results.append(check_crop_or_section_box(element, target_view))
    return results


# -----------------------------------------------------------------------------
# Fix actions
# -----------------------------------------------------------------------------

def unhide_element(revit_doc, element, target_view):
    def action():
        element_ids = get_element_and_dependent_ids(element)
        target_view.UnhideElements(make_id_list_from_ids(element_ids))
        for element_id in element_ids:
            try:
                target_view.SetElementOverrides(element_id, OverrideGraphicSettings())
            except Exception:
                pass
        revit_doc.Regenerate()
        return True

    result = run_in_transaction(revit_doc, "Why Not Here - Unhide Element", action)
    clear_selection()
    activate_target_view(target_view)
    refresh_active_view()
    return result


def undo_unhide_element(revit_doc, element, target_view):
    def action():
        target_view.HideElements(make_id_list_from_ids(get_element_and_dependent_ids(element)))
        revit_doc.Regenerate()
        return True

    result = run_in_transaction(revit_doc, "Why Not Here - Undo Unhide Element", action)
    refresh_active_view()
    return result


def show_category(revit_doc, category_id, target_view):
    def action():
        target_view.SetCategoryHidden(category_id, False)
        return True
    result = run_in_transaction(revit_doc, "Why Not Here - Show Category", action)
    activate_target_view(target_view)
    refresh_active_view()
    return result


def undo_show_category(revit_doc, category_id, target_view):
    def action():
        target_view.SetCategoryHidden(category_id, True)
        return True
    return run_in_transaction(revit_doc, "Why Not Here - Undo Show Category", action)


def show_filter(revit_doc, filter_id, target_view):
    def action():
        target_view.SetFilterVisibility(filter_id, True)
        return True
    result = run_in_transaction(revit_doc, "Why Not Here - Show Filter", action)
    activate_target_view(target_view)
    refresh_active_view()
    return result


def undo_show_filter(revit_doc, filter_id, target_view):
    def action():
        target_view.SetFilterVisibility(filter_id, False)
        return True
    return run_in_transaction(revit_doc, "Why Not Here - Undo Show Filter", action)


def show_workset(revit_doc, workset_id, target_view):
    def action():
        target_view.SetWorksetVisibility(workset_id, WorksetVisibility.Visible)
        return True
    result = run_in_transaction(revit_doc, "Why Not Here - Show Workset", action)
    activate_target_view(target_view)
    refresh_active_view()
    return result


def undo_show_workset(revit_doc, workset_id, target_view):
    def action():
        target_view.SetWorksetVisibility(workset_id, WorksetVisibility.Hidden)
        return True
    return run_in_transaction(revit_doc, "Why Not Here - Undo Show Workset", action)


def adjust_view_range_to_element(revit_doc, element, target_view, result):
    if not isinstance(target_view, ViewPlan):
        raise Exception("Target view is not a plan view.")

    direction = ""
    if result and result.action_data:
        direction = result.action_data.get("direction", "")

    try:
        element_box = element.get_BoundingBox(None)
    except Exception:
        element_box = None
    if element_box is None:
        raise Exception("Revit did not return a model bounding box for this element.")

    undo_data = {}

    def action():
        view_range = target_view.GetViewRange()

        if direction == "raise_top":
            plane_info = get_view_range_plane_info(revit_doc, view_range, PlanViewPlane.TopClipPlane)
            if plane_info is None:
                raise Exception("Could not read the target view top plane.")
            required_elevation = element_box.Max.Z + VIEW_RANGE_CLEARANCE_FEET
            if required_elevation <= plane_info["elevation"]:
                return "View top already includes the element."

        elif direction == "lower_range":
            plane_info = get_lower_view_range_plane_info(revit_doc, view_range)
            if plane_info is None:
                raise Exception("Could not read the target view lower or depth plane.")
            required_elevation = element_box.Min.Z - VIEW_RANGE_CLEARANCE_FEET
            if required_elevation >= plane_info["elevation"]:
                return "View lower range already includes the element."

        else:
            raise Exception("Unknown view range adjustment direction.")

        previous_offset = plane_info["offset"]
        new_offset = required_elevation - plane_info["level_elevation"]
        view_range.SetOffset(plane_info["plane"], new_offset)
        target_view.SetViewRange(view_range)

        undo_data.update(make_view_range_action_data(
            direction,
            plane_info,
            previous_offset,
            new_offset
        ))
        return "Changed view range from {0} to {1}.".format(
            format_mm(plane_info["elevation"]),
            format_mm(required_elevation)
        )

    message = run_in_transaction(revit_doc, "Why Not Here - Adjust View Range", action)
    if undo_data:
        result.action_data = undo_data
    activate_target_view(target_view)
    refresh_active_view()
    return message


def undo_adjust_view_range(revit_doc, target_view, action_data):
    if not isinstance(target_view, ViewPlan):
        raise Exception("Target view is not a plan view.")
    if not action_data or "plane" not in action_data:
        raise Exception("No previous view range value was recorded.")

    def action():
        view_range = target_view.GetViewRange()
        view_range.SetOffset(action_data["plane"], action_data["previous_offset"])
        target_view.SetViewRange(view_range)
        return True

    result = run_in_transaction(revit_doc, "Why Not Here - Undo View Range", action)
    activate_target_view(target_view)
    refresh_active_view()
    return result


def expand_crop_to_element(revit_doc, element, target_view, result):
    if isinstance(target_view, View3D):
        raise Exception("This crop fix is only for 2D target views.")
    if not hasattr(target_view, "CropBoxActive") or not target_view.CropBoxActive:
        raise Exception("The target view does not have an active crop region.")

    try:
        element_box = element.get_BoundingBox(None)
    except Exception:
        element_box = None
    if element_box is None:
        raise Exception("Revit did not return a model bounding box for this element.")

    undo_data = {}

    def action():
        crop_box = target_view.CropBox
        previous_min = XYZ(crop_box.Min.X, crop_box.Min.Y, crop_box.Min.Z)
        previous_max = XYZ(crop_box.Max.X, crop_box.Max.Y, crop_box.Max.Z)

        element_points = get_box_points_in_box_space(element_box, crop_box)
        element_min, element_max = get_points_extents(element_points)

        new_min = XYZ(
            min(crop_box.Min.X, element_min.X - CROP_CLEARANCE_FEET),
            min(crop_box.Min.Y, element_min.Y - CROP_CLEARANCE_FEET),
            min(crop_box.Min.Z, element_min.Z - CROP_CLEARANCE_FEET)
        )
        new_max = XYZ(
            max(crop_box.Max.X, element_max.X + CROP_CLEARANCE_FEET),
            max(crop_box.Max.Y, element_max.Y + CROP_CLEARANCE_FEET),
            max(crop_box.Max.Z, element_max.Z + CROP_CLEARANCE_FEET)
        )

        if (
            new_min.X == crop_box.Min.X and
            new_min.Y == crop_box.Min.Y and
            new_min.Z == crop_box.Min.Z and
            new_max.X == crop_box.Max.X and
            new_max.Y == crop_box.Max.Y and
            new_max.Z == crop_box.Max.Z
        ):
            return "The crop already includes the selected element."

        crop_box.Min = new_min
        crop_box.Max = new_max
        target_view.CropBox = crop_box

        undo_data.update({
            "previous_min": previous_min,
            "previous_max": previous_max,
        })
        return "Expanded the crop boundary to include the selected element with a {0:.0f} mm margin.".format(CROP_CLEARANCE_MM)

    message = run_in_transaction(revit_doc, "Why Not Here - Expand Crop Region", action)
    if undo_data:
        result.action_data = undo_data
    activate_target_view(target_view)
    refresh_active_view()
    return message


def undo_expand_crop_region(revit_doc, target_view, action_data):
    if not action_data or "previous_min" not in action_data or "previous_max" not in action_data:
        raise Exception("No previous crop boundary was recorded.")

    def action():
        crop_box = target_view.CropBox
        crop_box.Min = action_data["previous_min"]
        crop_box.Max = action_data["previous_max"]
        target_view.CropBox = crop_box
        return True

    result = run_in_transaction(revit_doc, "Why Not Here - Undo Crop Region", action)
    activate_target_view(target_view)
    refresh_active_view()
    return result


FIX_ACTIONS = {
    ACTION_UNHIDE_ELEMENT: (
        lambda window, result: unhide_element(window.revit_doc, window.element, window.target_view),
        "The element and safe dependent ids are now unhidden in this view."
    ),
    ACTION_SHOW_CATEGORY: (
        lambda window, result: show_category(window.revit_doc, result.action_data, window.target_view),
        "The category is now visible in this view."
    ),
    ACTION_SHOW_FILTER: (
        lambda window, result: show_filter(window.revit_doc, result.action_data, window.target_view),
        "The matching view filter is now visible in this view."
    ),
    ACTION_SHOW_WORKSET: (
        lambda window, result: show_workset(window.revit_doc, result.action_data, window.target_view),
        "The workset is now visible in this view."
    ),
    ACTION_ADJUST_VIEW_RANGE: (
        lambda window, result: adjust_view_range_to_element(window.revit_doc, window.element, window.target_view, result),
        "The view range was adjusted by the smallest required offset to include the element."
    ),
    ACTION_EXPAND_CROP_REGION: (
        lambda window, result: expand_crop_to_element(window.revit_doc, window.element, window.target_view, result),
        "The crop boundary was expanded to include the selected element."
    ),
}

UNDO_ACTIONS = {
    ACTION_UNHIDE_ELEMENT: lambda window, result: undo_unhide_element(window.revit_doc, window.element, window.target_view),
    ACTION_SHOW_CATEGORY: lambda window, result: undo_show_category(window.revit_doc, result.action_data, window.target_view),
    ACTION_SHOW_FILTER: lambda window, result: undo_show_filter(window.revit_doc, result.action_data, window.target_view),
    ACTION_SHOW_WORKSET: lambda window, result: undo_show_workset(window.revit_doc, result.action_data, window.target_view),
    ACTION_ADJUST_VIEW_RANGE: lambda window, result: undo_adjust_view_range(window.revit_doc, window.target_view, result.action_data),
    ACTION_EXPAND_CROP_REGION: lambda window, result: undo_expand_crop_region(window.revit_doc, window.target_view, result.action_data),
}


def close_output_window():
    try:
        if output is not None:
            output.close()
    except Exception:
        pass


def result_matches(first, second):
    if first.action_name or second.action_name:
        return first.action_name == second.action_name and str(first.action_data) == str(second.action_data)
    return first.group == second.group and first.title == second.title


class WhyNotHereRequest(object):
    def __init__(self, action, result=None, callback=None):
        self.action = action
        self.result = result
        self.callback = callback


# -----------------------------------------------------------------------------
# External event handler
# -----------------------------------------------------------------------------

class WhyNotHereExternalHandler(IExternalEventHandler):
    ANALYZE = "analyze"
    FIX = "fix"
    UNDO = "undo"

    def __init__(self):
        self._queue = deque()
        self.window = None
        self.ui_dispatcher = None
        self.is_closed = False

    def enqueue(self, request):
        if self.is_closed:
            return
        self._queue.append(request)

    def clear(self):
        try:
            while self._queue:
                self._queue.popleft()
        except Exception:
            pass

    def Execute(self, uiapp):
        while self._queue:
            request = self._queue.popleft()
            self._execute_request(uiapp, request)

    def _execute_request(self, uiapp, request):
        if self.window is None:
            return

        try:
            if request.action == self.ANALYZE:
                results = analyze_visibility(
                    self.window.revit_doc,
                    self.window.element,
                    self.window.target_view
                )
                self._done(
                    request,
                    "Analysis complete. Make manual Revit changes if needed, then click Recheck.",
                    False,
                    {"results": results}
                )

            elif request.action == self.FIX:
                fixed_result, rechecked = self._execute_fix(request.result)
                self._done(
                    request,
                    "Fix applied. Rechecked visibility conditions.",
                    False,
                    {
                        "fixed_result": fixed_result,
                        "results": rechecked
                    }
                )

            elif request.action == self.UNDO:
                rechecked = self._execute_undo(request.result)
                self._done(
                    request,
                    "Undo applied. Rechecked visibility conditions.",
                    False,
                    {"results": rechecked}
                )

        except Exception as err:
            logger.error("External event failed in {0}: {1}".format(TOOL_NAME, err))
            logger.debug(traceback.format_exc())
            self._done(request, "Action failed: {0}".format(err), True, None)

    def _execute_fix(self, result):
        if result is None or not result.action_name:
            return result, analyze_visibility(
                self.window.revit_doc,
                self.window.element,
                self.window.target_view
            )

        fix_entry = FIX_ACTIONS.get(result.action_name)
        if fix_entry:
            fix_func, fix_message = fix_entry
            fix_result = fix_func(self.window, result)
            result.fix_message = fix_result if isinstance(fix_result, str) else fix_message

        result.fixed = True
        rechecked = analyze_visibility(
            self.window.revit_doc,
            self.window.element,
            self.window.target_view
        )
        return result, rechecked

    def _execute_undo(self, result):
        if result is None:
            return analyze_visibility(
                self.window.revit_doc,
                self.window.element,
                self.window.target_view
            )

        undo_func = UNDO_ACTIONS.get(result.action_name)
        if undo_func:
            undo_func(self.window, result)

        return analyze_visibility(
            self.window.revit_doc,
            self.window.element,
            self.window.target_view
        )

    def _done(self, request, msg, is_error=False, payload=None):
        if self.is_closed or not request.callback:
            return

        def call_callback():
            try:
                request.callback(request.action, msg, is_error, payload)
            except Exception as err:
                logger.error("Callback failed in {0}: {1}".format(TOOL_NAME, err))
                logger.debug(traceback.format_exc())

        try:
            if self.ui_dispatcher:
                self.ui_dispatcher.BeginInvoke(System.Action(call_callback))
            else:
                call_callback()
        except Exception:
            pass

    def GetName(self):
        return "Why Not Here External Event"


# -----------------------------------------------------------------------------
# WPF window
# -----------------------------------------------------------------------------

class WhyNotHereWindow(forms.WPFWindow):
    def __init__(self, revit_doc, element, external_event, external_handler):
        self.revit_doc = revit_doc
        self.element = element
        self.target_views = collect_target_views(revit_doc)
        self.target_view = None
        self.results = []
        self.external_event = external_event
        self.external_handler = external_handler
        self.external_handler.window = self

        forms.WPFWindow.__init__(self, XAML_FILE)
        self._use_revit_default_window_icon()
        self.external_handler.ui_dispatcher = self.Dispatcher
        self._validate_theme_resources()
        self._cache_resources()
        self._wire_events()
        self._load_initial_state()

    def _use_revit_default_window_icon(self):
        try:
            self.Icon = None
        except Exception:
            pass

    def _validate_theme_resources(self):
        missing = []
        for key in REQUIRED_RESOURCE_KEYS:
            try:
                self.FindResource(key)
            except Exception:
                missing.append(key)
        if missing:
            forms.alert(
                "Missing WPF theme resource(s):\n\n{0}".format(", ".join(missing)),
                exitscript=True
            )

    def _cache_resources(self):
        self.brush_text = self.FindResource("Brush.Text")
        self.brush_subtext = self.FindResource("Brush.Subtext")
        self.brush_border = self.FindResource("Brush.Border")
        self.brush_surface = self.FindResource("Brush.Surface")
        self.brush_accent = self.FindResource("Brush.Accent")
        self.brush_success = self.FindResource("Brush.Success")
        self.brush_warning = self.FindResource("Brush.Warning")
        self.brush_danger = self.FindResource("Brush.Danger")
        self.brush_blocker_surface = self.FindResource("Brush.BlockerSurface")
        self.brush_blocker_border = self.FindResource("Brush.BlockerBorder")
        self.brush_success_surface = self.FindResource("Brush.SuccessSurface")
        self.brush_success_border = self.FindResource("Brush.SuccessBorder")
        self.brush_possible_surface = self.FindResource("Brush.PossibleSurface")
        self.brush_possible_border = self.FindResource("Brush.PossibleBorder")
        self.style_primary = self.FindResource("Button.Primary")
        self.style_secondary = self.FindResource("Button.Secondary")

    def _wire_events(self):
        self.BtnBack.Click += self.on_back_clicked
        self.BtnCancel.Click += self.on_close_clicked
        self.BtnAnalyze.Click += self.on_analyze_clicked
        self.BtnRecheck.Click += self.on_recheck_clicked
        self.BtnClose.Click += self.on_close_clicked
        self.Closed += self.on_window_closed
        self.TxtSearch.TextChanged += self.on_search_changed
        self.ComboViews.SelectionChanged += self.on_view_selected
        self.BtnPossibleToggle.Click += self.on_possible_toggle_clicked
        self.BtnPassedToggle.Click += self.on_passed_toggle_clicked

    def _load_initial_state(self):
        self.TxtElementTitle.Text = get_element_label(self.element)
        self.TxtElementSubtitle.Text = "Host-model element"
        self.PanelHeaderTarget.Visibility = Visibility.Collapsed
        self.TxtHeaderTargetView.Text = ""

        self.filter_view_list("")
        selected = self.ComboViews.SelectedItem
        self.target_view = selected.view if selected else None
        self.update_target_summary()
        self.update_analyze_enabled()
        self.set_status("Choose the view where the element is missing.")

    def set_status(self, message):
        self.TxtStatus.Text = message

    def set_busy(self, is_busy):
        self.BtnAnalyze.IsEnabled = False if is_busy else self.has_valid_inputs()
        self.BtnRecheck.IsEnabled = not is_busy
        self.BtnClose.IsEnabled = not is_busy
        self.BtnCancel.IsEnabled = not is_busy
        self.BtnBack.IsEnabled = not is_busy
        self.Cursor = None

    def has_valid_inputs(self):
        return self.element is not None and self.target_view is not None and view_can_be_target(self.target_view)

    def update_analyze_enabled(self):
        self.BtnAnalyze.IsEnabled = self.has_valid_inputs()

    def update_target_summary(self):
        if self.target_view:
            self.TxtTargetSummary.Text = "Selected view: {0}".format(self.target_view.Name)
        else:
            self.TxtTargetSummary.Text = "Selected view: none"

    def filter_view_list(self, query):
        query = (query or "").lower()
        self.ComboViews.Items.Clear()
        for choice in self.target_views:
            if not query or query in choice.display_name.lower():
                self.ComboViews.Items.Add(choice)

        if self.ComboViews.Items.Count > 0 and self.ComboViews.SelectedItem is None:
            self.ComboViews.SelectedIndex = 0

    def on_search_changed(self, sender, args):
        self.filter_view_list(self.TxtSearch.Text)
        selected = self.ComboViews.SelectedItem
        self.target_view = selected.view if selected else None
        self.update_target_summary()
        self.update_analyze_enabled()

    def on_view_selected(self, sender, args):
        selected = self.ComboViews.SelectedItem
        self.target_view = selected.view if selected else None
        self.update_target_summary()
        self.update_analyze_enabled()

    def on_analyze_clicked(self, sender, args):
        self.queue_request("analyze")

    def on_recheck_clicked(self, sender, args):
        self.queue_request("analyze")

    def on_back_clicked(self, sender, args):
        self.ResultsPanel.Visibility = Visibility.Collapsed
        self.InputPanel.Visibility = Visibility.Visible
        self.PanelHeaderTarget.Visibility = Visibility.Collapsed
        self.TxtHeaderTargetView.Text = ""
        self.BtnBack.Visibility = Visibility.Collapsed
        self.BtnRecheck.Visibility = Visibility.Collapsed
        self.BtnClose.Visibility = Visibility.Collapsed
        self.BtnCancel.Visibility = Visibility.Visible
        self.BtnAnalyze.Visibility = Visibility.Visible
        self.update_target_summary()
        self.update_analyze_enabled()
        self.set_status("Choose a different missing view, then analyze again.")

    def on_close_clicked(self, sender, args):
        close_output_window()
        self.Close()

    def on_window_closed(self, sender, args):
        self.cleanup_modeless_refs()

    def cleanup_modeless_refs(self):
        if self.external_handler is None:
            return

        self.external_handler.is_closed = True
        self.external_handler.clear()
        self.external_handler.window = None
        try:
            self.external_event.Dispose()
        except Exception:
            pass
        self.external_handler = None
        self.external_event = None
        try:
            _WNH_STATE["ui"] = None
            _WNH_STATE["handler"] = None
            _WNH_STATE["ext_event"] = None
        except Exception:
            pass
        close_output_window()

    def on_possible_toggle_clicked(self, sender, args):
        self.PanelPossibleItems.Visibility = (
            Visibility.Collapsed
            if self.PanelPossibleItems.Visibility == Visibility.Visible
            else Visibility.Visible
        )
        self.TxtPossibleChevron.Text = "v" if self.PanelPossibleItems.Visibility == Visibility.Collapsed else "^"

    def on_passed_toggle_clicked(self, sender, args):
        self.PanelPassedItems.Visibility = (
            Visibility.Collapsed
            if self.PanelPassedItems.Visibility == Visibility.Visible
            else Visibility.Visible
        )
        self.TxtPassedChevron.Text = "v" if self.PanelPassedItems.Visibility == Visibility.Collapsed else "^"

    def confirm_alert(self, message, title):
        was_topmost = False
        try:
            was_topmost = bool(self.Topmost)
            self.Topmost = False
        except Exception:
            pass

        try:
            return forms.alert(
                message,
                title=title,
                yes=True,
                no=True,
                exitscript=False
            )
        finally:
            try:
                self.Topmost = was_topmost
                self.Activate()
            except Exception:
                pass

    def queue_request(self, request_type, result=None):
        self.set_busy(True)
        if request_type == "analyze":
            self.set_status("Analyzing visibility...")
        elif request_type == "fix":
            self.set_status("Applying fix...")
        elif request_type == "undo":
            self.set_status("Undoing fix...")
        try:
            request = WhyNotHereRequest(
                request_type,
                result=result,
                callback=self.on_external_done
            )
            self.external_handler.enqueue(request)
            self.external_event.Raise()
        except Exception as err:
            self.set_busy(False)
            self.set_status("Could not queue Revit action: {0}".format(err))

    def on_external_done(self, action, msg, is_error, payload):
        self.set_busy(False)

        if payload and payload.get("fixed_result"):
            fixed_result = payload.get("fixed_result")
            rechecked = payload.get("results", [])
            self.results = [fixed_result]
            for item in rechecked:
                if not result_matches(fixed_result, item):
                    self.results.append(item)
        elif payload and payload.get("results") is not None:
            self.results = payload.get("results", [])

        if payload:
            self.render_results()
            self.InputPanel.Visibility = Visibility.Collapsed
            self.ResultsPanel.Visibility = Visibility.Visible
            self.BtnBack.Visibility = Visibility.Visible
            self.BtnCancel.Visibility = Visibility.Collapsed
            self.BtnAnalyze.Visibility = Visibility.Collapsed
            self.BtnRecheck.Visibility = Visibility.Visible
            self.BtnClose.Visibility = Visibility.Visible

        self.set_status(msg)

    def render_results(self):
        confirmed = [item for item in self.results if item.group == "confirmed"]
        possible = [item for item in self.results if item.group == "possible"]
        passed = [item for item in self.results if item.group == "passed"]

        remaining = len([item for item in confirmed if not item.fixed])
        if remaining > 0:
            self.TxtBlockerCount.Text = "{0} blocker{1} remaining".format(
                remaining,
                "" if remaining == 1 else "s"
            )
            self.TxtResultMarker.Text = "X"
            self.TxtResultMarker.Background = self.brush_danger
        else:
            self.TxtBlockerCount.Text = "0 blockers"
            self.TxtResultMarker.Text = u"\u2713"
            self.TxtResultMarker.Background = self.brush_success

        if possible:
            self.PanelPossibleSummary.Visibility = Visibility.Visible
            self.TxtPossibleSummary.Text = "{0} possible issue{1}".format(
                len(possible),
                "" if len(possible) == 1 else "s"
            )
            self.TxtPossibleSummaryMarker.Background = self.brush_warning
            self.TxtPossibleSummary.Foreground = self.brush_text
        else:
            self.PanelPossibleSummary.Visibility = Visibility.Collapsed
        self.PanelHeaderTarget.Visibility = Visibility.Visible
        self.TxtHeaderTargetView.Text = self.target_view.Name
        self.TxtPossibleCount.Text = "Possible issues ({0})".format(len(possible))
        self.TxtPassedCount.Text = "Passed checks ({0})".format(len(passed))

        self.PanelConfirmed.Children.Clear()
        self.PanelPossibleItems.Children.Clear()
        self.PanelPassedItems.Children.Clear()

        if confirmed:
            for item in confirmed:
                self.PanelConfirmed.Children.Add(self.make_issue_card(item))
        else:
            self.PanelConfirmed.Children.Add(self.make_empty_card("No confirmed blockers found."))

        for item in possible:
            self.PanelPossibleItems.Children.Add(self.make_issue_card(item))
        for item in passed:
            self.PanelPassedItems.Children.Add(self.make_issue_card(item))

        self.PanelPossibleItems.Visibility = Visibility.Visible if possible else Visibility.Collapsed
        self.PanelPassedItems.Visibility = Visibility.Collapsed
        self.TxtPossibleChevron.Text = "^" if possible else "v"
        self.TxtPassedChevron.Text = "v"
        self.update_possible_section_visuals(len(possible))

    def update_possible_section_visuals(self, possible_count):
        if possible_count > 0:
            self.BorderPossibleIssues.Background = self.brush_possible_surface
            self.BorderPossibleIssues.BorderBrush = self.brush_possible_border
            self.BorderPossibleIssues.BorderThickness = Thickness(2)
            self.BtnPossibleToggle.Background = self.brush_possible_surface
            self.BtnPossibleToggle.BorderBrush = self.brush_possible_border
            self.BtnPossibleToggle.Foreground = self.brush_warning
            self.TxtPossibleCount.Foreground = self.brush_warning
            self.TxtPossibleChevron.Foreground = self.brush_warning
            return

        self.BorderPossibleIssues.Background = self.brush_surface
        self.BorderPossibleIssues.BorderBrush = self.brush_border
        self.BorderPossibleIssues.BorderThickness = Thickness(1)
        self.BtnPossibleToggle.Background = Brushes.Transparent
        self.BtnPossibleToggle.BorderBrush = self.brush_accent
        self.BtnPossibleToggle.Foreground = self.brush_accent
        self.TxtPossibleCount.Foreground = self.brush_accent
        self.TxtPossibleChevron.Foreground = self.brush_accent

    def make_empty_card(self, message):
        border = Border()
        border.Background = self.brush_surface
        border.BorderBrush = self.brush_border
        border.BorderThickness = Thickness(1)
        border.CornerRadius = CornerRadius(5)
        border.Padding = Thickness(12)
        border.Margin = Thickness(0, 0, 0, 8)

        text = TextBlock()
        text.Text = message
        text.Foreground = self.brush_subtext
        text.TextWrapping = TextWrapping.Wrap
        border.Child = text
        return border

    def get_result_visuals(self, result):
        if result.fixed or result.group == "passed":
            return (
                u"\u2713",
                self.brush_success,
                self.brush_success_surface,
                self.brush_success_border
            )
        if result.group == "confirmed":
            return (
                "X",
                self.brush_danger,
                self.brush_blocker_surface,
                self.brush_blocker_border
            )
        if result.group == "possible":
            return (
                "?",
                self.brush_warning,
                self.brush_possible_surface,
                self.brush_possible_border
            )
        return (
            "",
            self.brush_subtext,
            self.brush_surface,
            self.brush_border
        )

    def make_issue_card(self, result):
        marker_text, marker_brush, surface_brush, border_brush = self.get_result_visuals(result)

        border = Border()
        border.Background = surface_brush
        border.BorderBrush = border_brush
        border.BorderThickness = Thickness(1)
        border.CornerRadius = CornerRadius(5)
        border.Padding = Thickness(12)
        border.Margin = Thickness(0, 0, 0, 8)

        shell = DockPanel()
        shell.LastChildFill = True

        marker = TextBlock()
        marker.Text = marker_text
        marker.Width = 24
        marker.FontSize = 16
        marker.FontWeight = FontWeights.Bold
        marker.Foreground = marker_brush
        marker.TextAlignment = System.Windows.TextAlignment.Center
        marker.Margin = Thickness(0, 0, 10, 0)
        DockPanel.SetDock(marker, Dock.Left)
        shell.Children.Add(marker)

        panel = StackPanel()
        panel.Orientation = Orientation.Vertical

        title = TextBlock()
        title.Text = ("Fixed: " if result.fixed else "") + result.title
        title.FontWeight = FontWeights.SemiBold
        title.FontSize = 14
        title.Foreground = self.brush_success if result.fixed or result.group == "passed" else self.brush_text
        title.TextWrapping = TextWrapping.Wrap
        panel.Children.Add(title)

        explanation = self.make_text(result.fix_message if result.fixed else result.explanation, self.brush_text, 0, True)
        panel.Children.Add(explanation)

        if result.evidence and not result.fixed:
            panel.Children.Add(self.make_label_text("Evidence: ", result.evidence))
        if result.recommendation and not result.fixed:
            panel.Children.Add(self.make_label_text("Recommended correction: ", result.recommendation))

        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.HorizontalAlignment = HorizontalAlignment.Right
        actions.Margin = Thickness(0, 8, 0, 0)

        if result.fixed:
            undo_button = Button()
            undo_button.Content = "Undo"
            undo_button.Style = self.style_secondary
            undo_button.Margin = Thickness(0, 0, 8, 0)
            undo_button.Click += self.make_undo_handler(result)
            actions.Children.Add(undo_button)
        else:
            if result.action_name:
                fix_button = Button()
                fix_button.Content = ACTION_LABELS.get(result.action_name, "Fix")
                fix_button.Style = self.style_primary
                fix_button.Click += self.make_fix_handler(result)
                actions.Children.Add(fix_button)
        if actions.Children.Count > 0:
            panel.Children.Add(actions)

        shell.Children.Add(panel)
        border.Child = shell
        return border

    def make_text(self, value, brush, top_margin, wrap):
        text = TextBlock()
        text.Text = value
        text.Foreground = brush
        text.Margin = Thickness(0, top_margin, 0, 0)
        if wrap:
            text.TextWrapping = TextWrapping.Wrap
        return text

    def make_label_text(self, label, value):
        text = TextBlock()
        text.Text = label + value
        text.Foreground = self.brush_subtext
        text.Margin = Thickness(0, 6, 0, 0)
        text.TextWrapping = TextWrapping.Wrap
        return text

    def make_fix_handler(self, result):
        def handler(sender, args):
            self.run_fix(result)
        return handler

    def make_undo_handler(self, result):
        def handler(sender, args):
            self.run_undo(result)
        return handler

    def run_fix(self, result):
        if not result.action_name:
            return

        ok = self.confirm_alert(
            "Apply this fix to target view '{0}'?\n\n{1}".format(
                self.target_view.Name,
                result.recommendation
            ),
            "Confirm fix"
        )
        if not ok:
            self.set_status("Fix canceled.")
            return

        self.queue_request("fix", result)

    def run_undo(self, result):
        ok = self.confirm_alert(
            "Undo this fix in target view '{0}'?".format(self.target_view.Name),
            "Confirm undo"
        )
        if not ok:
            self.set_status("Undo canceled.")
            return

        self.queue_request("undo", result)

    def is_open(self):
        try:
            return self.IsVisible
        except Exception:
            return False

    def activate(self):
        try:
            self.Activate()
        except Exception:
            pass

    def show(self):
        try:
            helper = WindowInteropHelper(self)
            helper.Owner = (
                System.Diagnostics.Process
                .GetCurrentProcess()
                .MainWindowHandle
            )
        except Exception:
            pass

        self.Topmost = True
        self.Show()


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    existing_ui = _WNH_STATE.get("ui", None)

    if existing_ui is not None:
        try:
            if existing_ui.is_open():
                existing_ui.activate()
                return
            _WNH_STATE["ui"] = None
            _WNH_STATE["handler"] = None
            _WNH_STATE["ext_event"] = None
        except Exception:
            _WNH_STATE["ui"] = None
            _WNH_STATE["handler"] = None
            _WNH_STATE["ext_event"] = None

    revit_doc = require_active_document()
    element = get_initial_element(revit_doc)
    handler = WhyNotHereExternalHandler()
    ext_event = ExternalEvent.Create(handler)
    ui = WhyNotHereWindow(revit_doc, element, ext_event, handler)

    _WNH_STATE["handler"] = handler
    _WNH_STATE["ext_event"] = ext_event
    _WNH_STATE["ui"] = ui

    ui.show()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as err:
        logger.error("Unhandled error in {0}: {1}".format(TOOL_NAME, err))
        logger.debug(traceback.format_exc())
        error_output = script.get_output()
        error_output.print_md("### {0} failed".format(TOOL_NAME))
        error_output.print_md("```text\n{0}\n```".format(traceback.format_exc()))
        forms.alert(
            "{0} failed.\n\nCheck the pyRevit output window for details.".format(TOOL_NAME),
            exitscript=True
        )

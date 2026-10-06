# -*- coding: utf-8 -*-
__title__   = "TagHVAC"
__doc__     = """Version = 1.3
Date    = 05.10.2026
________________________________________________________________
Description:

Etiqueta todas las tuberias y conductos VERTICALES de la vista activa,
agrupados por tipo de sistema.

Muestra un formulario con una fila por cada sistema detectado para
elegir que tipo de etiqueta se aplica a cada grupo. Las etiquetas se
crean desplazadas 100 cm respecto al punto medio del elemento y con
directriz (leader).

El formulario tiene una altura maxima (85% de la pantalla) y una barra
de desplazamiento vertical para la lista de sistemas: el boton
"Etiquetar" queda siempre visible, fijo en la parte inferior. Ademas
la ventana se puede redimensionar a mano.

Si dos cabezas de etiqueta quedan solapadas (o se tocan), el script las
desplaza en horizontal y/o vertical (segun los ejes de la propia vista)
hasta separarlas, SIN girarlas.

La verticalidad se comprueba con una tolerancia de 10 grados para
tolerar pequeños errores de modelizacion.
________________________________________________________________
How-To:

- Abre una vista 2D (planta, seccion o alzado).
- Pulsa el boton: aparecera un grupo por cada sistema vertical detectado.
- Marca los grupos que quieras etiquetar y elige su tipo de etiqueta.
- Aceptar -> crea todas las etiquetas en UNA sola transaccion (un solo Undo).
________________________________________________________________
Last Updates:
- [05.10.2026] v1.3 Anti-solape: una etiqueta que no se puede separar
                    vuelve a su posicion original + RollBack si falla
- [25.08.2026] v1.2 Anti-solape de cabezas de etiqueta
________________________________________________________________
Author: Dailo Lorenzo Perez"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import *

from pyrevit import forms, script

from System.Windows import (Window, WindowStartupLocation, ResizeMode,
                            Thickness, HorizontalAlignment, TextWrapping,
                            FontWeights, SystemParameters)
from System.Windows.Controls import (StackPanel, Orientation, CheckBox,
                                     ComboBox, Button, TextBlock,
                                     ScrollViewer, ScrollBarVisibility,
                                     DockPanel, Dock, Separator)
from System.Windows.Media import Brushes

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document if uidoc else None

TOL_ANGLE_DEG    = 10.0    # Tolerancia de verticalidad (grados)
OFFSET_CM        = 100.0   # Desplazamiento de la cabeza de la etiqueta (cm)
MIN_CURVE_LEN_FT = 1e-6    # Longitud minima de curva valida (pies)
TITULO_FORM      = u'Etiquetar CVC'

ANCHO_VENTANA       = 540.0
ALTO_MIN_VENTANA    = 340.0
ALTO_MAX_PORCENTAJE = 0.85   # % de la altura de pantalla disponible
ALTO_POR_FILA       = 68.0   # estimacion px por fila (checkbox + combo)
ALTO_POR_SECCION    = 40.0   # estimacion px por cabecera de seccion
ALTO_FIJO_FORM      = 210.0  # cabecera + pie (skip + boton) estimados

# Anti-solape de cabezas de etiqueta (desplazamiento, sin giro)
MARGEN_SOLAPE_CM = 2.0    # holgura para considerar "se tocan"
MOV_RONDAS       = 4      # nº de pasadas completas sobre todas las etiquetas
# Distancias que se van probando en cada intento (cm) -> se ha ampliado
# bastante el rango, hasta 3 m, para casos con muchas etiquetas apiladas.
MOV_PASOS_CM = [10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0]
# Direcciones a probar en cada paso, en ejes de la VISTA (horizontal, vertical):
# derecha, izquierda, arriba, abajo, las 4 diagonales y pasos intermedios.
MOV_DIRECCIONES = [(1, 0), (-1, 0), (0, 1), (0, -1),
                   (1, 1), (-1, 1), (1, -1), (-1, -1),
                   (2, 1), (-2, 1), (2, -1), (-2, -1),
                   (1, 2), (-1, 2), (1, -2), (-1, -2)]

# Parametro de sistema segun familia MEP
BIP_SISTEMA = {
    'pipe': BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
    'duct': BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
}

# Categorias de elementos y de etiquetas asociadas
BIC_ELEMENTOS = {
    'pipe': BuiltInCategory.OST_PipeCurves,
    'duct': BuiltInCategory.OST_DuctCurves,
}
BIC_ETIQUETAS = {
    'pipe': BuiltInCategory.OST_PipeTags,
    'duct': BuiltInCategory.OST_DuctTags,
}
NOMBRE_KIND = {'pipe': u'Tuberías', 'duct': u'Conductos'}

# Vistas 2D donde tiene sentido etiquetar
VISTAS_PERMITIDAS = (
    ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.AreaPlan,
    ViewType.EngineeringPlan, ViewType.Section, ViewType.Elevation,
    ViewType.Detail,
)


# ── Funciones ─────────────────────────────────────
def alerta(msg):
    """Muestra un aviso informativo con el titulo del boton."""
    forms.alert(msg, title=TITULO_FORM)


def valor_id(eid):
    """Valor numerico del ElementId compatible con todas las versiones."""
    try:
        return eid.Value           # Revit 2024+
    except Exception:
        return eid.IntegerValue    # Versiones anteriores


def angulo_desde_vertical(elem):
    """Grados entre el eje del elemento y el eje Z. None si no calculable."""
    loc = elem.Location
    if loc is None or not isinstance(loc, LocationCurve):
        return None
    curva = loc.Curve
    if curva is None:
        return None
    try:
        p0 = curva.GetEndPoint(0)
        p1 = curva.GetEndPoint(1)
    except Exception:
        return None
    vector = p1 - p0
    if vector.GetLength() < MIN_CURVE_LEN_FT:
        return None
    direccion = vector.Normalize()
    cos_ang = max(-1.0, min(1.0, abs(direccion.Z)))
    return math.degrees(math.acos(cos_ang))


def nombre_sistema(elem, kind):
    """Nombre del tipo de sistema del elemento (fallback robusto)."""
    param = elem.get_Parameter(BIP_SISTEMA[kind])
    nombre = param.AsValueString() if param is not None else None
    if not nombre:
        sistema = elem.MEPSystem
        nombre = sistema.Name if sistema is not None else u'(Sin sistema)'
    return nombre


def recolectar_verticales(view):
    """Agrupa los MEP verticales de la vista por familia y tipo de sistema.

    Returns:
        list[dict]: [{'kind': 'pipe'|'duct',
                      'sistema': str,
                      'elems': [Element, ...]}, ...]
    """
    grupos = {}
    for kind in ('pipe', 'duct'):
        colector = (FilteredElementCollector(doc, view.Id)
                    .OfCategory(BIC_ELEMENTOS[kind])
                    .WhereElementIsNotElementType())
        for elem in colector.ToElements():
            angulo = angulo_desde_vertical(elem)
            if angulo is None or angulo > TOL_ANGLE_DEG:
                continue
            clave = (kind, nombre_sistema(elem, kind))
            grupos.setdefault(clave, []).append(elem)

    orden_kind = {'pipe': 0, 'duct': 1}
    resultado = []
    for (kind, sistema), elems in grupos.items():
        resultado.append({'kind': kind, 'sistema': sistema, 'elems': elems})
    resultado.sort(key=lambda g: (orden_kind[g['kind']],
                                  -len(g['elems']),
                                  g['sistema']))
    return resultado


def obtener_tipos_etiqueta(kind):
    """Tipos de etiqueta cargados del proyecto -> {nombre: FamilySymbol}."""
    tipos = {}
    colector = (FilteredElementCollector(doc)
                .OfClass(FamilySymbol)
                .OfCategory(BIC_ETIQUETAS[kind]))
    for sym in colector.ToElements():
        try:
            nombre = Element.Name.GetValue(sym)
        except Exception:
            nombre = sym.Name
        tipos[nombre] = sym
    return tipos


def ids_ya_etiquetados(view):
    """Ids de elementos que ya tienen alguna etiqueta en la vista."""
    ids = set()
    for tag in (FilteredElementCollector(doc, view.Id)
                .OfClass(IndependentTag).ToElements()):
        try:
            for eid in tag.GetTaggedLocalElementIds():
                ids.add(valor_id(eid))
        except Exception:
            pass
    return ids


def calcular_alto_ventana(grupos):
    """Altura inicial de la ventana: se ajusta al numero de filas pero
    nunca supera ALTO_MAX_PORCENTAJE de la pantalla disponible (para eso
    esta el ScrollViewer) ni baja de ALTO_MIN_VENTANA."""
    num_secciones = len(set(g['kind'] for g in grupos))
    alto_contenido = (ALTO_FIJO_FORM
                      + num_secciones * ALTO_POR_SECCION
                      + len(grupos) * ALTO_POR_FILA)
    alto_maximo = SystemParameters.WorkArea.Height * ALTO_MAX_PORCENTAJE
    return max(ALTO_MIN_VENTANA, min(alto_contenido, alto_maximo)), alto_maximo


def crear_ventana_formulario(grupos, tipos_por_kind, vista_nombre):
    """Construye el formulario WPF: cabecera y boton fijos, lista de
    sistemas con scroll vertical si no caben en pantalla.

    Returns:
        tuple: (Window, filas, chk_skip)
               filas = [{'grupo': dict, 'checkbox': CheckBox,
                        'combo': ComboBox, 'tipos': dict}, ...]
               (solo filas con tipos de etiqueta disponibles)
    """
    alto_inicial, alto_maximo = calcular_alto_ventana(grupos)

    ventana = Window()
    ventana.Title = TITULO_FORM
    ventana.Width = ANCHO_VENTANA
    ventana.Height = alto_inicial
    ventana.MaxHeight = alto_maximo
    ventana.MinHeight = ALTO_MIN_VENTANA
    ventana.MinWidth = 420.0
    ventana.ResizeMode = ResizeMode.CanResize
    ventana.WindowStartupLocation = WindowStartupLocation.CenterScreen

    raiz = DockPanel()
    raiz.LastChildFill = True
    ventana.Content = raiz

    # --- Cabecera (fija, arriba) ---------------------------------
    lbl_vista = TextBlock()
    lbl_vista.Text = u'Vista: {}   ·   Verticalidad ±{}°'.format(
        vista_nombre, int(TOL_ANGLE_DEG))
    lbl_vista.TextWrapping = TextWrapping.Wrap
    lbl_vista.FontWeight = FontWeights.Bold
    lbl_vista.Margin = Thickness(14, 12, 14, 8)
    DockPanel.SetDock(lbl_vista, Dock.Top)
    raiz.Children.Add(lbl_vista)

    # --- Pie (fijo, abajo): omitir ya etiquetados + boton ---------
    panel_pie = StackPanel()
    panel_pie.Orientation = Orientation.Vertical
    panel_pie.Margin = Thickness(14, 6, 14, 14)
    DockPanel.SetDock(panel_pie, Dock.Bottom)

    sep_pie = Separator()
    sep_pie.Margin = Thickness(0, 0, 0, 10)
    panel_pie.Children.Add(sep_pie)

    chk_skip = CheckBox()
    chk_skip.Content = u'Omitir elementos ya etiquetados'
    chk_skip.IsChecked = True
    chk_skip.Margin = Thickness(0, 0, 0, 10)
    panel_pie.Children.Add(chk_skip)

    boton = Button()
    boton.Content = u'✔ Etiquetar'
    boton.Padding = Thickness(18, 6, 18, 6)
    boton.MinWidth = 110.0
    boton.HorizontalAlignment = HorizontalAlignment.Right
    boton.IsDefault = True

    def _on_click(sender, args):
        ventana.DialogResult = True
        ventana.Close()
    boton.Click += _on_click

    panel_pie.Children.Add(boton)
    raiz.Children.Add(panel_pie)

    # --- Zona central con scroll: lista de sistemas ----------------
    scroll = ScrollViewer()
    scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
    scroll.Margin = Thickness(14, 0, 14, 0)
    scroll.Padding = Thickness(0, 0, 8, 0)

    contenedor = StackPanel()
    contenedor.Orientation = Orientation.Vertical
    scroll.Content = contenedor

    filas = []
    kind_anterior = None
    for grupo in grupos:
        # Cabecera de seccion al cambiar de familia (tuberias/conductos)
        if grupo['kind'] != kind_anterior:
            kind_anterior = grupo['kind']
            sep = Separator()
            sep.Margin = Thickness(0, 10, 0, 4)
            contenedor.Children.Add(sep)
            titulo_kind = TextBlock()
            titulo_kind.Text = u'─── {} VERTICALES ───'.format(
                NOMBRE_KIND[kind_anterior].upper())
            titulo_kind.FontWeight = FontWeights.Bold
            titulo_kind.Margin = Thickness(0, 0, 0, 6)
            contenedor.Children.Add(titulo_kind)

        texto_grupo = u'{} · {}   ({})'.format(
            NOMBRE_KIND[grupo['kind']], grupo['sistema'],
            len(grupo['elems']))
        tipos = tipos_por_kind[grupo['kind']]

        fila_panel = StackPanel()
        fila_panel.Orientation = Orientation.Vertical
        fila_panel.Margin = Thickness(0, 0, 0, 8)

        chk = CheckBox()
        chk.Content = texto_grupo
        chk.Margin = Thickness(0, 0, 0, 3)

        if tipos:
            chk.IsChecked = True
            combo = ComboBox()
            combo.Margin = Thickness(22, 0, 0, 0)
            combo.MinWidth = 280.0
            combo.HorizontalAlignment = HorizontalAlignment.Left
            for nombre in sorted(tipos.keys()):
                combo.Items.Add(nombre)
            combo.SelectedIndex = 0

            fila_panel.Children.Add(chk)
            fila_panel.Children.Add(combo)
            contenedor.Children.Add(fila_panel)
            filas.append({'grupo': grupo, 'checkbox': chk,
                          'combo': combo, 'tipos': tipos})
        else:
            # Grupo visible pero sin etiquetas cargadas -> deshabilitado
            chk.IsChecked = False
            chk.IsEnabled = False
            fila_panel.Children.Add(chk)
            aviso = TextBlock()
            aviso.Text = u'⚠ Sin tipos de etiqueta cargados'
            aviso.Margin = Thickness(22, 0, 0, 0)
            aviso.Foreground = Brushes.OrangeRed
            fila_panel.Children.Add(aviso)
            contenedor.Children.Add(fila_panel)

    raiz.Children.Add(scroll)

    return ventana, filas, chk_skip


def bbox_tag(tag, view):
    """BoundingBox de la etiqueta en la vista, o None si no se puede calcular."""
    try:
        return tag.get_BoundingBox(view)
    except Exception:
        return None


def cajas_solapan(b1, b2, margen_ft):
    """True si dos BoundingBox se solapan o se tocan (con holgura margen_ft)."""
    if b1 is None or b2 is None:
        return False
    return (b1.Min.X - margen_ft <= b2.Max.X and b2.Min.X - margen_ft <= b1.Max.X and
            b1.Min.Y - margen_ft <= b2.Max.Y and b2.Min.Y - margen_ft <= b1.Max.Y and
            b1.Min.Z - margen_ft <= b2.Max.Z and b2.Min.Z - margen_ft <= b1.Max.Z)


def mover_tag_absoluto(tag, vector_absoluto, vector_acumulado):
    """Desplaza la etiqueta hasta dejarla en 'vector_absoluto' respecto a su
    posicion original (no acumula sobre el movimiento anterior, lo sustituye)."""
    delta = vector_absoluto - vector_acumulado
    if delta.GetLength() < 1e-9:
        return
    ElementTransformUtils.MoveElement(doc, tag.Id, delta)


def resolver_solapes_cabezas(tags, view, margen_ft):
    """Desplaza (en horizontal y/o vertical, segun los ejes de la vista, SIN
    girar) las cabezas de etiqueta que se solapan entre si, hasta separarlas
    o hasta agotar las combinaciones de MOV_PASOS_CM x MOV_DIRECCIONES.
    Devuelve cuantas se movieron en total.

    Hace varias pasadas completas (MOV_RONDAS) porque al mover una etiqueta
    puede dejar de solapar con la primera pero empezar a solapar con otra
    que ya se habia movido antes; repetir la pasada limpia esos casos.

    Nota: es una heuristica -> no reoptimiza globalmente, asi que en casos
    extremadamente apretados puede quedar algun solape residual.
    """
    if len(tags) < 2:
        return 0

    doc.Regenerate()
    horiz = view.RightDirection
    vert = view.UpDirection

    def solapa_con_otras(idx):
        bbox_a = bbox_tag(tags[idx], view)
        if bbox_a is None:
            return False
        for k, otro in enumerate(tags):
            if k == idx:
                continue
            if cajas_solapan(bbox_a, bbox_tag(otro, view), margen_ft):
                return True
        return False

    ids_movidas = set()
    for ronda in range(MOV_RONDAS):
        algun_cambio = False
        for i, tag in enumerate(tags):
            if not solapa_con_otras(i):
                continue

            acumulado = XYZ.Zero
            resuelto = False
            for paso_cm in MOV_PASOS_CM:
                paso_ft = UnitUtils.ConvertToInternalUnits(
                    paso_cm, UnitTypeId.Centimeters)
                for dx, dy in MOV_DIRECCIONES:
                    vector_obj = (horiz * (dx * paso_ft)) + (vert * (dy * paso_ft))
                    mover_tag_absoluto(tag, vector_obj, acumulado)
                    acumulado = vector_obj
                    doc.Regenerate()
                    if not solapa_con_otras(i):
                        resuelto = True
                        break
                if resuelto:
                    break

            # Sin hueco libre -> la etiqueta vuelve a su posicion original
            if not resuelto:
                mover_tag_absoluto(tag, XYZ.Zero, acumulado)
                acumulado = XYZ.Zero
                doc.Regenerate()

            if acumulado.GetLength() > 1e-9:
                ids_movidas.add(valor_id(tag.Id))
                algun_cambio = True

        if not algun_cambio:
            break   # ya no queda ningun solape que se pueda resolver -> salir antes

    return len(ids_movidas)


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# --- Contexto obligatorio -------------------------------------
if uidoc is None:
    alerta(u'No hay ningun documento abierto en Revit.')
    script.exit()

view = uidoc.ActiveView
if view is None:
    alerta(u'No hay ninguna vista activa.')
    script.exit()

if view.ViewType not in VISTAS_PERMITIDAS:
    alerta(u'La vista activa "{}" no admite etiquetas.\n'
           u'Abre una vista 2D (planta, seccion o alzado).'.format(view.Name))
    script.exit()

# --- Deteccion de verticales ----------------------------------
grupos = recolectar_verticales(view)
if not grupos:
    alerta(u'No hay tuberias ni conductos verticales (±{}°) en la vista\n'
           u'"{}".'.format(int(TOL_ANGLE_DEG), view.Name))
    script.exit()

tipos_por_kind = {'pipe': obtener_tipos_etiqueta('pipe'),
                  'duct': obtener_tipos_etiqueta('duct')}
if not any(tipos_por_kind[g['kind']] for g in grupos):
    alerta(u'No hay familias de etiqueta de tuberia ni de conducto '
           u'cargadas en el proyecto.\nCarga al menos una y vuelve a intentarlo.')
    script.exit()

# --- Formulario ------------------------------------------------
ventana, filas, chk_skip = crear_ventana_formulario(grupos, tipos_por_kind,
                                                    view.Name)
resultado_dialogo = ventana.ShowDialog()

if resultado_dialogo is not True:
    script.exit()   # Cerrado con X o cancelado -> salir sin tocar nada

# --- Selecciones del usuario -----------------------------------
omitir_etiquetados = bool(chk_skip.IsChecked)
ya_etiquetados = ids_ya_etiquetados(view) if omitir_etiquetados else set()

objetivos = []   # [(Element, FamilySymbol), ...]
for fila in filas:
    if not fila['checkbox'].IsChecked:
        continue
    nombre_sel = fila['combo'].SelectedItem
    if not nombre_sel:
        continue
    simbolo = fila['tipos'].get(nombre_sel)
    if simbolo is None:
        continue
    for elem in fila['grupo']['elems']:
        objetivos.append((elem, simbolo))

if not objetivos:
    alerta(u'No hay ningun grupo marcado para etiquetar.')
    script.exit()

offset_ft = UnitUtils.ConvertToInternalUnits(OFFSET_CM,
                                             UnitTypeId.Centimeters)
margen_solape_ft = UnitUtils.ConvertToInternalUnits(MARGEN_SOLAPE_CM,
                                                    UnitTypeId.Centimeters)

# --- Creacion de etiquetas (UNA transaccion) --------------------
creadas = omitidas = fallidas = 0
activados = set()   # Ids de FamilySymbol ya activados
tags_creados = []   # Etiquetas creadas con exito (para el anti-solape)

t = Transaction(doc, u'Etiquetar CVC')
t.Start()
try:
    for elem, simbolo in objetivos:
        try:
            if valor_id(elem.Id) in ya_etiquetados:
                omitidas += 1
                continue

            sid = valor_id(simbolo.Id)
            if sid not in activados and not simbolo.IsActive:
                simbolo.Activate()
            activados.add(sid)

            curva = elem.Location.Curve
            medio = (curva.GetEndPoint(0) + curva.GetEndPoint(1)) * 0.5

            tag = IndependentTag.Create(doc, simbolo.Id, view.Id,
                                        Reference(elem), True,
                                        TagOrientation.Horizontal, medio)
            tag.TagHeadPosition = XYZ(medio.X + offset_ft,
                                      medio.Y + offset_ft,
                                      medio.Z)
            tags_creados.append(tag)
            creadas += 1
        except Exception as ex:
            fallidas += 1
            print(u'⚠ Fallo etiquetando elemento {}: {}'.format(elem.Id, ex))

    # --- Anti-solape: desplaza (sin girar) las cabezas que se tocan --
    movidas = resolver_solapes_cabezas(tags_creados, view, margen_solape_ft)

    t.Commit()
except Exception:
    t.RollBack()
    raise

resumen = (u'✅ Etiquetas creadas: {}\n'
           u'↔ Movidas para evitar solapes: {}\n'
           u'⏭ Omitidas (ya etiquetadas): {}\n'
           u'⚠ Fallos: {}').format(creadas, movidas, omitidas, fallidas)
print(resumen)
alerta(resumen)
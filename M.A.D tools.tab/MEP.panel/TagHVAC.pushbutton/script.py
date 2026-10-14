# -*- coding: utf-8 -*-
__title__   = "TagHVAC"
__doc__     = """Version = 1.6
Date    = 14.10.2026
________________________________________________________________
Description:

Etiqueta todas las tuberias y conductos VERTICALES de la vista activa,
agrupados por tipo de sistema.

Muestra un formulario con una fila por cada sistema detectado para
elegir que tipo de etiqueta se aplica a cada grupo. Las etiquetas se
crean con directriz (leader).

Si varias canalizaciones del mismo sistema se ven en la MISMA VERTICAL
(p. ej. un montante partido en tramos por planta), solo se coloca UNA
etiqueta para todas ellas.

Las etiquetas se agrupan por ZONAS (elementos cercanos) y cada zona se
coloca en una COLUMNA alineada a un lado de sus elementos, ordenada
para que las directrices NO se crucen. Las columnas no tapan las redes
del modelo nativo (tuberias, conductos, bandejas y tubos, con su trazado
real), etiquetas que ya existian ni los elementos: si chocan, se desplaza
la columna entera, pero como mucho 25 mm de papel para que no se aleje
de su zona. Las distancias van en mm de PAPEL (igual a cualquier escala).

El formulario recuerda el tipo de etiqueta elegido para cada sistema
la proxima vez que se use el boton.

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
- [14.10.2026] v1.6 Las etiquetas no tapan las redes (trazado real).
                    Desplazamiento de columna limitado a 25 mm de papel.
                    Directrices re-ordenadas tras desplazar la columna
                    (antes podian volver a cruzarse).
- [14.10.2026] v1.5 Etiquetas alineadas en columnas por zona y
                    directrices sin cruces.
- [14.10.2026] v1.4 Una sola etiqueta por vertical. Desplazamientos en
                    ejes de la vista y en mm de papel (corrige secciones).
                    Anti-solape mucho mas rapido (sin regenerar en cada
                    intento), mide solo la cabeza y respeta las etiquetas
                    existentes. Nombres "Familia : Tipo". Recuerda la
                    ultima eleccion. Boton Cancelar.
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
import json
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
CONFIG = script.get_config()

TOL_ANGLE_DEG    = 10.0    # Tolerancia de verticalidad (grados)
MIN_CURVE_LEN_FT = 1e-6    # Longitud minima de curva valida (pies)
TITULO_FORM      = u'Etiquetar CVC'

# Distancias en mm de PAPEL (se multiplican por la escala de la vista).
# A 1:50 -> 20 mm de papel = 100 cm de modelo (lo mismo que en v1.3).
OFFSET_PAPEL_MM  = 20.0    # Distancia de la columna de etiquetas a los elementos

# Dos elementos estan "en la misma vertical" si sus ejes, vistos en la
# vista activa, quedan a menos de esta distancia (cm de modelo).
TOL_MISMA_VERTICAL_CM = 5.0

ANCHO_VENTANA       = 540.0
ALTO_MIN_VENTANA    = 340.0
ALTO_MAX_PORCENTAJE = 0.85   # % de la altura de pantalla disponible
ALTO_POR_FILA       = 68.0   # estimacion px por fila (checkbox + combo)
ALTO_POR_SECCION    = 40.0   # estimacion px por cabecera de seccion
ALTO_FIJO_FORM      = 210.0  # cabecera + pie (skip + botones) estimados

# Maquetacion: columnas de etiquetas alineadas por zona (mm de papel)
RADIO_ZONA_PAPEL_MM       = 40.0  # elementos a menos de esto del centro de
                                  # una zona comparten columna (1:50 -> 2 m)
SEPARACION_FILAS_PAPEL_MM = 1.0   # hueco vertical entre etiquetas apiladas
RADIO_ELEMENTO_PAPEL_MM   = 1.5   # zona alrededor de cada elemento que las
                                  # cabezas no deben tapar
MARGEN_SOLAPE_PAPEL_MM    = 0.4   # holgura para considerar "se tocan"
MAX_ITER_DESCRUCE         = 200   # tope de pasadas para descruzar directrices
CELDA_MAPA_PAPEL_MM       = 10.0  # tamaño de celda del indice espacial
# Si una columna choca con algo se desplaza ENTERA, pero nunca mas lejos
# que esto: si no hay hueco libre cerca, se queda cerca aunque toque algo.
MAX_DESPLAZAMIENTO_PAPEL_MM = 25.0
# Distancias que se van probando (mm de papel); a 1:50 equivalen a
# 10..125 cm de modelo.
MOV_PASOS_PAPEL_MM = [2.0, 4.0, 6.0, 10.0, 15.0, 20.0, 25.0]

# Redes que las cabezas de etiqueta no deben tapar (solo modelo nativo; se
# usa su trazado real con su grosor, no su caja envolvente)
CATEGORIAS_REDES = ['OST_PipeCurves', 'OST_DuctCurves', 'OST_CableTray',
                    'OST_Conduit', 'OST_FlexPipeCurves', 'OST_FlexDuctCurves']
# Parametros cuyo valor maximo da el grosor visible de una canalizacion
BIPS_GROSOR = [
    BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
    BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
    BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
    BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
    BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
    BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
]
# Direcciones a probar, en ejes de la VISTA (horizontal, vertical):
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


# ── Utilidades generales ──────────────────────────
def alerta(msg):
    """Muestra un aviso informativo con el titulo del boton."""
    forms.alert(msg, title=TITULO_FORM)


def valor_id(eid):
    """Valor numerico del ElementId compatible con todas las versiones."""
    try:
        return eid.Value           # Revit 2024+
    except Exception:
        return eid.IntegerValue    # Versiones anteriores


def cm_a_pies(cm):
    return UnitUtils.ConvertToInternalUnits(cm, UnitTypeId.Centimeters)


def papel_a_pies(mm_papel, view):
    """mm de papel -> pies de modelo segun la escala de la vista."""
    escala = view.Scale if view.Scale > 0 else 1
    return UnitUtils.ConvertToInternalUnits(mm_papel * escala,
                                            UnitTypeId.Millimeters)


def cargar_memoria():
    """{'kind|sistema': 'Familia : Tipo'} elegidos en la ultima ejecucion."""
    try:
        return json.loads(CONFIG.get_option('ultimas_etiquetas', '{}')) or {}
    except Exception:
        return {}


def guardar_memoria(memoria):
    try:
        CONFIG.ultimas_etiquetas = json.dumps(memoria)
        script.save_config()
    except Exception:
        pass   # Recordar la eleccion es una comodidad, nunca debe romper nada


def clave_memoria(grupo):
    return u'{}|{}'.format(grupo['kind'], grupo['sistema'])


# ── Geometria de los elementos ────────────────────
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


def punto_medio(elem):
    curva = elem.Location.Curve
    return (curva.GetEndPoint(0) + curva.GetEndPoint(1)) * 0.5


def huella_en_vista(punto, view):
    """Coordenadas (en ejes de la vista) que identifican 'la vertical' por la
    que pasa un punto:
      - Planta: un elemento vertical se ve como un punto -> (u, v).
      - Seccion/alzado: se ve como una linea vertical -> solo (u,), porque
        dos tramos a distinta altura (o profundidad) se ven en la misma linea.
    """
    u = punto.DotProduct(view.RightDirection)
    if abs(view.ViewDirection.Z) > 0.5:      # Vista "en planta"
        return (u, punto.DotProduct(view.UpDirection))
    return (u,)


def distancia_huellas(h1, h2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(h1, h2)))


def agrupar_por_vertical(elems, view, tol_ft):
    """Reparte los elementos en 'verticales': listas de elementos que se ven
    superpuestos en la vista. Cada vertical recibira UNA sola etiqueta."""
    verticales = []   # [(huella_referencia, [elems...]), ...]
    for elem in elems:
        huella = huella_en_vista(punto_medio(elem), view)
        for referencia, miembros in verticales:
            if distancia_huellas(huella, referencia) <= tol_ft:
                miembros.append(elem)
                break
        else:
            verticales.append((huella, [elem]))
    return [miembros for _, miembros in verticales]


def elegir_representante(vertical, view):
    """De una lista de elementos que se ven en la misma vertical, devuelve el
    elemento al que se le pondra la etiqueta.

    - Planta: el tramo que atraviesa el plano de corte (el que se ve cortado).
    - Si no hay ninguno (o es seccion/alzado): el tramo mas largo.
    """
    def longitud(elem):
        return elem.Location.Curve.Length

    cota_corte = cota_plano_corte(view)
    if cota_corte is not None:
        cortados = []
        for elem in vertical:
            curva = elem.Location.Curve
            z0, z1 = curva.GetEndPoint(0).Z, curva.GetEndPoint(1).Z
            if min(z0, z1) <= cota_corte <= max(z0, z1):
                cortados.append(elem)
        if cortados:
            return max(cortados, key=longitud)
    return max(vertical, key=longitud)


def cota_plano_corte(view):
    """Cota Z absoluta (pies) del plano de corte de una planta, o None."""
    try:
        rango = view.GetViewRange()               # Solo existe en ViewPlan
        nivel = doc.GetElement(rango.GetLevelId(PlanViewPlane.CutPlane))
        return (nivel.ProjectElevation
                + rango.GetOffset(PlanViewPlane.CutPlane))
    except Exception:
        return None


# ── Recoleccion de datos ──────────────────────────
def nombre_sistema(elem, kind):
    """Nombre del tipo de sistema del elemento (fallback robusto)."""
    param = elem.get_Parameter(BIP_SISTEMA[kind])
    nombre = param.AsValueString() if param is not None else None
    if not nombre:
        sistema = elem.MEPSystem
        nombre = sistema.Name if sistema is not None else u'(Sin sistema)'
    return nombre


def recolectar_verticales(view):
    """Agrupa los MEP verticales de la vista por familia y tipo de sistema,
    y dentro de cada grupo los reparte por vertical.

    Returns:
        list[dict]: [{'kind': 'pipe'|'duct',
                      'sistema': str,
                      'elems': [Element, ...],
                      'verticales': [[Element, ...], ...]}, ...]
    """
    grupos = {}
    for kind in ('pipe', 'duct'):
        colector = (FilteredElementCollector(doc, view.Id)
                    .OfCategory(BIC_ELEMENTOS[kind])
                    .WhereElementIsNotElementType())
        for elem in colector:
            angulo = angulo_desde_vertical(elem)
            if angulo is None or angulo > TOL_ANGLE_DEG:
                continue
            clave = (kind, nombre_sistema(elem, kind))
            grupos.setdefault(clave, []).append(elem)

    tol_ft = cm_a_pies(TOL_MISMA_VERTICAL_CM)
    orden_kind = {'pipe': 0, 'duct': 1}
    resultado = []
    for (kind, sistema), elems in grupos.items():
        resultado.append({'kind': kind, 'sistema': sistema, 'elems': elems,
                          'verticales': agrupar_por_vertical(elems, view,
                                                             tol_ft)})
    resultado.sort(key=lambda g: (orden_kind[g['kind']],
                                  -len(g['elems']),
                                  g['sistema']))
    return resultado


def obtener_tipos_etiqueta(kind):
    """Tipos de etiqueta cargados -> {'Familia : Tipo': FamilySymbol}.
    Se incluye la familia porque dos familias pueden tener un tipo con el
    mismo nombre (p. ej. 'Standard') y uno pisaria al otro."""
    tipos = {}
    colector = (FilteredElementCollector(doc)
                .OfClass(FamilySymbol)
                .OfCategory(BIC_ETIQUETAS[kind]))
    for sym in colector:
        try:
            nombre_tipo = Element.Name.GetValue(sym)
        except Exception:
            nombre_tipo = sym.Name
        tipos[u'{} : {}'.format(sym.FamilyName, nombre_tipo)] = sym
    return tipos


def ids_elementos_etiquetados(tag):
    """Ids de los elementos etiquetados por una etiqueta (todas las versiones)."""
    try:
        return [valor_id(e) for e in tag.GetTaggedLocalElementIds()]  # 2022+
    except Exception:
        try:
            return [valor_id(tag.TaggedLocalElementId)]               # <2022
        except Exception:
            return []


def ids_ya_etiquetados(view):
    """Ids de elementos que ya tienen alguna etiqueta en la vista."""
    ids = set()
    for tag in (FilteredElementCollector(doc, view.Id)
                .OfClass(IndependentTag)):
        ids.update(ids_elementos_etiquetados(tag))
    return ids


# ── Formulario ────────────────────────────────────
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


def crear_ventana_formulario(grupos, tipos_por_kind, vista_nombre, memoria):
    """Construye el formulario WPF: cabecera y botones fijos, lista de
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

    # --- Pie (fijo, abajo): omitir ya etiquetados + botones -------
    panel_pie = StackPanel()
    panel_pie.Orientation = Orientation.Vertical
    panel_pie.Margin = Thickness(14, 6, 14, 14)
    DockPanel.SetDock(panel_pie, Dock.Bottom)

    sep_pie = Separator()
    sep_pie.Margin = Thickness(0, 0, 0, 10)
    panel_pie.Children.Add(sep_pie)

    chk_skip = CheckBox()
    chk_skip.Content = u'Omitir verticales ya etiquetadas'
    chk_skip.IsChecked = True
    chk_skip.Margin = Thickness(0, 0, 0, 10)
    panel_pie.Children.Add(chk_skip)

    panel_botones = StackPanel()
    panel_botones.Orientation = Orientation.Horizontal
    panel_botones.HorizontalAlignment = HorizontalAlignment.Right

    boton_cancelar = Button()
    boton_cancelar.Content = u'Cancelar'
    boton_cancelar.Padding = Thickness(18, 6, 18, 6)
    boton_cancelar.MinWidth = 110.0
    boton_cancelar.Margin = Thickness(0, 0, 8, 0)
    boton_cancelar.IsCancel = True   # Esc tambien cierra sin hacer nada
    panel_botones.Children.Add(boton_cancelar)

    boton = Button()
    boton.Content = u'✔ Etiquetar'
    boton.Padding = Thickness(18, 6, 18, 6)
    boton.MinWidth = 110.0
    boton.IsDefault = True

    def _on_click(sender, args):
        ventana.DialogResult = True
        ventana.Close()
    boton.Click += _on_click
    panel_botones.Children.Add(boton)

    panel_pie.Children.Add(panel_botones)
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

        texto_grupo = u'{} · {}   ({} elem. → {} etiq.)'.format(
            NOMBRE_KIND[grupo['kind']], grupo['sistema'],
            len(grupo['elems']), len(grupo['verticales']))
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
            nombres = sorted(tipos.keys())
            for nombre in nombres:
                combo.Items.Add(nombre)
            # Preselecciona lo que se eligio la ultima vez para este sistema
            recordado = memoria.get(clave_memoria(grupo))
            combo.SelectedIndex = (nombres.index(recordado)
                                   if recordado in nombres else 0)

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


# ── Anti-solape de cabezas ────────────────────────
# Todo se calcula con rectangulos 2D (umin, umax, vmin, vmax) en los ejes
# de la vista: asi da igual que sea planta, seccion o alzado, y dos
# etiquetas a distinta profundidad pero superpuestas en pantalla tambien
# se detectan como solapadas.
def rect_en_vista(elem, view):
    """Rectangulo 2D de la BoundingBox de 'elem' en la vista, o None."""
    try:
        bbox = elem.get_BoundingBox(view)
    except Exception:
        return None
    if bbox is None:
        return None
    tr = bbox.Transform
    derecha, arriba = view.RightDirection, view.UpDirection
    us, vs = [], []
    for x in (bbox.Min.X, bbox.Max.X):
        for y in (bbox.Min.Y, bbox.Max.Y):
            for z in (bbox.Min.Z, bbox.Max.Z):
                p = tr.OfPoint(XYZ(x, y, z))
                us.append(p.DotProduct(derecha))
                vs.append(p.DotProduct(arriba))
    return (min(us), max(us), min(vs), max(vs))


def rects_solapan(a, b, margen):
    """True si dos rectangulos se solapan o se tocan (con holgura)."""
    return (a[0] - margen <= b[1] and b[0] - margen <= a[1] and
            a[2] - margen <= b[3] and b[2] - margen <= a[3])


def desplazar_rect(rect, du, dv):
    return (rect[0] + du, rect[1] + du, rect[2] + dv, rect[3] + dv)


def punto_2d(punto, view):
    """XYZ -> (u, v) en los ejes de la vista."""
    return (punto.DotProduct(view.RightDirection),
            punto.DotProduct(view.UpDirection))


def medir_cabezas(tags, view):
    """Caja de la CABEZA de cada etiqueta (sin directriz), RELATIVA a su
    TagHeadPosition: (izq, der, abajo, arriba), o None si no se puede medir.

    La caja de una etiqueta puede incluir su directriz, y una directriz en
    diagonal 'ocupa' mucho espacio vacio. Se quitan las directrices dentro de
    una SubTransaction, se mide y se deshace: el modelo queda intacto."""
    st = SubTransaction(doc)
    st.Start()
    try:
        for tag in tags:
            try:
                if tag.HasLeader:
                    tag.HasLeader = False
            except Exception:
                pass
        doc.Regenerate()
        medidas = []
        for tag in tags:
            rect = rect_en_vista(tag, view)
            if rect is None:
                medidas.append(None)
                continue
            hu, hv = punto_2d(tag.TagHeadPosition, view)
            medidas.append((rect[0] - hu, rect[1] - hu,
                            rect[2] - hv, rect[3] - hv))
        return medidas
    finally:
        st.RollBack()


def generar_candidatos(view):
    """Desplazamientos (du, dv) en pies, en ejes de la vista, ordenados de
    menor a mayor distancia: siempre se prefiere el hueco mas cercano.
    Nunca mas lejos que MAX_DESPLAZAMIENTO_PAPEL_MM."""
    maximo = papel_a_pies(MAX_DESPLAZAMIENTO_PAPEL_MM, view) * 1.0001
    candidatos = [(0.0, 0.0)]
    for paso_mm in MOV_PASOS_PAPEL_MM:
        paso_ft = papel_a_pies(paso_mm, view)
        for dx, dy in MOV_DIRECCIONES:
            du, dv = dx * paso_ft, dy * paso_ft
            if math.hypot(du, dv) <= maximo:
                candidatos.append((du, dv))
    candidatos.sort(key=lambda c: math.hypot(c[0], c[1]))   # sort estable
    return candidatos


def segmentos_cruzan(p1, p2, q1, q2):
    """True si el segmento p1-p2 cruza el q1-q2 (cruce propio, en 2D)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (orient(q1, q2, p1) * orient(q1, q2, p2) < 0 and
            orient(p1, p2, q1) * orient(p1, p2, q2) < 0)


def agrupar_por_zona(items, radio):
    """Reparte las etiquetas en zonas: cada una se une a la zona cuyo centro
    queda mas cerca (si esta a menos de 'radio'); si no, abre una zona nueva.
    El radio acota el tamano de la zona, asi no se encadenan zonas enormes."""
    zonas = []   # [{'centro': (u, v), 'items': [...]}]
    for item in sorted(items, key=lambda it: it['ancla']):
        au, av = item['ancla']
        mejor, mejor_dist = None, radio
        for zona in zonas:
            dist = math.hypot(au - zona['centro'][0], av - zona['centro'][1])
            if dist <= mejor_dist:
                mejor, mejor_dist = zona, dist
        if mejor is None:
            zonas.append({'centro': (au, av), 'items': [item]})
        else:
            mejor['items'].append(item)
            n = float(len(mejor['items']))
            cu, cv = mejor['centro']
            mejor['centro'] = (cu + (au - cu) / n, cv + (av - cv) / n)
    return [zona['items'] for zona in zonas]


def maquetar_columna(items, lado, separacion_ft, hueco_ft, du=0.0, dv=0.0):
    """Coloca las cabezas de una zona en UNA columna alineada a la derecha
    (lado=1) o a la izquierda (lado=-1) de sus elementos, desplazada (du, dv)
    respecto a su posicion natural.

    Las directrices van de cada elemento al borde de la columna. Si dos se
    cruzan, se intercambian sus huecos: eso acorta siempre la longitud total,
    asi que el bucle termina y, como todos los elementos quedan al mismo lado
    de la columna (du nunca va hacia ellos), termina SIN cruces. El orden se
    calcula con la posicion FINAL de la columna: si se calculara antes de
    desplazarla, al moverla podrian volver a cruzarse.

    Returns:
        list[(item, rect, cabeza, enganche)] en coordenadas 2D de la vista.
    """
    anclas_u = [it['ancla'][0] for it in items]
    x_col = (max(anclas_u) + separacion_ft if lado > 0
             else min(anclas_u) - separacion_ft) + du
    alto_hueco = max(it['medida'][3] - it['medida'][2] for it in items)
    paso = alto_hueco + hueco_ft
    n = len(items)
    centro_v = sum(it['ancla'][1] for it in items) / float(n) + dv
    techo = centro_v + (n * paso - hueco_ft) / 2.0
    v_huecos = [techo - alto_hueco / 2.0 - k * paso for k in range(n)]

    # Orden inicial: de arriba abajo, igual que los elementos
    asignacion = sorted(items, key=lambda it: -it['ancla'][1])

    def directriz(k):
        return asignacion[k]['ancla'], (x_col, v_huecos[k])

    for _ in range(MAX_ITER_DESCRUCE):
        hubo_cruce = False
        for a in range(n):
            for b in range(a + 1, n):
                pa, qa = directriz(a)
                pb, qb = directriz(b)
                if segmentos_cruzan(pa, qa, pb, qb):
                    asignacion[a], asignacion[b] = asignacion[b], asignacion[a]
                    hubo_cruce = True
        if not hubo_cruce:
            break

    resultado = []
    for k, item in enumerate(asignacion):
        izq, der, abajo, arriba = item['medida']
        ancho, alto = der - izq, arriba - abajo
        borde_izq = x_col if lado > 0 else x_col - ancho
        vc = v_huecos[k]
        rect = (borde_izq, borde_izq + ancho, vc - alto / 2.0, vc + alto / 2.0)
        cabeza = (borde_izq - izq, vc - (abajo + arriba) / 2.0)
        resultado.append((item, rect, cabeza, (x_col, vc)))
    return resultado


def inflar_rect(rect, d):
    return (rect[0] - d, rect[1] + d, rect[2] - d, rect[3] + d)


def segmento_toca_rect(p, q, rect):
    """True si el segmento p-q toca el rectangulo (recorte de Liang-Barsky)."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, p[0] - rect[0]), (dx, rect[1] - p[0]),
                   (-dy, p[1] - rect[2]), (dy, rect[3] - p[1])):
        if abs(pk) < 1e-12:
            if qk < 0:
                return False   # Paralelo y fuera
        else:
            t = qk / pk
            if pk < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


class MapaOcupacion(object):
    """Lo que ya ocupa sitio en la vista, indexado en una rejilla para no
    comparar cada etiqueta con miles de elementos. Cada forma es un
    rectangulo o un segmento con grosor (una canalizacion en diagonal NO se
    aproxima por su caja, que seria enorme)."""

    MAX_CELDAS = 20000   # Formas mas grandes se comprueban siempre, sin rejilla

    def __init__(self, celda):
        self.celda = celda
        self.formas = []      # ('r', rect) | ('s', p, q, semiancho)
        self.rejilla = {}     # (i, j) -> [indices de formas]
        self.grandes = []     # indices de formas demasiado grandes

    def _celdas(self, rect):
        c = self.celda
        i0, i1 = int(math.floor(rect[0] / c)), int(math.floor(rect[1] / c))
        j0, j1 = int(math.floor(rect[2] / c)), int(math.floor(rect[3] / c))
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def _indexar(self, idx, rect):
        c = self.celda
        num = ((rect[1] - rect[0]) / c + 1) * ((rect[3] - rect[2]) / c + 1)
        if num > self.MAX_CELDAS:
            if idx not in self.grandes:
                self.grandes.append(idx)
            return
        for clave in self._celdas(rect):
            self.rejilla.setdefault(clave, []).append(idx)

    def agregar_rect(self, rect):
        self.formas.append(('r', rect))
        self._indexar(len(self.formas) - 1, rect)

    def agregar_segmento(self, p, q, semiancho):
        idx = len(self.formas)
        self.formas.append(('s', p, q, semiancho))
        # Se indexa a trozos del tamaño de una celda: asi solo ocupa las
        # celdas por las que pasa, no todo su rectangulo envolvente
        n = max(1, int(math.ceil(math.hypot(q[0] - p[0], q[1] - p[1])
                                 / self.celda)))
        for k in range(n):
            a0, a1 = k / float(n), (k + 1) / float(n)
            ua, va = p[0] + (q[0] - p[0]) * a0, p[1] + (q[1] - p[1]) * a0
            ub, vb = p[0] + (q[0] - p[0]) * a1, p[1] + (q[1] - p[1]) * a1
            self._indexar(idx, inflar_rect((min(ua, ub), max(ua, ub),
                                            min(va, vb), max(va, vb)),
                                           semiancho))

    def choques(self, rect, margen):
        """Numero de formas que tapa 'rect' (dejando 'margen' libre)."""
        vistos = set(self.grandes)
        candidatos = list(self.grandes)
        for clave in self._celdas(inflar_rect(rect, margen)):
            for idx in self.rejilla.get(clave, ()):
                if idx not in vistos:
                    vistos.add(idx)
                    candidatos.append(idx)
        total = 0
        for idx in candidatos:
            forma = self.formas[idx]
            if forma[0] == 'r':
                if rects_solapan(rect, forma[1], margen):
                    total += 1
            elif segmento_toca_rect(forma[1], forma[2],
                                    inflar_rect(rect, forma[3] + margen)):
                total += 1
        return total


def trazado_visible(elem, view):
    """Canalizacion recta como (p, q, semiancho) en 2D, o None si no lo es
    (p. ej. un flexible): entonces se usa su caja."""
    loc = elem.Location
    if not isinstance(loc, LocationCurve) or not isinstance(loc.Curve, Line):
        return None
    # Rectangulares: el mayor de ancho/alto (en seccion se ve el alto)
    grosor = 0.0
    for bip in BIPS_GROSOR:
        param = elem.get_Parameter(bip)
        if param is not None and param.HasValue:
            grosor = max(grosor, param.AsDouble())
    curva = loc.Curve
    return (punto_2d(curva.GetEndPoint(0), view),
            punto_2d(curva.GetEndPoint(1), view), grosor / 2.0)


def registrar_redes(view, mapa):
    """Añade al mapa las redes del modelo NATIVO visibles en la vista
    (tuberias, conductos, bandejas y tubos), con su trazado real."""
    for nombre in CATEGORIAS_REDES:
        bic = getattr(BuiltInCategory, nombre, None)
        if bic is None:
            continue
        for elem in (FilteredElementCollector(doc, view.Id).OfCategory(bic)
                     .WhereElementIsNotElementType()):
            try:
                trazado = trazado_visible(elem, view)
            except Exception:
                trazado = None
            if trazado is not None:
                mapa.agregar_segmento(*trazado)
                continue
            rect = rect_en_vista(elem, view)
            if rect is not None:
                mapa.agregar_rect(rect)


def maquetar_etiquetas(tags_y_anclas, view):
    """Agrupa las etiquetas nuevas por zona y coloca cada zona en una columna
    alineada, con directrices que no se cruzan y sin tapar redes (tuberias,
    conductos, bandejas, tubos), etiquetas que ya existian ni los elementos.
    Una columna nunca se aleja mas de MAX_DESPLAZAMIENTO_PAPEL_MM.

    Cada columna se mueve como un bloque (se prueban desplazamientos con
    aritmetica, sin regenerar el modelo) y al final cada etiqueta se mueve
    UNA sola vez.

    Returns:
        tuple: (num_zonas, cruces_restantes)
    """
    if not tags_y_anclas:
        return 0, 0

    doc.Regenerate()
    margen = papel_a_pies(MARGEN_SOLAPE_PAPEL_MM, view)
    separacion = papel_a_pies(OFFSET_PAPEL_MM, view)
    hueco = papel_a_pies(SEPARACION_FILAS_PAPEL_MM, view)
    radio_elem = papel_a_pies(RADIO_ELEMENTO_PAPEL_MM, view)
    tags = [t for t, _ in tags_y_anclas]
    ids_nuevas = set(valor_id(t.Id) for t in tags)

    medidas = medir_cabezas(tags, view)
    items = []
    for (tag, ancla), medida in zip(tags_y_anclas, medidas):
        if medida is not None:
            items.append({'tag': tag, 'ancla': punto_2d(ancla, view),
                          'medida': medida})

    # Obstaculos fijos: redes del modelo, etiquetas que ya existian y los
    # propios elementos etiquetados
    ocupado = MapaOcupacion(papel_a_pies(CELDA_MAPA_PAPEL_MM, view))
    registrar_redes(view, ocupado)
    for otra in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        if valor_id(otra.Id) not in ids_nuevas:
            rect = rect_en_vista(otra, view)
            if rect is not None:
                ocupado.agregar_rect(rect)
    for item in items:
        au, av = item['ancla']
        ocupado.agregar_rect((au - radio_elem, au + radio_elem,
                              av - radio_elem, av + radio_elem))

    directrices = []   # [(ancla, enganche)] de las columnas ya colocadas
    candidatos = generar_candidatos(view)
    zonas = agrupar_por_zona(items,
                             papel_a_pies(RADIO_ZONA_PAPEL_MM, view))
    zonas.sort(key=len, reverse=True)   # Las mas grandes primero

    for zona in zonas:
        bases = dict((lado, maquetar_columna(zona, lado, separacion, hueco))
                     for lado in (1, -1))
        mejor = None
        for du, dv in candidatos:
            for lado in (1, -1):
                if du * lado < 0:
                    continue   # Nunca hacia los elementos: se cruzarian
                choques = cruces = 0
                for item, rect, _, (eu, ev) in bases[lado]:
                    choques += ocupado.choques(desplazar_rect(rect, du, dv),
                                               margen)
                    seg = (item['ancla'], (eu + du, ev + dv))
                    cruces += sum(1 for a, b in directrices
                                  if segmentos_cruzan(seg[0], seg[1], a, b))
                coste = (choques, cruces, math.hypot(du, dv))
                if mejor is None or coste < mejor[0]:
                    mejor = (coste, lado, du, dv)
            if mejor[0][0] == 0 and mejor[0][1] == 0:
                break   # Hueco libre y sin cruces: el mas cercano posible

        # Se recoloca la columna en su posicion final y se vuelve a ordenar
        # para que, ya desplazada, sus directrices sigan sin cruzarse
        _, lado, du, dv = mejor
        for item, rect, cabeza, enganche in maquetar_columna(
                zona, lado, separacion, hueco, du, dv):
            ocupado.agregar_rect(rect)
            directrices.append((item['ancla'], enganche))
            item['cabeza'] = cabeza

    # Aplicar: cada etiqueta se mueve una sola vez
    derecha, arriba = view.RightDirection, view.UpDirection
    for item in items:
        tag = item['tag']
        hu0, hv0 = punto_2d(tag.TagHeadPosition, view)
        hu, hv = item['cabeza']
        tag.TagHeadPosition = (tag.TagHeadPosition
                               + derecha * (hu - hu0) + arriba * (hv - hv0))

    cruces = 0
    for i in range(len(directrices)):
        for j in range(i + 1, len(directrices)):
            if segmentos_cruzan(directrices[i][0], directrices[i][1],
                                directrices[j][0], directrices[j][1]):
                cruces += 1
    return len(zonas), cruces


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
memoria = cargar_memoria()
ventana, filas, chk_skip = crear_ventana_formulario(grupos, tipos_por_kind,
                                                    view.Name, memoria)
if ventana.ShowDialog() is not True:
    script.exit()   # Cerrado con X, Esc o Cancelar -> salir sin tocar nada

# --- Selecciones del usuario -----------------------------------
omitir_etiquetados = bool(chk_skip.IsChecked)
ya_etiquetados = ids_ya_etiquetados(view) if omitir_etiquetados else set()

objetivos = []   # [(Element, FamilySymbol), ...] -> uno por vertical
omitidas = fusionados = 0
for fila in filas:
    if not fila['checkbox'].IsChecked:
        continue
    nombre_sel = fila['combo'].SelectedItem
    simbolo = fila['tipos'].get(nombre_sel) if nombre_sel else None
    if simbolo is None:
        continue
    memoria[clave_memoria(fila['grupo'])] = nombre_sel
    for vertical in fila['grupo']['verticales']:
        # Si CUALQUIER tramo de la vertical ya tiene etiqueta, la vertical
        # entera cuenta como etiquetada (si no, se duplicaria la etiqueta)
        if any(valor_id(e.Id) in ya_etiquetados for e in vertical):
            omitidas += 1
            continue
        objetivos.append((elegir_representante(vertical, view), simbolo))
        fusionados += len(vertical) - 1

guardar_memoria(memoria)

if not objetivos:
    if omitidas:
        alerta(u'Todas las verticales marcadas ya estaban etiquetadas '
               u'({}).'.format(omitidas))
    else:
        alerta(u'No hay ningun grupo marcado para etiquetar.')
    script.exit()

offset_ft = papel_a_pies(OFFSET_PAPEL_MM, view)
# Posicion provisional de la cabeza (luego la maquetacion por zonas la
# recoloca). Ejes de la VISTA: en una seccion la Y del modelo es profundidad.
vector_offset = (view.RightDirection + view.UpDirection) * offset_ft

# --- Creacion de etiquetas (UNA transaccion) --------------------
creadas = fallidas = num_zonas = cruces = 0
fallo_maquetacion = None
activados = set()   # Ids de FamilySymbol ya activados
tags_creados = []   # [(IndependentTag, punto de anclaje XYZ), ...]

t = Transaction(doc, u'Etiquetar CVC')
t.Start()
try:
    for elem, simbolo in objetivos:
        try:
            sid = valor_id(simbolo.Id)
            if sid not in activados and not simbolo.IsActive:
                simbolo.Activate()
            activados.add(sid)

            medio = punto_medio(elem)
            tag = IndependentTag.Create(doc, simbolo.Id, view.Id,
                                        Reference(elem), True,
                                        TagOrientation.Horizontal, medio)
            tag.TagHeadPosition = medio + vector_offset
            tags_creados.append((tag, medio))
            creadas += 1
        except Exception as ex:
            fallidas += 1
            print(u'⚠ Fallo etiquetando elemento {}: {}'.format(
                valor_id(elem.Id), ex))

    # --- Maquetacion en su propia SubTransaction: si falla, se deshace
    #     solo la maquetacion y las etiquetas creadas se conservan.
    st = SubTransaction(doc)
    st.Start()
    try:
        num_zonas, cruces = maquetar_etiquetas(tags_creados, view)
        st.Commit()
    except Exception as ex:
        st.RollBack()
        num_zonas = cruces = 0
        fallo_maquetacion = ex

    t.Commit()
except Exception:
    t.RollBack()
    raise

resumen = (u'✅ Etiquetas creadas: {}\n'
           u'🔗 Tramos en la misma vertical (sin etiqueta extra): {}\n'
           u'▦ Zonas (columnas de etiquetas alineadas): {}\n'
           u'✖ Cruces de directrices restantes: {}\n'
           u'⏭ Omitidas (ya etiquetadas): {}\n'
           u'⚠ Fallos: {}').format(creadas, fusionados, num_zonas, cruces,
                                   omitidas, fallidas)
if fallo_maquetacion is not None:
    resumen += u'\n\n⚠ No se pudo alinear las etiquetas: {}'.format(
        fallo_maquetacion)
print(resumen)
alerta(resumen)

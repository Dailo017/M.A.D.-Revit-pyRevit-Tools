# -*- coding: utf-8 -*-
__title__   = "TagPLBG"
__doc__     = """Version = 1.4
Date    = 17.10.2026
________________________________________________________________
Description:

Etiqueta todas las tuberias y conductos VERTICALES de la vista activa,
agrupados por tipo de sistema.

Muestra un formulario con una fila por cada sistema detectado para
elegir que tipo de etiqueta se aplica a cada grupo. Las etiquetas se
crean SIN directriz (leader), centradas en el punto medio del elemento.

Si varios elementos del MISMO sistema estan en la misma vertical
(misma posicion en planta), solo se etiqueta uno de ellos.

Para que las etiquetas no se crucen, se lee de la familia la parte
visible de cada tipo (flecha, simbolos y texto) y cada etiqueta nueva
se gira 0°, +7°, -7°, +14°... alrededor de su punto hasta que no toca
a ninguna otra (nueva o ya existente en la vista), sin dejar nunca el
texto boca abajo. Los cruces junto a la cabeza, donde convergen las
flechas, no cuentan. Si no hay hueco, se usa el giro con menos cruces.

El formulario tiene una altura maxima (85% de la pantalla) y una barra
de desplazamiento vertical para la lista de sistemas: el boton
"Etiquetar" queda siempre visible, fijo en la parte inferior. Ademas
la ventana se puede redimensionar a mano.

La verticalidad se comprueba con una tolerancia de 10 grados para
tolerar pequeños errores de modelizacion.
________________________________________________________________
How-To:

- Abre una vista 2D (planta, seccion o alzado).
- Pulsa el boton: aparecera un grupo por cada sistema vertical detectado.
- Marca los grupos que quieras etiquetar y elige su tipo de etiqueta,
  o "— No tag —" para no colocar etiquetas en ese sistema.
- Aceptar -> crea todas las etiquetas en UNA sola transaccion (un solo Undo).
________________________________________________________________
Last Updates:
- [17.10.2026] v1.4 "No tag" option per system in the form
- [17.10.2026] v1.3 Rotation chosen from the visible tag geometry
               (arrow, symbols, text) so tags do not cross
- [17.10.2026] v1.2 One tag per vertical and system; overlapping tags
               are fanned out by rotation
- [05.10.2026] v1.1 Transaction is rolled back if something fails
- [25.08.2026] v1.0 First release
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
OFFSET_CM        = 0.0    # Desplazamiento de la cabeza de la etiqueta (cm)
MIN_CURVE_LEN_FT = 1e-6    # Longitud minima de curva valida (pies)
TOL_MISMA_VERTICAL_CM = 2.0   # Distancia en planta para "misma vertical"
PASO_ROTACION_DEG     = 7.0   # Giro entre etiquetas solapadas (grados)
MARGEN_MM             = 0.3   # Separacion minima entre etiquetas (mm papel)
ZONA_LIBRE_MM         = 1.5   # Radio junto a la cabeza donde se permite cruce
ANCHO_CARACTER        = 0.8   # Ancho medio de caracter / altura de texto
MM_POR_PIE            = 304.8
TITULO_FORM      = u'Etiquetar Verticales'
NO_ETIQUETAR     = u'— No tag —'   # Opcion del desplegable de sistema

ANCHO_VENTANA       = 540.0
ALTO_MIN_VENTANA    = 340.0
ALTO_MAX_PORCENTAJE = 0.85   # % de la altura de pantalla disponible
ALTO_POR_FILA       = 68.0   # estimacion px por fila (checkbox + combo)
ALTO_POR_SECCION    = 40.0   # estimacion px por cabecera de seccion
ALTO_FIJO_FORM      = 210.0  # cabecera + pie (skip + boton) estimados

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


def punto_medio(elem):
    """Punto medio de la curva del elemento."""
    curva = elem.Location.Curve
    return (curva.GetEndPoint(0) + curva.GetEndPoint(1)) * 0.5


def distancia_xy(a, b):
    """Distancia en planta (ignora Z) entre dos XYZ."""
    return math.hypot(a.X - b.X, a.Y - b.Y)


def agrupar_cercanos(items, tol):
    """Agrupa items [(XYZ, obj), ...] encadenando los que esten a <= tol
    en planta. Conserva el orden original dentro de cada grupo."""
    grupos = []   # listas de indices de items
    for i, item in enumerate(items):
        cercanos = [g for g in grupos
                    if any(distancia_xy(item[0], items[j][0]) <= tol
                           for j in g)]
        nuevo = [i]
        for g in cercanos:
            nuevo.extend(g)
            grupos.remove(g)
        grupos.append(sorted(nuevo))
    return [[items[j] for j in g] for g in grupos]


# ── Huella visible de las etiquetas ───────────────
# Geometria en mm de papel, en el sistema local de la familia de etiqueta
# (origen = cabeza de la etiqueta). Segmentos = [((x1, y1), (x2, y2)), ...]

def _visible_en_tipo(elem, fm, tipo):
    """True si el elemento de la familia se ve en ese tipo (parametro de
    visibilidad propio o asociado a un parametro de familia)."""
    param = elem.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
    if param is None:
        return True
    param_fam = fm.GetAssociatedFamilyParameter(param)
    if param_fam is not None and tipo is not None and tipo.HasValue(param_fam):
        return tipo.AsInteger(param_fam) == 1
    return param.AsInteger() == 1


def _segmentos_curva(curva):
    """Curva de familia -> segmentos en mm (arcos teselados)."""
    pts = [(p.X * MM_POR_PIE, p.Y * MM_POR_PIE) for p in curva.Tessellate()]
    return list(zip(pts, pts[1:]))


def leer_huellas(simbolos):
    """Lee de cada familia de etiqueta las lineas, regiones rellenas y
    textos VISIBLES de cada tipo -> {id simbolo: {'segs', 'textos'}}.
    Abre cada familia una sola vez (EditFamily, sin transaccion abierta)."""
    huellas = {}
    por_familia = {}
    for sym in simbolos:
        por_familia.setdefault(valor_id(sym.Family.Id), []).append(sym)
    id_sketch = int(BuiltInCategory.OST_SketchLines)

    for syms in por_familia.values():
        try:
            fdoc = doc.EditFamily(syms[0].Family)
        except Exception as ex:
            print(u'⚠ No se pudo leer la familia {}: {}'.format(
                syms[0].Family.Name, ex))
            continue
        try:
            fm = fdoc.FamilyManager
            tipos = dict((ft.Name, ft) for ft in fm.Types)
            elems = list(FilteredElementCollector(fdoc)
                         .WhereElementIsNotElementType().ToElements())
            for sym in syms:
                tipo = tipos.get(Element.Name.GetValue(sym))
                segs, textos = [], []
                for e in elems:
                    if isinstance(e, CurveElement):
                        if (e.Category is not None
                                and valor_id(e.Category.Id) == id_sketch):
                            continue   # contorno de region: se lee abajo
                        if _visible_en_tipo(e, fm, tipo):
                            segs.extend(_segmentos_curva(e.GeometryCurve))
                    elif isinstance(e, FilledRegion):
                        if _visible_en_tipo(e, fm, tipo):
                            for bucle in e.GetBoundaries():
                                for curva in bucle:
                                    segs.extend(_segmentos_curva(curva))
                    elif isinstance(e, TextElement):
                        if not _visible_en_tipo(e, fm, tipo):
                            continue
                        tipo_txt = fdoc.GetElement(e.GetTypeId())
                        textos.append({
                            'x': e.Coord.X * MM_POR_PIE,
                            'y': e.Coord.Y * MM_POR_PIE,
                            'base': (e.BaseDirection.X, e.BaseDirection.Y),
                            'h': str(e.HorizontalAlignment),
                            'v': str(e.VerticalAlignment),
                            'size': tipo_txt.get_Parameter(
                                BuiltInParameter.TEXT_SIZE).AsDouble()
                                * MM_POR_PIE,
                            'escala': tipo_txt.get_Parameter(
                                BuiltInParameter.TEXT_WIDTH_SCALE).AsDouble(),
                        })
                huellas[valor_id(sym.Id)] = {'segs': segs, 'textos': textos}
        finally:
            fdoc.Close(False)
    return huellas


def _rectangulo_texto(t, texto):
    """Caja aproximada del texto (bordes + diagonales) en mm locales."""
    ancho = max(1, len(texto)) * t['size'] * t['escala'] * ANCHO_CARACTER
    alto = t['size']
    x0 = {'Left': 0.0, 'Center': -ancho / 2.0}.get(t['h'], -ancho)
    y0 = {'Bottom': 0.0, 'Top': -alto}.get(t['v'], -alto / 2.0)
    bx, by = t['base']
    ux, uy = -by, bx
    esq = [(t['x'] + bx * a + ux * b, t['y'] + by * a + uy * b)
           for a, b in ((x0, y0), (x0 + ancho, y0),
                        (x0 + ancho, y0 + alto), (x0, y0 + alto))]
    return [(esq[0], esq[1]), (esq[1], esq[2]), (esq[2], esq[3]),
            (esq[3], esq[0]), (esq[0], esq[2]), (esq[1], esq[3])]


def _recortar_origen(seg, radio):
    """Quita la parte del segmento dentro del circulo de radio dado
    alrededor de la cabeza: ahi convergen todas las flechas y no cuenta
    como cruce. None si el segmento queda entero dentro."""
    (x1, y1), (x2, y2) = seg
    d1, d2 = math.hypot(x1, y1), math.hypot(x2, y2)
    if d1 >= radio and d2 >= radio:
        return seg
    if d1 < radio and d2 < radio:
        return None
    if d1 < radio:   # el extremo interior pasa a ser el segundo
        (x1, y1), (x2, y2) = (x2, y2), (x1, y1)
    # Punto del segmento a distancia 'radio' del origen
    dx, dy = x2 - x1, y2 - y1
    a = dx * dx + dy * dy
    b = 2 * (x1 * dx + y1 * dy)
    c = x1 * x1 + y1 * y1 - radio * radio
    raiz = math.sqrt(max(0.0, b * b - 4 * a * c))
    t = (-b - raiz) / (2 * a)
    return ((x1, y1), (x1 + dx * t, y1 + dy * t))


def huella_local(huella, texto):
    """Segmentos visibles de una etiqueta con su texto real (mm locales)."""
    if huella is None:
        return []
    segs = list(huella['segs'])
    for t in huella['textos']:
        segs.extend(_rectangulo_texto(t, texto or u''))
    res = []
    for seg in segs:
        recortado = _recortar_origen(seg, ZONA_LIBRE_MM)
        if recortado is not None:
            res.append(recortado)
    return res


def huella_modelo(segs_mm, cabeza, angulo, ejes, mm_a_pies):
    """Coloca la huella local en planta: cabeza + giro respecto a la vista.
    Devuelve (bbox, segmentos) en pies."""
    (rx, ry), (vx, vy) = ejes
    c, s = math.cos(angulo), math.sin(angulo)
    ax, ay = (c * rx + s * vx) * mm_a_pies, (c * ry + s * vy) * mm_a_pies
    bx, by = (c * vx - s * rx) * mm_a_pies, (c * vy - s * ry) * mm_a_pies
    hx, hy = cabeza
    segs = []
    for (x1, y1), (x2, y2) in segs_mm:
        segs.append(((hx + x1 * ax + y1 * bx, hy + x1 * ay + y1 * by),
                     (hx + x2 * ax + y2 * bx, hy + x2 * ay + y2 * by)))
    if not segs:
        return None
    xs = [p[0] for sg in segs for p in sg]
    ys = [p[1] for sg in segs for p in sg]
    return ((min(xs), min(ys), max(xs), max(ys)), segs)


def _dist_punto_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx
                                                + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segs_cerca(s1, s2, margen):
    """True si dos segmentos se cruzan o quedan a menos de 'margen'."""
    a, b = s1
    c, d = s2
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    return min(_dist_punto_seg(a, c, d), _dist_punto_seg(b, c, d),
               _dist_punto_seg(c, a, b), _dist_punto_seg(d, a, b)) < margen


def huellas_chocan(h1, h2, margen):
    """True si alguna parte visible de una etiqueta toca la de la otra."""
    (ax0, ay0, ax1, ay1), segs1 = h1
    (bx0, by0, bx1, by1), segs2 = h2
    if (ax0 > bx1 + margen or bx0 > ax1 + margen
            or ay0 > by1 + margen or by0 > ay1 + margen):
        return False
    for s1 in segs1:
        for s2 in segs2:
            if _segs_cerca(s1, s2, margen):
                return True
    return False


def angulo_de_etiqueta(tag):
    """Giro de la etiqueta respecto a la vista (radianes)."""
    if tag.TagOrientation == TagOrientation.Vertical:
        return math.pi / 2.0
    if tag.TagOrientation == TagOrientation.AnyModelDirection:
        return tag.RotationAngle
    return 0.0


def etiquetas_mep_existentes(view):
    """Etiquetas de tuberia/conducto ya colocadas en la vista."""
    cats = set(int(b) for b in BIC_ETIQUETAS.values())
    return [tag for tag in (FilteredElementCollector(doc, view.Id)
                            .OfClass(IndependentTag).ToElements())
            if tag.Category is not None
            and valor_id(tag.Category.Id) in cats]


def angulos_candidatos(huella):
    """Giros a probar (radianes): 0, +paso, -paso, +2*paso, -2*paso...
    descartando los que dejarian algun texto boca abajo."""
    bases = []
    if huella is not None:
        bases = [math.degrees(math.atan2(t['base'][1], t['base'][0]))
                 for t in huella['textos']]

    def legible(giro):
        for base in bases:
            d = (base + giro + 180.0) % 360.0 - 180.0
            if d > 90.0 + 1e-6 or d < -90.0 - 1e-6:
                return False
        return True

    grados = [0.0]
    for i in range(1, int(180.0 / PASO_ROTACION_DEG) + 1):
        grados += [i * PASO_ROTACION_DEG, -i * PASO_ROTACION_DEG]
    return [math.radians(g % 360.0) for g in grados if legible(g)]


def elegir_angulo(segs_mm, candidatos, cabeza, obstaculos, ejes, mm_a_pies,
                  margen):
    """Primer giro candidato con el que la etiqueta no toca a ninguna otra.
    Si todos chocan, el que menos choques tiene.
    Devuelve (angulo, huella_modelo, choques)."""
    if not segs_mm:
        return 0.0, None, 0
    # Solo cuentan los obstaculos al alcance de la etiqueta
    hx, hy = cabeza
    alcance = (max(math.hypot(x, y) for seg in segs_mm for x, y in seg)
               * mm_a_pies + margen)
    cerca = [o for o in obstaculos
             if o[0][0] <= hx + alcance and o[0][2] >= hx - alcance
             and o[0][1] <= hy + alcance and o[0][3] >= hy - alcance]
    mejor = None
    for angulo in candidatos:
        h = huella_modelo(segs_mm, cabeza, angulo, ejes, mm_a_pies)
        choques = sum(1 for o in cerca if huellas_chocan(h, o, margen))
        if choques == 0:
            return angulo, h, 0
        if mejor is None or choques < mejor[2]:
            mejor = (angulo, h, choques)
    return mejor


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


def enlazar_no_etiquetar(chk, combo):
    """Sincroniza la casilla y el desplegable: elegir "No etiquetar"
    desmarca la casilla; volver a marcarla elige el primer tipo."""
    def _on_combo(sender, args):
        if combo.SelectedItem == NO_ETIQUETAR:
            chk.IsChecked = False

    def _on_check(sender, args):
        if combo.SelectedItem == NO_ETIQUETAR:
            combo.SelectedIndex = 1
    combo.SelectionChanged += _on_combo
    chk.Checked += _on_check


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
            combo.Items.Add(NO_ETIQUETAR)
            for nombre in sorted(tipos.keys()):
                combo.Items.Add(nombre)
            combo.SelectedIndex = 1   # primer tipo de etiqueta real

            enlazar_no_etiquetar(chk, combo)

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

def cm_a_pies(cm):
    return UnitUtils.ConvertToInternalUnits(cm, UnitTypeId.Centimeters)

offset_ft = cm_a_pies(OFFSET_CM)
tol_vertical_ft = cm_a_pies(TOL_MISMA_VERTICAL_CM)
mm_a_pies = view.Scale / MM_POR_PIE          # mm de papel -> pies modelo
margen_ft = MARGEN_MM * mm_a_pies
ejes_vista = ((view.RightDirection.X, view.RightDirection.Y),
              (view.UpDirection.X, view.UpDirection.Y))

# Una sola etiqueta por vertical y sistema: los elementos del mismo
# sistema en la misma posicion en planta se agrupan y se etiqueta uno.
omitidas = suprimidas = 0
objetivos = []   # [{'elem', 'simbolo', 'punto'}, ...]
for fila in filas:
    if not fila['checkbox'].IsChecked:
        continue
    nombre_sel = fila['combo'].SelectedItem
    if not nombre_sel or nombre_sel == NO_ETIQUETAR:
        continue
    simbolo = fila['tipos'].get(nombre_sel)
    if simbolo is None:
        continue
    items = [(punto_medio(e), e) for e in fila['grupo']['elems']]
    for vertical in agrupar_cercanos(items, tol_vertical_ft):
        if any(valor_id(e.Id) in ya_etiquetados for _, e in vertical):
            omitidas += len(vertical)
            continue
        suprimidas += len(vertical) - 1
        punto, elem = vertical[0]
        objetivos.append({'elem': elem, 'simbolo': simbolo, 'punto': punto})

if not objetivos:
    if omitidas:
        alerta(u'Todos los elementos marcados ya estan etiquetados.')
    else:
        alerta(u'No hay ningun grupo marcado para etiquetar.')
    script.exit()

# --- Huella visible de las etiquetas (antes de la transaccion) ---
existentes = etiquetas_mep_existentes(view)
simbolos = {}
for obj in objetivos:
    simbolos[valor_id(obj['simbolo'].Id)] = obj['simbolo']
for tag in existentes:
    simbolos.setdefault(valor_id(tag.GetTypeId()), doc.GetElement(tag.GetTypeId()))
huellas = leer_huellas(simbolos.values())

# Obstaculos: parte visible de las etiquetas ya colocadas en la vista
obstaculos = []
for tag in existentes:
    segs_mm = huella_local(huellas.get(valor_id(tag.GetTypeId())), tag.TagText)
    cabeza = tag.TagHeadPosition
    h = huella_modelo(segs_mm, (cabeza.X, cabeza.Y), angulo_de_etiqueta(tag),
                      ejes_vista, mm_a_pies)
    if h is not None:
        obstaculos.append(h)

# --- Creacion de etiquetas (UNA transaccion) --------------------
# Cada etiqueta nueva se gira 0°, 7°, 14°... hasta que su parte visible
# (flecha, simbolos y texto) no toque la de ninguna otra etiqueta.
creadas = rotadas = sin_hueco = fallidas = 0
activados = set()   # Ids de FamilySymbol ya activados
candidatos = {}     # Id de FamilySymbol -> giros a probar

t = Transaction(doc, u'Etiquetar verticales')
t.Start()
try:
    for obj in objetivos:
        elem, simbolo, medio = obj['elem'], obj['simbolo'], obj['punto']
        try:
            sid = valor_id(simbolo.Id)
            if sid not in activados and not simbolo.IsActive:
                simbolo.Activate()
            activados.add(sid)

            # addLeader = False -> etiqueta sin linea de directriz (repere)
            tag = IndependentTag.Create(doc, simbolo.Id, view.Id,
                                        Reference(elem), False,
                                        TagOrientation.Horizontal, medio)
            tag.HasLeader = False
            cabeza = XYZ(medio.X + offset_ft, medio.Y + offset_ft, medio.Z)
            tag.TagHeadPosition = cabeza

            huella = huellas.get(sid)
            if sid not in candidatos:
                candidatos[sid] = angulos_candidatos(huella)
            segs_mm = huella_local(huella, tag.TagText)
            angulo, h, choques = elegir_angulo(
                segs_mm, candidatos[sid], (cabeza.X, cabeza.Y),
                obstaculos, ejes_vista, mm_a_pies, margen_ft)
            if choques:
                sin_hueco += 1
            if angulo > 1e-9:
                # Solo AnyModelDirection admite un angulo de giro libre
                tag.TagOrientation = TagOrientation.AnyModelDirection
                tag.RotationAngle = angulo
                rotadas += 1
            if h is not None:
                obstaculos.append(h)
            creadas += 1
        except Exception as ex:
            fallidas += 1
            print(u'⚠ Fallo etiquetando elemento {}: {}'.format(elem.Id, ex))
    t.Commit()
except Exception:
    t.RollBack()
    raise

resumen = (u'✅ Etiquetas creadas: {}\n'
           u'↻ Giradas para no cruzarse: {}\n'
           u'⚠ Sin hueco libre (revisar a mano): {}\n'
           u'⏭ Omitidas (ya etiquetadas): {}\n'
           u'✂ Suprimidas (misma vertical y sistema): {}\n'
           u'⚠ Fallos: {}').format(creadas, rotadas, sin_hueco, omitidas,
                                   suprimidas, fallidas)
print(resumen)
alerta(resumen)
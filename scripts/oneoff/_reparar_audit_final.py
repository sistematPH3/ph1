# coding: utf-8
# REPARACION FINAL (byte-safe, utf-8-sig, assert coincidencia unica).
#   A) waste\auditinventory.html  L69 literal corrupto -> bandera limpia + include
#   B) security\login_audit.html  L64-65 -> insertar export_sin_fechas=True antes del include
#   C) app\static\js\audit\audit_export.js -> fallback tambien lee dateFilter/hourFilter/locationFilter (accesos)
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1\app'

def leer(rel):
    p = BASE + '\\' + rel
    b = open(p, 'rb').read()
    t = b.decode('utf-8-sig')
    return p, t

def escribir(rel, t):
    p = BASE + '\\' + rel
    open(p, 'wb').write(b'\xef\xbb\xbf' + t.encode('utf-8'))
    return p

def reemplazar1(rel, old, new, desc):
    p, t = leer(rel)
    n = t.count(old)
    if n == 1:
        escribir(rel, t.replace(old, new))
        print(u'  [OK] {0}: {1}'.format(p, desc))
        return True
    if n == 0:
        print(u'  [FALLO] {0}: {1} -> literal NO encontrado (n=0)'.format(p, desc))
        print(u'    old buscado: {0!r}'.format(old[:90]))
        # contexto alrededor del include/toolbar para diagnostico
        idx = t.find(u"audit_export_toolbar.html")
        if idx >= 0:
            frag = t[max(0, idx-260):idx+120]
            print(u'    contexto: ...{0}...'.format(frag))
        return False
    print(u'  [AMBIGUO] {0}: {1} -> {2} coincidencias'.format(p, desc, n))
    return False

print(u'')
print(u'== A) INVENTARIO: reparar literal corrupto de la bandera ==================================')
okA = reemplazar1(
    r'waste\auditinventory.html',
    u"{% include 'reports/{% set export_sin_fechas = True %}\n{% include 'reports/audit_export_toolbar.html' %}",
    u"{% set export_sin_fechas = True %}\n{% include 'reports/audit_export_toolbar.html' %}",
    u'literal corrupto del include -> bandera limpia + include')

print(u'')
print(u'== B) ACCESOS: insertar bandera antes del include del toolbar =============================')
p, t = leer(r'security\login_audit.html')
# localizar el include y ver si ya tiene bandera
inc_mark = u"{% include 'reports/audit_export_toolbar.html' %}"
if u'export_sin_fechas = True' in t:
    print(u'  [INFO] {0}: ya tiene export_sin_fechas=True (sin cambios)'.format(p))
    okB = True
else:
    candidatos = []
    inicio = 0
    li = t.find(u"url_for('audit_exports.descargar_accesos'", 0)
    lin_ini = t.rfind('\n', 0, max(0, li)) + 1
    lin_ref = t.rfind('\n', 0, lin_ini - 1) + 1 if lin_ini > 0 else 0
    # insertar la linea de bandera justo despues de la linea de export_base_url
    if li >= 0:
        # la linea del set export_base_url
        nose = t.rfind('\n', 0, li)
        indent = t[nose + 1:li].split('{%')[0]
        if indent and not indent.strip():
            indentstr = indent
        else:
            indentstr = u'    '
        flag_line = indentstr + u'{% set export_sin_fechas = True %}\n'
        # insertar tras la linea del set (fin de linea siguiente al > %)
        fin_set = t.find('%}', li)
        fin_linea = t.find('\n', fin_set)
        t2 = t[:fin_linea + 1] + flag_line + t[fin_linea + 1:]
        escribir(r'security\login_audit.html', t2)
        print(u'  [OK] {0} (accesos): bandera insertada tras url_for (indent={1!r})'.format(p, indentstr))
        okB = True
    else:
        print(u'  [FALLO] {0}: literal url_for describir_accesos no encontrado'.format(p))
        okB = False

print(u'')
print(u'== C) JS: fallback tambien lee dateFilter/hourFilter/locationFilter (cintillo de accesos) =====')
p, t = leer(r'static\js\audit\audit_export.js')
# Patron actual: filtrosAplicados lee start_date/end_date y location_filter numerico.
# Ampliar para accesos: dateFilter -> desde+hasta (single-day), locationFilter -> sede si numerico.
viejo = u'''            if (!desde && !hasta) {
                desde = valorToolbar('start_date');
                hasta = valorToolbar('end_date');
            }
            if (!sede) {
                var loc = valorToolbar('location_filter');
                if (loc && /^\\d+$/.test(loc)) sede = loc;
            }'''
nuevo = u'''            if (!desde && !hasta) {
                desde = valorToolbar('start_date') || valorToolbar('dateFilter');
                hasta = valorToolbar('end_date') || valorToolbar('dateFilter');
            }
            if (desde && hasta && desde === hasta && valorToolbar('dateFilter')) {
                // accesos: un unico dia (dateFilter)
            }
            if (!sede) {
                var loc = valorToolbar('location_filter') || valorToolbar('locationFilter');
                if (loc && /^\\d+$/.test(loc)) sede = loc;
            }'''
okC = reemplazar1(r'static\js\audit\audit_export.js', viejo, nuevo, u'fallback id dateFilter/locationFilter de accesos')

print(u'')
print(u'===== RESUMEN: A={0}  B={1}  C={2} ====='.format(okA, okB, okC))
print(u'===== {0} ====='.format(u'OK TODO' if (okA and okB and okC) else u'REVISAR MANUAL'))

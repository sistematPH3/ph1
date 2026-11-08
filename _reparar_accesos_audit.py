# coding: utf-8
import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1'
print(u'BASE real: {0}'.format(BASE))

def leer(rel):
    p = os.path.join(BASE, rel)
    return open(p, 'rb').read().decode('utf-8-sig')

def escribir(rel, t):
    p = os.path.join(BASE, rel)
    open(p, 'wb').write(b'\xef\xbb\xbf' + t.encode('utf-8'))
    return p

# ============================================================
# 1) ACCESOS: bandera ANTES del include si no existe
# ============================================================
rel = r'app\templates\security\login_audit.html'
t = leer(rel)
if u'export_sin_fechas = True' in t:
    print(u'[OK accesos] ya tiene la bandera')
else:
    inc = u"{% include 'reports/audit_export_toolbar.html' %}"
    pat = re.compile(r'^(\s*)\{% include \'reports/audit_export_toolbar\.html\' %\}', re.M)
    m = pat.search(t)
    if not m:
        print(u'[FALLO accesos] include no encontrado')
    else:
        indent = m.group(1)
        bandera = u'{0}{{% set export_sin_fechas = True %}}\n'.format(indent)
        t2 = t[:m.start()] + bandera + t[m.start():]
        escribir(rel, t2)
        print(u'[OK accesos] bandera insertada antes del include (indent={0!r})'.format(indent))

# ============================================================
# 2) JS audit_export.js: fallback tambien a dateFilter/hourFilter/locationFilter (accesos)
# ============================================================
rel2 = r'app\static\js\audit\audit_export.js'
t2 = leer(rel2)

old_fallback = u"""            if (!desde && !hasta) {
                desde = valorToolbar('start_date');
                hasta = valorToolbar('end_date');
            }
            if (!sede) {
                var loc = valorToolbar('location_filter');
                if (loc && /^\\d+$/.test(loc)) sede = loc;
            }"""

new_fallback = u"""            if (!desde && !hasta) {
                desde = valorToolbar('start_date') || valorToolbar('dateFilter');
                hasta = valorToolbar('end_date') || valorToolbar('hourFilter');
            }
            if (!sede) {
                var loc = valorToolbar('location_filter') || valorToolbar('locationFilter');
                if (loc && /^\\d+$/.test(loc)) sede = loc;
            }"""

n = t2.count(old_fallback)
if n == 0:
    print(u'[FALLO js] literal del fallback no encontrado; busco con m�s =='.encode('latin-1').decode('latin-1'))
    # diagnostico: mostrar el bloque filtrosAplicados real
    i = t2.find(u'filtrosAplicados')
    print(u'   bloque actual (entorno del fallback):')
    for j in range(i - 10, min(i + 100, len(t2))):
        pass
    # mejor: imprimir lineas alrededor
    ls = t2.split(u'\n')
    for k, l in enumerate(ls, 1):
        if u'filtrosAplicados' in l or u'valorToolbar' in l or u'start_date' in l:
            print(u'   L{0}: {1}'.format(k, l))
elif n == 1:
    t3 = t2.replace(old_fallback, new_fallback)
    escribir(rel2, t3)
    print(u'[OK js] fallback ampliado a accesos (dateFilter/hourFilter/locationFilter)')
else:
    print(u'[AMBIGUO js] {0} coincidencias'.format(n))

print(u'')
print(u'=== VERIFICACION FINAL ===')
for rr in (r'app\templates\security\login_audit.html',
           r'app\templates\waste\auditinventory.html'):
    t_ = leer(rr)
    ok_band = u'export_sin_fechas = True' in t_
    ok_inc = u"include 'reports/audit_export_toolbar.html'" in t_
    ok_rot = u"reports/{% set" in t_
    print(u'  {0,-38} bandera={1} include_limpio={2} literal_corrupto={3}'.format(
        rr.split(u'\\')[-1], ok_band, ok_inc, ok_rot))
tjs = leer(r'app\static\js\audit\audit_export.js')
print(u'  audit_export.js            dateFilter_ref={0} locationFilter_ref={1}'.format(
    (u'valorToolbar(\'dateFilter\')' in tjs), (u'valorToolbar(\'locationFilter\')' in tjs)))

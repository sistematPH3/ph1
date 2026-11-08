# coding: utf-8
# Repara el mojibake (doble-encoding) de TODAS las plantillas .html bajos
# ph1\app\templates: los bytes UTF-8 originales (C3 A1 = 'a') fueron leidos
# como CP1252 ("C3" -> U+00C3 'A', "A1" -> U+00A1 'i') y re-guardados como UTF-8.
# Revertir: agrupar los chars <=0xFF a bytes, decodificar UTF-8. Los chars
# >0xFF que YA estan bien (em-dash U+2014, etc.) se conservan intactos.
# Ademas: renombra "Auditoria Forense" -> "Auditoria de Traslados" en
# logistics\movement_audit.html.
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1\app\templates'


def revertir_mojibake(s):
    out = []
    buf = bytearray()

    def aplanar():
        if not buf:
            return
        try:
            out.append(bytes(buf).decode('utf-8'))
        except UnicodeDecodeError:
            out.append(u''.join(chr(b) for b in buf))
        del buf[:]

    for ch in s:
        if ord(ch) <= 0xFF:
            buf.append(ord(ch))
        else:
            aplanar()
            out.append(ch)
    aplanar()
    return u''.join(out)


total_fix = 0
renombrado_files = 0

for raiz, _, archivos in os.walk(BASE):
    for f in archivos:
        if not f.endswith('.html'):
            continue
        p = os.path.join(raiz, f)
        rel = os.path.relpath(p, BASE)
        b = open(p, 'rb').read()
        bom = b.startswith(b'\xef\xbb\xbf')
        cuerpo = b[3:] if bom else b
        try:
            t = cuerpo.decode('utf-8')
        except UnicodeDecodeError:
            print(u'[AVISO] {0}: bytes NO-UTF8, se omite'.format(rel))
            continue

        antes = t.count(u'\u00c3') + t.count(u'\u00c2')
        t2 = revertir_mojibake(t)

        es_movement = rel.replace('\\', '/').lower() == 'logistics/movement_audit.html'
        if es_movement:
            t2 = t2.replace(u'Auditor\u00eda Forense', u'Auditor\u00eda de Traslados')
            t2 = t2.replace(u'Forense', u'de Traslados')
            renombrado_files += 1

        if t2 != t:
            nuevo = (b'\xef\xbb\xbf' if bom else b'') + t2.encode('utf-8')
            open(p, 'wb').write(nuevo)
            total_fix += 1
            print(u'[FIX] {0}: mojibake previo {1} -> reparado'.format(rel, antes))
        else:
            print(u'[OK ] {0}: limpio'.format(rel))

print(u'')
print(u'=== mojibake reparados en {0} archivos; renombrado ''de Traslados'' en {1} ==='.format(total_fix, renombrado_files))

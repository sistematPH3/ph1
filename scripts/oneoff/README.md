# Scripts de un solo uso

Esta carpeta guarda scripts históricos que se ejecutaron **una vez** para reparar
plantillas y datos del proyecto. No forman parte de la aplicación y **no deben
ejecutarse** en el servidor ni en producción.

## Advertencia

Todos tienen rutas absolutas de Windows hardcodeadas, por ejemplo:

```python
BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1'
```

Por eso no funcionan en Linux y, si se ejecutaran en la máquina original,
modificarían archivos de plantillas directamente.

## Contenido

| Script | Qué hacía |
|---|---|
| `_fix_traslados.py` | Reparaba un literal corrupto en `logistics/movement_audit.html`. |
| `_reparar_accesos_audit.py` | Ajustaba las plantillas de auditoría de accesos y su exportación. |
| `_reparar_audit_final.py` | Reparación final, byte-safe, de las plantillas de auditoría. |
| `_reparar_mojibake.py` | Corregía el doble-encoding (mojibake) de las plantillas `.html`. |

## Regla

No se importan desde `app/`. Si en el futuro hace falta una reparación masiva,
crear un script nuevo dentro de `scripts/` con rutas relativas al proyecto,
pruebas y confirmación explícita antes de escribir archivos.

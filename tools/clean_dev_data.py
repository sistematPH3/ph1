# coding: utf-8
"""
LIMPIEZA TOTAL DE DATOS (SOLO DATOS, NUNCA ESTRUCTURA).

QUÉ HACE
--------
Vacía **absolutamente todas** las tablas del sistema: transaccionales
(compras, detalles, traslados, mermas, evidencias, inventario, snapshots de
estadística, notificaciones y bitácoras de auditoría), catálogos (categorías,
tipos de producto, tipos de merma, proveedores, parámetros de la app) y
seguridad (usuarios, roles, sedes y asignaciones usuario-sede).

La ÚNICA tabla que se conserva es `alembic_version`, para que el historial de
migraciones de Alembic siga intacto. No se borran tablas, no se alteran
columnas, no se tocan modelos ni archivos de migración.

CÓMO RESPETA LAS LLAVES FORÁNEAS
-------------------------------
En PostgreSQL se ejecuta UN SOLO `TRUNCATE TABLE a, b, c ... RESTART IDENTITY`
con todas las tablas del esquema en la MISMA sentencia. Postgres valida las FK
al final de la sentencia, así que la auto-referencia de `movements`
(`source_dispute_id` / `return_of_dispute_id`), `user_locations`, y las cadenas
`users -> roles/locations` quedan resueltas sin errores de integridad.

No se usa `CASCADE` a propósito: si algún día aparece una tabla nueva que
referencie a estas y no esté en la lista, el TRUNCATE falla con un error de
integridad visible en vez de vaciar en silencio algo fuera de control.

OJO
---
Al terminar, la base queda sin usuarios, sin roles y sin sedes: **no podrás
iniciar sesión** hasta volver a crear el usuario administrador y los catálogos
mínimos. Es un borrado total pensado para desarrollo/pruebas.

SEGURIDAD
---------
- DRY-RUN POR DEFECTO: sin --apply solo cuenta filas y muestra el SQL; no escribe.
- Con --apply pide escribir la palabra LIMPIAR por teclado (o usa --yes para
  automatizar en un entorno controlado).
- Aborta si el nombre de la base contiene "prod".
- Avisa si detecta alguna tabla del esquema que no esté en la lista (para que
  la limpieza sea realmente del 100%).
- Verifica al final que todas las tablas quedaron en 0 filas; si no, sale con
  código 1. Si algo falla, hace ROLLBACK y no deja la base a medias.

USO (PowerShell, desde la raíz del proyecto)
--------------------------------------------
    python tools/clean_dev_data.py                  # diagnóstico (solo lectura)
    python tools/clean_dev_data.py --apply          # limpia (pide confirmación)
    python tools/clean_dev_data.py --apply --yes    # limpia sin preguntar

La app usa la MISMA conexión que el proyecto (DATABASE_URL del .env), así que
no hay que pasar credenciales por parámetro.
"""

import argparse
import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db


# --- Orden de dependencias (hijas primero, padres al final) -----------------
# Se mantiene explícito y legible: es la documentación viva del grafo de FKs y
# además sirve como orden correcto para el fallback con DELETE.
TABLAS_A_LIMPIAR = (
    # Mermas
    'waste_detail_photos',      # -> waste_details
    'waste_details',            # -> waste, products, waste_types, users
    'waste',                    # -> locations, waste_types, users
    # Compras
    'purchase_audit_log',       # -> purchases, users
    'purchase_details',         # -> purchases, products
    'purchases',                # -> suppliers, users
    # Logística
    'movement_details',         # -> movements, products
    'movements',                # -> locations, users y self-FK
    # Inventario y estadísticas
    'inventory',                # -> locations, products
    'statistics_snapshots',     # -> locations, users
    # Notificaciones y auditoría
    'notifications',            # -> users, locations
    'audit_logs',               # -> users, locations
    'login_audit',              # -> users, locations, roles
    'user_audit',               # -> users, roles
    'password_recoveries',      # -> users
    'exchange_rate_history',    # -> users
    # Catálogos de inventario / merma
    'products',                 # -> product_types
    'product_types',            # -> categories
    'categories',
    'waste_types',
    'suppliers',
    'app_parameters',
    # Seguridad (usuarios, roles y sedes)
    'user_locations',           # -> users, locations
    'users',                    # -> roles
    'roles',
    'locations',
)

# Nunca se incluye en el TRUNCATE (ni por error de edición del script).
TABLAS_PROTEGIDAS = ('alembic_version',)


def _tablas_existentes(nombres):
    """Filtra la lista contra el esquema real (por si alguna tabla aún no existe)."""
    existentes = set(inspect(db.engine).get_table_names())
    faltantes = [n for n in nombres if n not in existentes]
    if faltantes:
        print(f'  (omitidas, no existen en esta base: {", ".join(faltantes)})')
    return [n for n in nombres if n in existentes]


def _tablas_fuera_de_la_lista(tablas):
    """Tablas del esquema real que no se vaciarían (excluyendo alembic_version)."""
    existentes = set(inspect(db.engine).get_table_names())
    return sorted(existentes - set(tablas) - set(TABLAS_PROTEGIDAS))


def _contar(tablas):
    return {
        t: db.session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()
        for t in tablas
    }


def _imprimir_conteo(titulo, conteo):
    if not conteo:
        print(f'{titulo} (sin tablas)')
        return
    ancho = max(len(t) for t in conteo)
    print(titulo)
    for tabla in conteo:
        print(f'  {tabla:<{ancho}}  {conteo[tabla]:>9,} fila(s)')
    print(f'  {"TOTAL":<{ancho}}  {sum(conteo.values()):>9,} fila(s)')


def _sql_truncate(tablas):
    lista = ', '.join(f'"{t}"' for t in tablas)
    return f'TRUNCATE TABLE {lista} RESTART IDENTITY'


def _ejecutar_limpieza(tablas):
    if db.engine.dialect.name == 'postgresql':
        # Una sola sentencia: resuelve las FKs entre tablas listadas sin CASCADE.
        db.session.execute(text(_sql_truncate(tablas)))
    else:
        # Fallback para motores sin TRUNCATE multi-tabla (p. ej. SQLite en local).
        db.session.execute(text('PRAGMA foreign_keys = OFF'))
        for tabla in tablas:
            db.session.execute(text(f'DELETE FROM "{tabla}"'))


def main():
    parser = argparse.ArgumentParser(
        description='Vacía TODOS los datos de la base de DESARROLLO (incluidos usuarios, '
                    'roles, sedes y catálogos) sin tocar estructura ni migraciones. '
                    'Solo se conserva alembic_version.'
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Ejecuta la limpieza. Sin esta bandera solo diagnostica (no escribe nada).'
    )
    parser.add_argument(
        '--yes', action='store_true',
        help='No pide confirmación interactiva (úsalo solo en entornos controlados).'
    )
    args = parser.parse_args()

    tablas = list(TABLAS_A_LIMPIAR)

    # Salvaguarda dura: alembic_version no puede colarse en la lista.
    conflicto = sorted(set(tablas) & set(TABLAS_PROTEGIDAS))
    if conflicto:
        raise SystemExit(f'ABORTADO: el script intentaría tocar tablas protegidas: {conflicto}')

    app = create_app()
    with app.app_context():
        url = db.engine.url
        nombre_bd = url.database or '(sin nombre)'
        print(f'Base de datos destino : {nombre_bd}')
        print(f'Servidor              : {url.host or "local"}')
        print(f'Motor                 : {db.engine.dialect.name}')

        if 'prod' in nombre_bd.lower():
            raise SystemExit(
                'ABORTADO: el nombre de la base contiene "prod". Este script es solo '
                'para desarrollo/pruebas.'
            )

        print()
        fuera_de_lista = _tablas_fuera_de_la_lista(tablas)
        if fuera_de_lista:
            print(f'ADVERTENCIA: estas tablas existen y NO se vaciarían: {", ".join(fuera_de_lista)}')
            print('             Agrégalas a TABLAS_A_LIMPIAR si también deben limpiarse.')
            print()

        tablas = _tablas_existentes(tablas)
        if not tablas:
            print('No hay tablas que limpiar. Nada que hacer.')
            return

        antes = _contar(tablas)
        _imprimir_conteo('Filas actuales:', antes)
        print()
        if db.engine.dialect.name == 'postgresql':
            print('SQL a ejecutar:')
            print(f'  {_sql_truncate(tablas)};')
        print('Se conserva: alembic_version (estado de migraciones).')
        print()

        if sum(antes.values()) == 0:
            print('Las tablas ya están vacías. Nada que hacer.')
            return

        if not args.apply:
            print('[DRY-RUN] No se escribió nada.')
            print('Para limpiar de verdad: python tools/clean_dev_data.py --apply')
            return

        if not args.yes:
            print('Esto BORRARÁ todos los registros de TODAS las tablas, incluidos')
            print('usuarios, roles, sedes y catálogos. La base quedará sin acceso hasta')
            print('recrear el usuario administrador.')
            print(f'Base de datos: {nombre_bd}')
            respuesta = input('Escribe LIMPIAR en mayúsculas para continuar: ')
            if respuesta.strip() != 'LIMPIAR':
                print('Cancelado. No se modificó nada.')
                return

        try:
            _ejecutar_limpieza(tablas)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise SystemExit(f'ERROR: se revirtió todo, la base quedó intacta. Detalle: {exc}')

        despues = _contar(tablas)
        _imprimir_conteo('Filas después de la limpieza:', despues)
        pendientes = {t: n for t, n in despues.items() if n}
        if pendientes:
            print(f'ADVERTENCIA: quedaron filas en {pendientes}. Revisar manualmente.')
            sys.exit(1)

        print()
        print('Limpieza completada. Tablas, columnas, índices y alembic_version intactos.')
        print('Recuerda: sin usuarios ni roles no podrás iniciar sesión hasta volver a crearlos.')


if __name__ == '__main__':
    main()

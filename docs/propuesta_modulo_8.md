# Propuesta — Módulo 8: Dashboards, Estadísticas y Exportación Financiera

> Versión: 1.0 (borrador para validar)
> Autor responsable: titular del Módulo 8
> Colaboración externa: compañero de notificaciones y alarmas (partes señaladas)

---

## 1. Resumen ejecutivo (en palabras simples)

El sistema hoy controla el día a día: comprar insumos, trasladarlos entre sedes,
registrar consumos de cocina, dar de baja mermas y auditar todo. Lo que **falta** es
responder una pregunta: **¿cuánto está costando realmente operar cada sede y todo
el negocio?** Ese es el objetivo del Módulo 8.

Este módulo agrega:

1. **Dashboards por rol** con indicadores clave (no solo listas, sino números y
   gráficos: cuánto se compró este mes, qué sedes pierden más por merma, cuántos
   traslados hay en tránsito).
2. **Estadísticas financieras**: compras, gastos de cocina, mermas y traslados,
   vistos por **semana, mes, trimestre y año**, por sede, por producto y por
   categoría, siempre con **comparación contra el período anterior**.
3. **Alarmas de irregularidad**: si un gasto se dispara de golpe (ej. una sede
   gasta en un mes lo mismo que solía gastar en tres), se genera un aviso en la
   bandeja interna con el detalle de la estadística.
4. **Exportación en PDF y Excel** de cada reporte, con identificación del período,
   la sede y quién lo generó (pensado también para auditoría).

**Idea clave para no quedarnos cortos**: las mermas y los consumos no se guardan
con su precio en el momento. El valor del dinero se calcula usando el **último
precio de compra** del insumo (el "costo de reponerlo hoy"). Esto se explica a
fondo en la sección 5.

---

## 2. Objetivos

| Objetivo | Descripción |
|---|---|
| O1 | Que el **Administrador** vea la estadística global: todas las sedes juntas, por separado, y la Central. |
| O2 | Que **Finanzas** vea la estadística **solo de sus sedes asignadas** (perfil de solo lectura). |
| O3 | Calcular el **costo operativo** del negocio con los datos que ya existen (compras, consumos, mermas) y monedas BS / USD / EUR. |
| O4 | Detectar **gastos irregulares** (picos fuera de lo normal) y notificarlos automáticamente. |
| O5 | Permitir **exportar** cada reporte a **PDF y Excel** para presentación y auditoría. |
| O6 | Completar los **dashboards por rol** que hoy son casi vacíos. |

---

## 3. Situación actual del sistema (lo que ya existe)

### Lo que es sólido

| Pieza | Estado hoy |
|---|---|
| Compras (`Purchase` / `PurchaseDetail`) | Guardan **monto total, moneda, tasa de cambio** y por línea: producto, **lote**, cantidad, precio en moneda extranjera (`foreign_price`) y en bolívares (`price_bs`). → El dinero real ya existe. |
| Historial de tasa (`ExchangeRateHistory`) | Tasas BS/USD/EUR con fecha y fuente (pyBCV / pyDolarVenezuela ya integrados). |
| Categorías contables (`Category`) | "Categorías Macro Contables y de Reportes Financieros". Hoy se usan poco; serán el agrupador de los reportes. |
| Permisos por sede | Ya existe el patrón para que Finanzas vea solo sus sedes asignadas (se usa en auditoría de compras y movimientos). |
| Notificaciones (`Notification`) | Bandeja interna con sede, tipo, mensaje, leído/no leído. Perfecta para las alarmas. |
| Auditoría (`AuditLog`) | Registra quién hizo qué y con qué cambios. Base de trazabilidad para los exportes. |
| Mermas (`Waste` / `WasteDetail`) | La tabla **ya trae campos de costo** (`unit_cost`, `subtotal_cost`, `total_cost`, `currency`)… que hoy se llenan en **0**. → Los activaremos. |

### Lo que falta (espacios en blanco)

| Pieza | Estado hoy |
|---|---|
| Dashboards | Existen los 6 por rol, pero casi vacíos: solo muestran las alarmas de stock bajo. El de finanzas tiene un placeholder "Reportes Financieros" con enlace a `#`. |
| Módulo de estadísticas | `analytics/dashboard.html` = archivo **vacío (0 bytes)**. Sin rutas ni servicios. |
| Módulo de reportes / export | `reports/export.html` = archivo **vacío (0 bytes)**. |
| Alarmas | Solo existen las de **stock bajo**. No hay detección de irregularidad de costos. |
| Valor monetario de consumos | Los consumos de cocina guardan **cantidades, no dinero**. El valor hay que **calcularlo** (sección 5). |

---

## 4. Roles y permisos

| Rol | Qué ve | Puede hacer |
|---|---|---|
| **Admin** | Estadística de **todas las sedes juntas**, **por sede** y de la **Central**. | Todo: ver, refrescar resúmenes, configurar umbrales, exportar. |
| **Finanzas** | Estadística **solo de sus sedes asignadas**. | **Solo lectura** (consistente con el resto del sistema). Puede exportar. |

- Implementación: se reutiliza el filtro de sedes asignadas que ya se usa en
  `audit_purchase` y `movement_audit`. El Admin no tiene filtro (ve todo).
- El concepto de "Central" es la sede con rol Central (ej. `Almacén Central`):
  es una sede más en el modelo, por lo que no requiere cambios de esquema.
- **Rol de la Central en la operación**: todo se compra en la Central y de ahí se
  distribuye a las demás sedes. Por eso la Central:
  - **Sí** genera estadísticas de **compras** y de **traslados** (salidas hacia
    las sedes).
  - **No** maneja **gastos de cocina** (sus consumos de cocina no aplican). El
    reporte de gastos de cocina se concentra en las sedes con cocina.
- Las estadísticas de "la Central" = las de esta sede concreta; "todas juntas" =
  suma de todas las sedes (incluida la Central).

---

## 5. El dinero: cómo se valora (último precio de compra)

### En palabras simples

Las mermas (producto que se bota) y los consumos (lo que usa la cocina) **no
tienen precio grabado** porque el precio cambia. Ejemplo:

> Hoy compran un lote de **10 kg de harina a 20 $** (es decir, 2 $/kg). Dentro de
> un mes la harina sube y ese mismo lote de 10 kg costaría **25 $** (2,50 $/kg).
> Si hoy botan 1 kg, la pérdida vale **2 $**; si botan los 10 kg completos, vale
> **20 $** (el costo del lote). Si botan los 10 kg el mes que viene, la pérdida
> vale **25 $**, porque hoy le costaría 25 $ reponer ese lote.

La regla del módulo: **una merma o un consumo se valora a lo que costaría
reponerlo hoy**, o sea el **último precio de compra** del insumo en ese momento
(cuando el precio sube, la merma vale más y se ve el impacto real).

### ¿Qué pasa si hay varios proveedores con precios distintos?

Ejemplo: la harina la venden el **Proveedor A a 2 $/kg** y el **Proveedor B a
2,20 $/kg**.

- La regla usa el precio de la **compra más reciente del producto**, sin importar
  el proveedor. Si la última compra fue al A (2 $/kg), las mermas/consumos se
  valoran a 2 $/kg. Si la siguiente compra es al B (2,20 $/kg), pasan a valorarse
  a 2,20 $/kg. Así el valor refleja siempre "lo que costaría reponerlo hoy".
- Si la merma o el consumo indica su **lote**, se usa el precio de **ese lote
  exacto** (que ya pertenece a un proveedor concreto y a una fecha concreta).
- El **promedio ponderado de las últimas 3 compras** suaviza los saltos cuando
  los precios de los proveedores se mueven seguido.
- En los **reportes de compras** el monto siempre se puede desglosar **por
  proveedor**, para ver cuánto compramos a cada uno y comparar precios.

> **Importante — cada lote pertenece a UN solo producto.** En una compra puedes
> registrar varias líneas: **una por producto, con su propio lote y su propia
> cantidad**. El mismo producto puede comprarse en **dos lotes separados** (ej.
> comprar harina en dos lotes distintos, cada uno con su cantidad y su precio).
> No existe el "precio de un lote" global: cada lote de producto tiene su
> cantidad y su precio. Por eso el costo siempre se consulta **por producto**
> ("¿cuánto está la harina?"), rastreando el lote exacto si hace falta.

### Detalle técnico (derivación del costo)

- La valorización siempre es **por producto**: en `PurchaseDetail` cada línea es
  un producto con su `lot_number` (o `S/L` si no lleva lote), su `quantity`, su
  `foreign_price` y su `price_bs`. Un mismo producto puede tener **varios lotes
  distintos** (el lote se autogenera por producto como `{sku}-{fecha}-{secuencia}`),
  cada uno con su cantidad y su precio.
- El "último precio" = última compra de ESE `product_id`; el `lot_number` solo
  sirve para rastrear la compra/el lote exacto y su precio cuando la merma o el
  consumo registra el lote.
- Cada insumo (`Product`) se valora con la última compra registrada antes de la
  fecha de la merma/consumo:
  - En **bolívares** → `PurchaseDetail.price_bs` (ya incluye la tasa de ese día).
  - En **USD** → `PurchaseDetail.foreign_price`.
  - En **EUR** → `PurchaseDetail.foreign_price` + conversión a USD con
    `ExchangeRateHistory` de la fecha de la compra (el consolidado siempre se
    reduce a USD como moneda base; se muestra cada moneda en su reporte).
- Para evitar saltos raros por una compra aislada, el "último precio" puede ser
  el **promedio ponderado de las últimas 3 compras** del producto.
- Las **mermas** dejarán de guardar costo en 0: a partir de este módulo se puebla
  `WasteDetail.unit_cost`, `subtotal_cost`, `total_cost` y `currency` **al
  registrar** (campos que ya existen y estaban reservados para un módulo de
  finanzas): en ese momento se calcula cantidad × último precio de compra y ese
  valor queda **congelado** en la merma. Si mañana cambia el precio, la merma de
  ayer **no se cambia**.
- **En palabras simples**: al registrar la merma se le pone su costo en ese
  instante. Si el precio sube después, las mermas que ya se registraron quedan
  como estaban. Las **mermas históricas antiguas NO se recalculan**: se dejan tal
  cual (quedan con costo 0), para no inventar datos del pasado que nunca fueron
  valorizados.
- Los **consumos** NO guardan dinero (se mantiene igual); su valor se **calcula
  al generar el reporte** multiplicando `quantity` × último precio de compra.
  Así, si se corrige un precio de compra, el historial se actualiza solo.

> Decisión tomada con el equipo: valorizar con el **último precio de compra** y
> umbrales **globales**. (Ver secciones 5 y 7).

---

## 6. Reportes de estadística

### 6.1 Reportes disponibles

| Reporte | Mide | Fuente de datos |
|---|---|---|
| **Compras** | Monto por sede, proveedor, categoría, mes. En BS, USD y EUR | `Purchase` + `PurchaseDetail` (+ `ExchangeRateHistory`) |
| **Gastos de cocina (consumos)** | Cantidad consumida y su valoración a último precio de compra | `AuditLog` (acción CONSUMO) valorizado (sección 5) |
| **Mermas** | Cantidad perdida, **costo de la pérdida**, por tipo de merma (vencido, sobreproducción, etc.), y **% sobre compras** (índice de merma) | `Waste` + `WasteDetail` (con costo poblado) |
| **Traslados** | **Cantidad de traslados por período** (semanal/mensual/trimestral/anual), enviados vs recibidos, reposiciones/complementos, disputas, y **pérdidas por novedades (ej. extravío) valorizadas a costo** | `Movement` + `MovementDetail` |
| **Consolidado financiero** | Compras − consumo − mermas − pérdidas en traslado = **costo operativo** del período | Suma de los reportes anteriores |

### 6.2 Comparativa entre sedes

El Admin ve, además del detalle, un **ranking entre sedes** para el período
seleccionado:

- **¿Qué sede gasta más?** (compras y gastos de cocina).
- **¿Qué sede tiene más mermas?** (cantidad y costo de la pérdida).
- **¿Qué sede genera más traslados?** (enviados/recibidos).
- **¿Qué sede pierde más en traslados?** (extravíos valorizados).
- Comparación lado a lado: cada sede con sus números del período + variación.

Esto responde "quién está gastando o perdiendo más" de un vistazo. Las
estadísticas de Administración usan este ranking global; las de Finanzas siempre
filtradas a sus sedes.

### 6.3 Períodos y comparación

- Períodos disponibles: **semanal, mensual, trimestral, anual**.
- Cada reporte muestra el período seleccionado contra el **período anterior
  equivalente** (ej. mes actual vs mes anterior) con:
  - Diferencia absoluta (ej. +350 $).
  - Variación porcentual (ej. +18 %).
  - Indicador visual de "subió / bajó". Un subidón notable genera alarma
    (sección 7).

### 6.4 Filtros (comunes a todos los reportes)

- Sede (según permiso del rol).
- Período y tipo de período.
- Moneda base del reporte (BS / USD / EUR).
- Producto, categoría contable, proveedor (según aplica).
- Fecha de corte (desde / hasta).

### 6.5 Pantalla general (diseño propuesto)

```
/estadisticas
├─ Selector: Período (semana/mes/trimestre/año) + Rango + Sede + Moneda
├─ KPI cards: Compras | Consumo | Mermas | Traslados | Costo operativo
├─ Ranking entre sedes (Admin): mayor gasto, más mermas, más traslados, pérdidas
├─ Gráficos (Chart.js): evolución temporal, top categorías, merma por tipo
├─ Tabla detallada del reporte activo con botones [Exportar PDF] [Exportar Excel]
└─ Panel de alarmas activas del período (si el requisito lo habilita)
```

- Gráficos con **Chart.js** (ya se usa vía CDN en el dashboard del Admin; no se
  agregan más librerías gráficas).
- La misma pantalla sirve a Admin (todas las sedes o selector) y a Finanzas
  (filtrando por sus sedes asignadas).

---

## 7. Alarmas de irregularidad

### En palabras simples

Imagina que una sede gasta lo mismo en **cada mes**: 100, 100, 100 y 300. Los
primeros tres meses gastó 100 cada uno; el cuarto gastó el triple. Eso es
**irregular**.

> Ejemplo del equipo: "tres meses fueron 600 y este, en un solo mes, fue 600"
> → un mes gastó lo que solía gastar en tres. Eso suena la alarma.

### La regla (umbral global)

Una alarma suena si, para una métrica y un período:

```
valor_del_periodo  >  (factor × promedio_movil_de_los_ultimos_3_periodos)
                     AND  valor_del_periodo  >=  minimo_absoluto
```

Con valores iniciales propuestos:
- **factor = 2.0** (el valor duplica el promedio).
- **mínimo absoluto = 100 $** (o su equivalente en BS) para no llenar de avisos
  por montos chicos.

El ejemplo con números:

| Mes | Gasto de cocina sede X | ¿Alarma? |
|---|---|---|
| Mes 1 | 100 | — (se construye el histórico) |
| Mes 2 | 100 | — |
| Mes 3 | 100 | — |
| Mes 4 | 300 | Sí (300 = 3× el promedio de 100) |
| Mes 4 | 80 | No (menos que el promedio) |
| Mes 4 | 100 | No |

### Por qué "global" (no por sede)

- **Global**: un solo factor y un solo mínimo para todas las sedes. Simple de
  configurar y de explicar. Las sedes comparten la misma operación.
- **Por sede** (descartado por ahora): cada sede con su factor y mínimo. Más
  ajuste, pero más configuración que mantener.
- El diseño se hace **a prueba de futuro**: si algún día se quiere un umbral por
  sede, se agrega un campo `location_id` opcional a la configuración sin romper
  nada (el valor por sede sobreescribiría al global).

### Detalle técnico (cómo se detecta y no se re-dispara)

- El **promedio móvil** se calcula sobre los 3 períodos inmediatamente anteriores
  al actual, usando los **snapshots** de la sección 8 (misma fuente para el
  gráfico, el export y la alarma → números consistentes).
- Cada métrica es independiente: compras, consumo, mermas y traslados tienen su
  propia evaluación.
- **Anti-duplicados**: no se vuelve a alarmar sobre el mismo `(sede, métrica,
  período)` aunque se recalculen los datos; si la alarma ya existe, se conserva.

### Coordinación con el compañero de notificaciones

- **Parte de este módulo**: detectar la irregularidad y crear el aviso.
- **Parte del compañero**: el motor de notificaciones y campana (tipos de aviso,
  marcar leído, entrega). Para no pisar su trabajo:
  - Este módulo **crea** notificaciones vía la infraestructura `Notification`
    (nuevo tipo, ej. `ALERTA_ESTADISTICA`), con `location_id` (para que
    Finanzas filtre por sus sedes) y un enlace que abre la estadística detallada.
  - La presentación (campana, listado, lectura) es del compañero.

---

## 8. Modelo de datos

### 8.1 Nueva tabla: `statistics_snapshots`

**En palabras simples**: una "foto" de los totales ya calculados. Guarda, por
sede y por período, cuánto se compró, consumió, mermó o trasladó. Se refresca con
un botón "Actualizar" y los reportes, gráficos y alarmas leen de esta "foto" en
vez de recalcular todo desde cero (que sería lento con muchos meses de datos).

**Detalle técnico** (nombres en inglés, consistentes con el proyecto):

| Campo | Tipo | Explicación |
|---|---|---|
| `id` | integer, PK | Identificador |
| `location_id` | FK → `locations.id`, **NOT NULL** | Sede del resumen. La Central es una sede más. "Todas las sedes juntas" = suma de las filas. |
| `metric` | varchar(30) | Métrica: `PURCHASES`, `KITCHEN_CONSUMPTION`, `WASTE`, `TRANSFERS` |
| `period_type` | varchar(15) | `WEEKLY`, `MONTHLY`, `QUARTERLY`, `ANNUAL` |
| `period_start` | date | Inicio del período |
| `period_end` | date | Fin del período |
| `amount_bs` | numeric(15,2) | Monto en bolívares |
| `amount_usd` | numeric(15,2) | Monto en USD (moneda base del consolidado) |
| `amount_eur` | numeric(15,2) | Monto original en euros (para reportes en EUR / consolidación) |
| `quantity` | numeric(14,2) | Cantidad/volumen (mermas, traslados) |
| `record_count` | integer | Cuántos registros fuente se agruparon (compras, consumos, …) |
| `calculated_at` | datetime | Cuándo se calculó el snapshot |
| `calculated_by_user_id` | FK → `users.id` | Quiém disparó el cálculo |

- **Clave única**: `(location_id, metric, period_type, period_start)` → evita
  duplicados al recalcular; la actualización es idempotente (UPSERT).
- La tabla se crea con **migración Alembic/Flask-Migrate** (mecanismo ya usado
  en el proyecto) cuando se implemente el módulo.
- Los montos se guardan en las 3 monedas para que el usuario elija la moneda del
  reporte sin recalcular.

### 8.2 Qué NO se modifica (y por qué)

| Tabla | Por qué no se toca |
|---|---|
| `Purchase` / `PurchaseDetail` | Ya guardan monto, moneda, tasa y lote con precio. |
| `Product` / `ProductType` / `Category` | El precio se **deriva** de las compras; las categorías contables ya existen. |
| `Movement` / `MovementDetail` | Ya guardan, **por producto y lote**, la cantidad que faltó al recibir (`missing_quantity`), que es justo la base del **extravío**. La pérdida se **valora a costo** desde ahí, sin tocar nada. |
| `Waste` / `WasteDetail` | **Ya tienen los campos de costo** (`unit_cost`, `subtotal_cost`, `total_cost`, `currency`). Solo empezamos a llenarlos. |
| `AuditLog` (consumos) | El gasto se calcula con el último precio de compra; no se graban montos fijos. |
| `Notification` | Ya soporta el tipo nuevo `ALERTA_ESTADISTICA` sin cambios. |
| `AppParameter` | Umbrales **factor** y **mínimo absoluto** se guardan como parámetros globales (`app_parameters`), sin tabla nueva de configuración. |

---

## 9. Dashboards por rol

Propuesta de **contenido concreto por dashboard** (KPIs, gráficos y accesos).
Los KPI financieros se calculan desde `statistics_snapshots` (datos ya agregados,
carga rápida) y el detalle bajo demanda abre el reporte correspondiente. Se
reutilizan las tarjetas y estilos de CSS existentes.

### 9.1 Administrador — Panel de Control Global (`/dashboard/admin`)

El más completo: ve todas las sedes juntas, cada sede, y la Central.

- **Indicadores financieros del período** (con selector de período y moneda):
  Compras, Gastos de cocina, Mermas (cantidad y costo de la pérdida) y Costo
  operativo.
- **Gráfico de evolución** (Chart.js): compras vs consumo vs mermas por período.
- **Mermas por tipo** (vencido, sobreproducción, temperatura…): barras con el
  costo por motivo.
- **Stock crítico / bajo** por sede (alarmas de stock que ya existen).
- **Pendientes por atender**: mermas por aprobar, traslados en tránsito, disputas.
- **Alarmas estadísticas**: picos irregulares detectados con enlace al detalle.
- **Últimos accesos** al sistema (ya existente).
- Accesos directos a: Estadísticas, Exportar reporte, Configurar umbrales.

### 9.2 Finanzas (`/dashboard/finance`)

Mismos indicadores que el Admin pero **solo de sus sedes asignadas** y en modo
**solo lectura**.

- **KPI del período de sus sedes**: Compras, Consumo, Mermas y Costo operativo.
- **Comparativo vs período anterior** (diferencia $ y %).
- **Auditoría de Accesos** y **Auditoría de Personal** (ya existen hoy).
- **Reportes Financieros**: reemplazar el placeholder `#` por enlaces a las
  estadísticas con su sede preseleccionada y botones de exportación.
- **Alarmas estadísticas de sus sedes** (mismo listado filtrado por sede).

### 9.3 Director / Gerencia (`/dashboard/director` → `management_dashboard`)

Visión estratégica sin meter los números internos finos:

- **Resumen ejecutivo global**: stock agregado, mermas pendientes, traslados en
  tránsito, alertas críticas.
- **Panel de críticos**: stock crítico por sede, mermas de tipo alto/grave.
- Enlace a estadísticas si su rol tiene permiso.

### 9.4 Gerente (`/dashboard/manager-dashboard`)

Operativo de su sede:

- **Sede**: stock disponible vs mínimo, mermas pendientes, consumos del día.
- **Traslados por recibir** y reposiciones solicitadas.
- **Alarmas de stock** de su sede.

### 9.5 Asistente de Gerencia (`/dashboard/assistant-manager`)

Enfoque en cola de tareas del día:

- **Pendientes de su sede**: consumos y mermas por registrar, aprobaciones.
- **Inventario**: productos próximos a vencer, stock bajo.
- Menos KPIs, más listado accionable (botones para registrar/ver).

### 9.6 Operaciones (`/dashboard/operations`)

Enfoque en traslados:

- **Traslados en tránsito**, recibidos y pendientes de recepción.
- **Disputas por resolver** y reposiciones complementarias.
- **Alertas de recepción** y de stock en las sedes de operación.

---

## 10. Exportación: PDF y Excel

### En palabras simples

Cada reporte tendrá dos botones: **"Exportar PDF"** (para adjuntar en correos o
presentar) y **"Exportar Excel"** (para revisar/editar números en hojas). Ambos
llevan identificados: **período, sede, moneda, fecha de generación y quién lo
generó** → útil para auditoría.

### Librerías (já instaladas o por agregar)

| Librería | Uso | Estado |
|---|---|---|
| `reportlab` >= 4.5 | Generar **PDF** con tablas y resumen | **Ya instalada** |
| `openpyxl` >= 3.1 | Escribir archivos **Excel** | **Ya instalada** |
| `pandas` >= 3.0 | Procesar/transformar los datos antes de exportar | **Ya instalada** |
| `xlrd` >= 2.0 | Leer Excel legado (si acaso) | **Ya instalada** |
| `python-docx` | Generar **Word** | **DESCARTADO** (decisión del equipo: PDF + Excel son suficientes) |
| Chart.js (CDN) | Gráficos en pantalla | Ya se usa en el dashboard del Admin |

### Qué se exporta

- **PDF** (`reportlab`): portada con título, período, sede, generador y fecha;
  tabla resumen; desglose por producto/categoría/proveedor (según reporte);
  totales por período y comparativo. Una libreta por reporte.
- **Excel** (`openpyxl` + `pandas`): una hoja por desglose (Resumen, Compras,
  Consumos, Mermas) con formatos de moneda según BS/USD/EUR y totales con
  fórmulas. Abierto y editable por el usuario.
- Ambos formatos comparten el mismo "objeto de datos del reporte" (se construye
  una sola vez y se renderiza a PDF, Excel o pantalla) → consistencia garantizada.

---

## 11. Endpoints y pantallas propuestos

| Ruta | Propósito |
|---|---|
| `GET /estadisticas` | Pantalla principal de estadísticas (selector período/sede/moneda) |
| `GET /estadisticas/<reporte>` | Detalle de un reporte (`compras`, `consumo`, `mermas`, `traslados`, `consolidado`) |
| `GET /estadisticas/export/<formato>/<reporte>` | Exportar a `pdf` o `excel` del reporte activo |
| `POST /estadisticas/refresh` | Recalcular y actualizar los `statistics_snapshots` |
| `GET /config/estadisticas` | Pantalla de umbrales (factor, mínimo absoluto) |
| `POST /config/estadisticas` | Guardar umbrales en `app_parameters` |
| `POST /api/estadisticas/alarmas/evaluar` | Evaluar irregularidades del período y crear notificaciones `ALERTA_ESTADISTICA` |

- Modo de acceso: menú lateral y tarjetas de cada dashboard.
- Rol: finanzas alcanza las rutas de lectura/export (filtradas por sus sedes);
  Admin, todo.

### 11.1 Apartado de configuración (¿qué se configura?)

En pocas palabras: **casi nada necesita configuración**; el módulo calcula solo.
Solo hay **una** pantalla, **Configuración de Estadísticas** (`/config/estadisticas`),
accesible al Admin, para que el comportamiento de las alarmas se pueda ajustar sin
tocar código:

- **Umbral de irregularidad global** (dos números):
  - **Factor (ej. 2.0)**: cuántas veces el promedio se considera "anormal". Con
    factor 2, un mes que duplica el promedio de los 3 meses anteriores dispara la
    alarma.
  - **Mínimo absoluto (ej. 100 $)**: la cifra mínima para que valga la pena
    avisar. Ejemplo: una sede pasa de gastar 40 $ a 90 $ en cocina al mes — eso es
    más del doble, pero 90 $ es poco dinero, así que **no** se molesta con una
    alarma. Si el mes sube a 300 $, ahí sí se avisa.
- **Moneda por defecto** de los reportes (BS / USD / EUR): solo define con qué
  moneda **abren** los reportes; el usuario siempre puede cambiar a otra en el
  selector.

**Lo que NO se configura** (es automático): los precios (último precio de
compra), los períodos (semana/mes/trimestre/año), el refresco de resúmenes, las
comparativas y los rankings entre sedes. Estos parámetros se guardan en
`app_parameters`, la tabla de reglas globales que el sistema ya usa para otras
configuraciones.

---

## 12. Plan de implementación (fases)

### Fase 1 — Cimientos (modelo y motor de costos)
- [ ] Migración Alembic: creación de `statistics_snapshots`.
      _(Fuera de la división de tareas del Anexo D: no la cuenta como trabajo nadie.)_
- [ ] Servicio de "último precio de compra" por producto (BS/USD/EUR + promedio
      ponderado de las últimas 3 compras).
- [ ] Poblar el costo de mermas **nuevas** (`unit_cost`, `subtotal_cost`,
      `total_cost`, `currency`) al registrar. Las mermas históricas NO se tocan.
- [ ] Calcular costo de consumos bajo demanda.

### Fase 2 — Snapshots y reportes
- [ ] Generador de snapshots por sede y período (semanal/mensual/trimestral/
      anual) idempotente (UPSERT).
- [ ] Consultas de los 5 reportes con filtros (sede, período, moneda, producto,
      categoría, proveedor) y comparativo vs período anterior. Incluye el
      **conteo de traslados** por período y la **valorización de pérdidas por
      novedades (extravío)**.
- [ ] **Ranking entre sedes** (mayor gasto, más mermas, más traslados, pérdidas).
- [ ] Pantalla `/estadisticas` con selector, KPIs, ranking y gráficos Chart.js.

### Fase 3 — Alarmas
- [ ] Evaluación de irregularidad (factor + mínimo absoluto, promedio móvil 3
      períodos) y creación de notificaciones `ALERTA_ESTADISTICA`.
- [ ] Panel de config `/config/estadisticas` (guarda en `app_parameters`).
- [ ] Vinculación con la campana de notificaciones del compañero: nuestro
      módulo **escribe** notificaciones `ALERTA_ESTADISTICA` que la campana
      muestra, pero **no se modifica** su infraestructura (campana y bandeja).

### Fase 4 — Exportación
- [ ] Módulo de export PDF (`reportlab`) para los 4 formatos de reporte.
- [ ] Módulo de export Excel (`openpyxl` + `pandas`) con hojas por desglose.
- [ ] Cabecera de auditoría en ambos (período, sede, generador, fecha).

### Fase 5 — Dashboards y pulido
- [ ] KPIs y accesos en **los 6 dashboards** (Admin y Finanzas por los rápidos;
      Operaciones, Gerente, Subgerente y Director por el resto del equipo). El
      cuadro de **productos vencidos** lo añade el compañero como `include`
      compartido en los 5 dashboards operativos.
- [ ] Pruebas: tests de servicios (costo, snapshots, alarmas) y de endpoints.
- [ ] Revisión de rendimiento con datos históricos y de permisos por sede.

---

## 13. Riesgos y decisiones pendientes

| Tema | Decisión/riesgo |
|---|---|
| Valorización | Tomada: **último precio de compra** (promedio de las últimas 3 compras). Tomada: **las mermas históricas viejas NO se recalculan** (quedan con costo 0); solo las nuevas se valorizan al registrar. |
| Umbrales | Tomada: **global** (factor + mínimo absoluto). Pendiente: valores finales de factor y mínimo. |
| Monedas | Los reportes muestran BS/USD/EUR y el consolidado se reduce a USD. Pendiente: moneda por defecto en cada reporte. |
| Word | Tomada: **no se usa Word** (solo PDF y Excel). |
| Rendimiento | `statistics_snapshots` mitiga la lentitud con datos históricos grandes. Si el volumen crece mucho, futuro: índice por `(location_id, metric, period_type, period_start)` ya incluido en la clave única. |
| Central | Tomada: la **Central es una sede más** (almacén): compra en ella, distribuye por traslados y **no maneja gastos de cocina**. "La Central" = esa sede; "todas juntas" = suma de todas. |
| Traslados | Ampliado: además del **conteo semanal/mensual/trimestral/anual**, las **novedades con pérdida (ej. extravío) se valorizan a costo** y entran al consolidado como costo operativo. |
| Snapshot | Si no se refrescan ("Actualizar"), los reportes pueden mostrar datos viejos. Se propone refresco manual + automático al cerrar el período. |
| Módulo de notificaciones (compañero) | **Alcance:** su propuesta es **por su cuenta**: alarma de **productos vencidos** (cuadro en el Dashboard, clic → merma VENCEDO precargada y bloqueada, **sin migración**) + la familia de **respuestas del administrador** (ya existe, se mantiene intacta). El nuestro no entra ahí: solo escribimos notificaciones `ALERTA_ESTADISTICA`. |
| Coordinación de dashboards | Los **5 dashboards operativos** los toca el compañero (añade su cuadro de vencidos) y el equipo (bloques de estadísticas) → **Rápido 1 actúa como integrador** al final. Carpeta `tests/dashboard/` compartida: pruebas en archivos separados por autor. |

---

## 14. Glosario (no técnico)

| Término | Qué significa |
|---|---|
| KPI | Indicador clave (número que resume un aspecto del negocio, ej. "compras del mes"). |
| Snapshot | "Foto" de los totales ya calculados. Evita recalcular todo a cada clic. |
| Último precio de compra | El precio más reciente al que se compró un insumo; lo que costaría reponerlo hoy. |
| Promedio móvil | Promedio de los últimos períodos (ej. 3 meses). Línea base para detectar anomalías. |
| Umbral | Regla que dice cuándo algo es irregular (factor y mínimo absoluto). |
| UPSERT | Actualizar si el registro ya existe; crearlo si no. Evita duplicados al recalcular. |
| Migración Alembic | Mecanismo del proyecto para crear/modificar tablas de forma controlada. |
| Idempotente | Operación que puede repetirse sin causar efectos duplicados. |

---

## 15. Anexo D — División del trabajo y coordinación

> Explicación en lenguaje simple para todo el equipo. Cada persona toca **todas
> las capas** de su parte (la que piensa, la que busca datos, la que muestra y
> la prueba), siguiendo el patrón que ya usan los módulos de mermas y traslados.

### 15.1. Las tres partes de cada pantalla

| Parte | Nombre técnico | Qué hace |
|---|---|---|
| **La que piensa** | `service` | Hace las cuentas (ej. "esto cuesta 2 $ por kilo"). |
| **La que busca** | `repository` | Va a lo guardado y trae los datos (ej. "dame las compras de esta semana"). |
| **La que muestra** | plantilla + `js` + `css` | La página que se ve: tarjetas, gráficos, botones y estilos. |
| **La que revisa** | validador (`request`) | Rechaza datos mal escritos antes de que se guarden. |
| **La prueba** | `test` | Chequeo automático: "si pongo estos datos, sale esto". |

### 15.2. El "cajón común"

Rápido 1 deja **guardado** un resumen por sede (compras, cocina, mermas,
traslados). Los demás **no vuelven a calcular**: abren el cajón, sacan lo suyo y
lo muestran.

### 15.3. División (5 personas)

| Persona | Trabajo | Pantallas a terminar |
|---|---|---|
| **Rápido 1** | Fábrica de números + alarmas + configuración + **integrador** | Admin |
| **Rápido 2** | Reportes, comparativos, descargas | Finanzas |
| **Lento 1** | Solo sus portadas | Operaciones + Gerente |
| **Lento 2** | Solo sus portadas | Subgerente + Director |
| **Compañero** | **Su módulo aparte** (productos vencidos + respuestas del admin) | Solo su cuadro de vencidos |

### 15.4. Quién hace qué (en simple)

**Rápido 1 — "La fábrica de los números" (pocas piezas, pero difíciles)**

1. Enseñar cuánto cuesta cada cosa. Ejemplo con harina: se compra a **2 $** el
   kilo; una merma de la semana pasada vale **2 $** y queda así para siempre;
   esta semana el precio sube a **2,20 $** y las mermas nuevas valen **2,20 $**.
   Si hay dos proveedores con precios distintos, manda la **última compra**; si
   la merma dice su lote, se usa el precio exacto de ese lote.
2. El **resumen por sede** ("Actualizar datos"): deja en el cajón el gasto en
   compras, en cocina, las mermas y los traslados, por período.
3. Las **alarmas estadísticas** + la pantalla de **configuración** (factor y
   mínimo: con factor 2 y mínimo 100 $, una sede que pasa de 100 $ a 600 $
   avisa; si pasa de 40 $ a 90 $ **no** avisa porque son pocos $).
4. **Pantalla Admin** (resumen de toda la empresa).
5. **Integrador de dashboards**: une al final los bloques del equipo con el
   cuadro de vencidos del compañero, sin pisarse.

**Rápido 2 — "Los reportes y documentos" (más pantallas, pero mecánicas)**

1. Los **KPIs** (los numeritos de arriba de cada pantalla).
2. Los **5 reportes** (compras, cocina, mermas, traslados y consolidado), con
   filtros de sede, período y moneda, y el **comparativo** con el período
   anterior ("este mes 300 $ vs 250 $ → +20%"). El de compras también por
   **proveedor**.
3. El **ranking entre sedes** (quién gasta más, quién pierde más en mermas y
   extravíos).
4. **Descargas PDF y Excel**.
5. **Pantalla Finanzas** (gastos del mes, comparación, mermas más caras).

**Compañero — su módulo, por su cuenta**

Alarma de **productos vencidos** (cuadro en el Dashboard, cada lote clicable →
abre la merma VENCEDO precargada y bloqueada, **sin migración**) + la familia de
**respuestas del administrador** ya existente (intacta). Su propuesta es
independiente de la nuestra; solo coordinamos las 3 zonas de la sección 15.5.

**Lento 1 — Portadas de Operaciones y Gerente** (muestran números ya listos)

- **Operaciones**: productos por agotarse, alertas de stock bajo, traslados
  pendientes por recibir.
- **Gerente**: resumen ejecutivo (gasto del mes, mermas, comparación rápida).
- No toca funciones del módulo de estadísticas: solo hace que su pantalla se vea
  clara y muestre los datos correctos (con su parte de "pensar/buscar" y su
  prueba de que la página abre bien).

**Lento 2 — Portadas de Subgerente y Director**

- **Subgerente**: ya recibe una base hecha; completa su tarjeta de alarmas de su
  sede y su resumen.
- **Director**: vista panorámica de toda la empresa (qué sede va bien/mal,
  resumen del año, alarmas activas).

### 15.5. Zonas compartidas (cómo no chocamos)

| Zona | Quién la toca | Regla |
|---|---|---|
| **5 dashboards operativos** | Compañero (cuadro de vencidos) + equipo (bloques de estadísticas) | Cada uno deja su bloque; **Rápido 1 integra al final**. No borrar el `include` del otro. |
| **Campana / bandeja de notificaciones** | Compañero (dueño) | Nosotros solo **escribimos** notificaciones `ALERTA_ESTADISTICA` para que la campana las muestre; **no** se modifica su código. |
| **Carpeta `tests/dashboard/`** | Ambos | Pruebas en archivos separados por autor. |

### 15.6. Qué NO cuenta como trabajo del equipo

- **La migración** de `statistics_snapshots` (fuera de la división).
- **El módulo del compañero** (lo hace él solo).

### 15.7. Dependencias (falta de cruce)

1. **Rápido 1** llena el cajón (resúmenes guardados por sede).
2. **Rápido 2** y los dashboards **muestran** esos mismos números.
3. Las **alarmas** vigilan el cajón y avisan.

Si alguien necesita cambiar cómo se guardan los números, avisa primero a Rápido 1.
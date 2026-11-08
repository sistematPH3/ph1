from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.logistics.requests.purchase_validators import es_moneda_bs
from app.time_utils import utc_a_ve, ve_a_utc

DEFAULT_ADMIN_DAYS = 7
DEFAULT_OTHER_HOURS = 24
PARAM_ADMIN_DAYS = 'PURCHASE_ADMIN_EDIT_DAYS'
PARAM_OTHER_HOURS = 'PURCHASE_OTHER_EDIT_HOURS'
CERO = Decimal('0.00')


class PurchaseManagementService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _local_to_utc_bounds(start_date, end_date):
        """Convierte fechas locales (America/Caracas, UTC-4) a rangos UTC.

        El sistema guarda purchase_date en UTC; la fecha mostrada es local.
        Un día local D corresponde en UTC al intervalo [D 04:00, D+1 04:00).
        """
        start_dt = ve_a_utc(datetime.combine(start_date, time.min)) if start_date else None
        end_dt = (ve_a_utc(datetime.combine(end_date, time.min) + timedelta(days=1))
                  if end_date else None)
        return start_dt, end_dt

    def _get_time_limits(self):
        """Obtiene los límites de tiempo configurables desde app_parameters.

        Returns:
            dict: {'admin_days': int, 'other_hours': int}
        """
        params = self.repository.get_app_parameters()
        return {
            'admin_days': self._int_param(params, PARAM_ADMIN_DAYS, DEFAULT_ADMIN_DAYS),
            'other_hours': self._int_param(params, PARAM_OTHER_HOURS, DEFAULT_OTHER_HOURS),
        }

    @staticmethod
    def _int_param(params, key, default):
        """Lee un parámetro entero. Antes un valor no numérico en app_parameters
        reventaba con ValueError y devolvía 500 en todo el listado."""
        try:
            valor = int(str(params.get(key)).strip())
        except (TypeError, ValueError, AttributeError):
            return default
        return valor

    def _ventana_para_usuario(self, current_user):
        """Ventana máxima de edición/anulación que aplica a un usuario."""
        limits = self._get_time_limits()
        if getattr(current_user, 'role_id', None) == 1:
            return timedelta(days=limits['admin_days'])
        return timedelta(hours=limits['other_hours'])

    def can_modify(self, purchase, current_user, now=None):
        """Única fuente de verdad de si una compra admite edición/anulación.

        La usan tanto el listado (para el botón) como process_edit/process_annulment
        (para el POST), de modo que la UI nunca ofrezca algo que el backend vaya
        a rechazar ni al revés.
        """
        if purchase is None or not purchase.purchase_date:
            return False
        if purchase.status != 'COMPLETED':
            return False
        ahora = now or datetime.now(UTC).replace(tzinfo=None)
        # Se compara en UTC: purchase_date se guarda en UTC. Antes se usaba
        # .days sobre la diferencia, que trunca y convertía el límite de 7 días
        # del administrador en 8 (7d 23h pasaba el filtro).
        return (ahora - purchase.purchase_date) <= self._ventana_para_usuario(current_user)

    def _segundos_restantes(self, purchase, current_user, now=None):
        """Segundos que le quedan de ventana, para el contador del modal."""
        if purchase is None or not purchase.purchase_date:
            return 0
        ahora = now or datetime.now(UTC).replace(tzinfo=None)
        restante = self._ventana_para_usuario(current_user) - (ahora - purchase.purchase_date)
        return max(0, int(restante.total_seconds()))

    def _check_time_limit(self, purchase, current_user):
        """Valida si la compra está dentro del límite de tiempo para editar/anular.

        Raises:
            ValueError: Si excede el límite de tiempo o no admite la operación
        """
        if purchase is None:
            raise ValueError("La compra no existe.")
        if purchase.status == 'ANNULLED':
            raise ValueError("La compra ya está anulada.")
        if purchase.status != 'COMPLETED':
            raise ValueError(
                f"Solo las compras completadas pueden editarse o anularse "
                f"(estado actual: {purchase.status})."
            )
        if not purchase.purchase_date:
            raise ValueError("La compra no tiene fecha de registro.")

        if self.can_modify(purchase, current_user):
            return

        limits = self._get_time_limits()
        if getattr(current_user, 'role_id', None) == 1:
            raise ValueError(
                f"Acceso Denegado: Los Administradores solo pueden operar facturas "
                f"registradas en los últimos {limits['admin_days']} días."
            )
        raise ValueError(
            f"Acceso Denegado: El límite de {limits['other_hours']} horas para "
            f"operar esta factura ha expirado."
        )

    def get_formatted_history(self, current_user, start_date=None, end_date=None, supplier_id=None, status=None):
        start_dt, end_dt = self._local_to_utc_bounds(start_date, end_date)

        raw_purchases = self.repository.get_filtered_history(
            start_date=start_dt,
            end_date=end_dt,
            supplier_id=supplier_id,
            status=status
        )

        formatted_history = []
        now = datetime.now(UTC).replace(tzinfo=None)

        for purchase, supplier_name in raw_purchases:
            total_amount = purchase.total_amount if purchase.total_amount is not None else CERO
            # En Bs el monto ya es bolívares: no se multiplica por la tasa.
            exchange_rate = purchase.exchange_rate if purchase.exchange_rate is not None else None
            if es_moneda_bs(purchase.currency):
                total_bs = total_amount
            elif exchange_rate is None:
                # Sin tasa no se puede convertir. Antes se devolvía 0,00, que
                # en pantalla parecía una compra de cero bolívares.
                total_bs = None
            else:
                total_bs = (total_amount * exchange_rate).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)

            formatted_history.append({
                'id': purchase.id,
                'supplier_id': purchase.supplier_id,
                'supplier_name': supplier_name if supplier_name else "Proveedor N/A",
                'purchase_date': utc_a_ve(purchase.purchase_date),
                'total_amount': total_amount,
                'total_bs': total_bs,
                'currency': purchase.currency,
                'exchange_rate': exchange_rate,
                'invoice_url': purchase.invoice_url,
                'status': purchase.status,
                'can_modify': self.can_modify(purchase, current_user, now)
            })

        return formatted_history

    def get_purchase_details_summary(self, purchase_id, current_user=None):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            return None

        details = self.repository.get_details_by_purchase_id(purchase_id)
        limits = self._get_time_limits()
        return {
            "purchase": purchase,
            "details": details,
            "time_limits": {
                "admin_days": limits['admin_days'],
                "other_hours": limits['other_hours']
            },
            "can_modify": (self.can_modify(purchase, current_user)
                           if current_user is not None else False),
            "remaining_seconds": (self._segundos_restantes(purchase, current_user)
                                  if current_user is not None else 0)
        }

    def process_annulment(self, purchase_id, current_user):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            raise ValueError("La compra no existe.")

        self._check_time_limit(purchase, current_user)
        return self.repository.logical_annulment(purchase_id, current_user.id)

    def process_edit(self, purchase_id, current_user, new_items, reason):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            raise ValueError("La compra no existe.")

        self._check_time_limit(purchase, current_user)
        return self.repository.logical_edit(purchase_id, current_user.id, new_items, reason)

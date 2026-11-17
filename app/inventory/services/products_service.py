import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from app.inventory.repositories.products_repository import ProductRepository
from app.inventory.number_utils import normalize_decimal_string
from app.models.inventory_model import (
    Product,
    Inventory,
    PRODUCT_NUMERIC_MAX,
    PRODUCT_NUMERIC_MAX_LABEL,
)


def _clean_decimal(raw, label):
    """Normaliza un campo NUMERIC(10, 2) antes de tocar la base de datos.

    Vacío se conserva como None para llamadas internas; el mínimo de stock
    tiene su propia validación obligatoria en _clean_min_stock.
    """
    if raw is None or str(raw).strip() == '':
        return None
    raw = normalize_decimal_string(raw)
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label} debe ser un número válido.')
    if not value.is_finite():
        raise ValueError(f'{label} debe ser un número válido.')
    if value < 0:
        raise ValueError(f'{label} no puede ser negativo.')
    if value > PRODUCT_NUMERIC_MAX:
        raise ValueError(f'{label} no puede superar {PRODUCT_NUMERIC_MAX_LABEL}, '
                         'el máximo que soporta la base de datos.')
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _clean_waste_limit(raw):
    return _clean_decimal(raw, 'El límite de merma')


def _clean_min_stock(raw):
    # Sin valor por defecto: el mínimo es obligatorio en creación y edición.
    if raw is None or str(raw).strip() == '':
        raise ValueError('El mínimo de stock es obligatorio.')
    return _clean_decimal(raw, 'El mínimo de stock')


class ProductService:

    @staticmethod
    def get_listed_products(search_query=None):
        if search_query:
            cleaned_query = search_query.strip()
            return ProductRepository.search_by_name_or_sku(cleaned_query)
        return ProductRepository.get_all_active()

    @staticmethod
    def get_product_by_id(product_id):
        return ProductRepository.find_by_id(product_id)

    @staticmethod
    def create_product(data):
        raw_sku = data.get('sku', '')
        cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper())

        existing_product = ProductRepository.find_by_sku(cleaned_sku)
        if existing_product:
            raise ValueError(f"El SKU '{cleaned_sku}' ya está registrado.")

        # CAMBIO AQUÍ: Se instancia con product_type_id
        new_product = Product(
            name=data.get('name', '').strip(),
            sku=cleaned_sku,
            product_type_id=data.get('product_type_id'),
            unit_of_measure=data.get('unit_of_measure', '').strip(),
            technical_description=data.get('technical_description', '').strip(),
            waste_limit=_clean_waste_limit(data.get('waste_limit')),
            min_stock=_clean_min_stock(data.get('min_stock')),
            is_active=True
        )

        return ProductRepository.save(new_product)

    @staticmethod
    def update_product(product_id, data):
        product = ProductRepository.find_by_id(product_id)
        if not product:
            raise ValueError("El producto que intenta editar no existe.")

        name = data.get('name', '').strip()
        tech_desc = data.get('technical_description', '').strip()
        unit_of_measure = data.get('unit_of_measure', '').strip()
        
        raw_sku = data.get('sku', '')
        cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper())

        if product.sku != cleaned_sku:
            existing_product = ProductRepository.find_by_sku(cleaned_sku)
            if existing_product:
                raise ValueError(f"El SKU '{cleaned_sku}' ya está registrado por otro insumo.")

        product.name = name
        # CAMBIO AQUÍ: Se actualiza product_type_id
        product.product_type_id = data.get('product_type_id')
        product.unit_of_measure = unit_of_measure
        product.sku = cleaned_sku
        product.technical_description = tech_desc
        product.waste_limit = _clean_waste_limit(data.get('waste_limit'))
        product.min_stock = _clean_min_stock(data.get('min_stock'))

        if 'is_active' in data:
            product.is_active = data.get('is_active') in ['True', True, 1, '1']

        # Sincronizar el mínimo en los inventarios existentes del insumo para
        # que el valor configurado aplique en todas las sedes.
        Inventory.query.filter_by(product_id=product.id).update(
            {Inventory.min_stock: Decimal(str(product.min_stock_efectivo))},
            synchronize_session=False,
        )

        return ProductRepository.save(product)
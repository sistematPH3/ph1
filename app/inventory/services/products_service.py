import re
from app.inventory.repositories.products_repository import ProductRepository
from app.models.inventory_model import Product

#archivo de Diego

class ProductService:

    @staticmethod
    def get_listed_products(search_query=None):
        """
        Determina si devuelve la lista completa de activos o aplica
        el filtro sanitizado en el repositorio si hay una búsqueda.
        """
        if search_query:
            cleaned_query = search_query.strip() # Validación tipo Strip
            return ProductRepository.search_by_name_or_sku(cleaned_query)
        return ProductRepository.get_all_active()

    @staticmethod
    def create_product(data):
        raw_sku = data.get('sku', '')
        cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper())

        existing_product = ProductRepository.find_by_sku(cleaned_sku)
        if existing_product:
            raise ValueError(f"El SKU '{cleaned_sku}' ya está registrado.")

        new_product = Product(
            name=data.get('name', '').strip(),
            sku=cleaned_sku,
            category_id=data.get('category_id'),
            quantity=data.get('quantity', 0),
            unit_of_measure=data.get('unit_of_measure', '').strip(),
            technical_description=data.get('technical_description', '').strip(),
            is_active=True
        )

        return ProductRepository.save(new_product)

    @staticmethod
    def update_existing_product(product_id, data):
        """
        Lógica de negocio para editar un insumo. Aplica sanitización,
        formatea el SKU manual y valida que no se duplique.
        """
        product = ProductRepository.find_by_id(product_id)
        if not product:
            raise ValueError("El producto que intenta editar no existe.")

        # 1. Sanitización exhaustiva de textos (Validación tipo Strip)
        name = data.get('name', '').strip()
        tech_desc = data.get('technical_description', '').strip()
        unit = data.get('unit', '').strip()
        
        # 2. Sanitización estricta del SKU Manual
        raw_sku = data.get('sku', '')
        cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper()) # Remueve caracteres raros y espacios

        # 3. Control estricto de Unicidad
        # Solo verificamos si el usuario cambió el SKU original por uno nuevo
        if product.sku != cleaned_sku:
            existing_product = ProductRepository.find_by_sku(cleaned_sku)
            if existing_product:
                raise ValueError(f"El SKU '{cleaned_sku}' ya está registrado por otro insumo.")

        # 4. Asignación de nuevos valores al modelo existente
        product.name = name
        product.category_id = data.get('category_id')
        product.unit = unit
        product.quantity = data.get('quantity', 0)
        product.sku = cleaned_sku
        product.technical_description = tech_desc
        # Mantiene o actualiza el estado lógico (True/False)
        product.is_active = data.get('is_active') == 'True' or data.get('is_active') is True

        return ProductRepository.save(product)
import re
from app.inventory.repositories.products_repository import ProductRepository
from app.models.inventory_model import Product

class ProductService:

    @staticmethod
    def get_listed_products(search_query=None):
        if search_query:
            cleaned_query = search_query.strip()
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
        product.category_id = data.get('category_id')
        product.unit_of_measure = unit_of_measure
        product.quantity = data.get('quantity', 0)
        product.sku = cleaned_sku
        product.technical_description = tech_desc
        
        if 'is_active' in data:
            product.is_active = data.get('is_active') in ['True', True, 1, '1']

        return ProductRepository.save(product)
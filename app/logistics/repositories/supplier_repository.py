# Suponiendo que usas una conexión de psycopg2 o similar para PostgreSQL
class SupplierRepository:
    def __init__(self, db_connection):
        self.db = db_connection

    def save(self, supplier_data):
        query = """
            INSERT INTO suppliers (name, tax_id, contact_name, phone, email, status)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
        """
        cursor = self.db.cursor()
        cursor.execute(query, (
            supplier_data.name,
            supplier_data.tax_id,
            supplier_data.contact_name,
            supplier_data.phone,
            supplier_data.email,
            supplier_data.status
        ))
        self.db.commit()
        generated_id = cursor.fetchone()[0]
        cursor.close()
        return generated_id
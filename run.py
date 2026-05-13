from app import create_app, db
from flask_migrate import Migrate

app = create_app()

# ESTA ES LA CLAVE: Flask-Migrate necesita vincularse a la app y a la db aquí
migrate = Migrate(app, db)

if __name__ == "__main__":
    app.run(debug=True)
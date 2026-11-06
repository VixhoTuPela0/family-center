# Family Center

Family Center es un archivo multimedia familiar privado para conservar recuerdos, documentos, fotografías y la historia de la familia en un solo lugar.

## Qué se puede hacer

- Subir fotografías, videos, audios, documentos y cartas.
- Organizar recuerdos en álbumes y slides.
- Buscar y explorar recuerdos por fecha, categoría y personas.
- Etiquetar a personas de la familia en los recuerdos.
- Controlar la visibilidad de los recuerdos y compartirlos con usuarios autorizados.
- Administrar personas, categorías, álbumes y usuarios.
- Visualizar documentos, PDFs, imágenes, videos y audios desde la aplicación.

## Tecnologías

- Frontend: React y Vite.
- API: FastAPI y SQLAlchemy.
- Base de datos: PostgreSQL.
- Despliegue local: Docker Compose.

## Configuración

1. Copia `.env.example` a `.env`.
2. Completa las variables de entorno necesarias.
3. Inicia los servicios:

```bash
docker compose up -d --build
```

La aplicación web queda disponible en `http://localhost:1234`.

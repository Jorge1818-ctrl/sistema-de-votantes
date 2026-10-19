# Sistema de Registro de Votantes

Aplicación Streamlit para administrar registros de personas y consultar estadísticas agrupadas por partido.

## Ejecutar

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

En el primer inicio, la aplicación solicita crear una cuenta de administrador. Los archivos `usuarios.json` y `votantes.csv` se crean localmente en el directorio de ejecución y están excluidos de Git.

## Datos personales

Los registros pueden contener CURP, domicilio y afiliación política. La aplicación guarda esos datos en un CSV local sin cifrar; no la uses con información real sin implementar controles adecuados de privacidad, acceso, respaldo y protección de datos.

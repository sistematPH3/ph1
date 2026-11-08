@echo off
:: Navegamos a la carpeta raíz del proyecto (subiendo 3 niveles desde app/integrations/api_bcv/)
cd /d "%~dp0..\..\.."

:: Ejecutamos el script usando el ejecutable de Python del entorno virtual
.\.venv\Scripts\python.exe app/integrations/api_bcv/tasks_bcv.py

:: Pausa opcional: si quieres ver el resultado después de ejecutarse, quita el "::" de la línea de abajo
:: pause
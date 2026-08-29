/**
 * movement_audit.js
 * Lógica para la vista de Auditoría Forense de Logística.
 * Formatea los objetos JSONB inmutables extraídos de la base de datos 
 * para presentarlos con indentación y estructura legible.
 */

document.addEventListener("DOMContentLoaded", function() {
    // Seleccionar todos los bloques de código que contienen trazas JSON
    const jsonBlocks = document.querySelectorAll('.json-data');
    
    jsonBlocks.forEach(block => {
        try {
            // Extraer el texto en crudo inyectado por Jinja2
            const rawData = block.getAttribute('data-json');
            
            // Prevención: Si el campo de base de datos está vacío o es nulo
            if (!rawData || rawData === 'null' || rawData.trim() === '') {
                block.textContent = "{}";
                return;
            }
            
            // Parsear a objeto de JavaScript
            const parsedData = JSON.parse(rawData);
            
            // Convertir nuevamente a String pero aplicando una indentación de 4 espacios
            block.textContent = JSON.stringify(parsedData, null, 4);
            
        } catch (error) {
            console.error("Error formateando la estructura JSONB de auditoría: ", error);
            // Fallback en caso de que la data esté corrupta o no sea formato JSON válido
            block.textContent = "Error al decodificar la traza forense. Datos ilegibles.";
        }
    });
});
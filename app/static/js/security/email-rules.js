/**
 * Componente compartido de validacion de correo.
 *
 * Antes cada formulario decidia por su cuenta: registro usaba un regex, pero
 * login y "recuperar contrasena" solo comprobaran que el texto incluyera '@'.
 * Eso dejaba pasar cosas que el backend rechazaba ('sinarroba@', 'a@b'), y el
 * usuario se enteraba del error al enviar, no al escribir.
 *
 * Aqui los tres usan la MISMA regla. El patron llega del backend
 * (PATRON_EMAIL de app/security/requests/auth_validators.py) via data-*, igual
 * que las reglas de contrasena, de modo que no pueden quedar desincronizados.
 *
 * No se exige ningun dominio en concreto: cualquier correo con '@' y dominio
 * con punto es valido (karol123@galletita.com, carlos@hotmail.com...).
 */
(function (global) {
    'use strict';

    // Copia de PATRON_EMAIL por si el atributo data-email-pattern no llegara.
    var POR_DEFECTO = '[^@\\s]+@[^@\\s.]+(\\.[^@\\s.]+)+';

    var cache = {};

    function obtenerPatron(raiz) {
        if (raiz && raiz.dataset && raiz.dataset.emailPattern) {
            return raiz.dataset.emailPattern;
        }
        return POR_DEFECTO;
    }

    function regexDe(raiz) {
        var patron = obtenerPatron(raiz);
        if (!cache[patron]) {
            cache[patron] = new RegExp('^' + patron + '$');
        }
        return cache[patron];
    }

    /** True si el correo tiene '@' y un dominio valido. */
    function esValido(email, raiz) {
        if (!email || typeof email !== 'string') return false;
        return regexDe(raiz).test(email.trim());
    }

    /** Mensaje unico para los tres formularios. */
    function mensaje() {
        return 'Ingresa un correo electrónico válido: debe incluir un "@" y un dominio, por ejemplo nombre@correo.com.';
    }

    global.EmailRules = {
        esValido: esValido,
        mensaje: mensaje,
        PATRON_POR_DEFECTO: POR_DEFECTO
    };
})(window);

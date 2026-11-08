/**
 * Componente compartido de validacion de contrasena.
 *
 * Resuelve el problema de la validacion en cascata: antes solo se mostraba UN
 * error a la vez, asi que el usuario iba descubriendo las reglas por descarte
 * (primero el largo, despues el simbolo, despues la mayuscula).
 *
 * Aqui las tres reglas se muestran siempre y cada una se marca en verde en
 * cuanto se cumple. El error en rojo aparece solo al intentar enviar.
 *
 * Las reglas vienen del backend (REGLAS_PASSWORD) via data-*, de modo que
 * frontend y backend no pueden quedar desincronizados.
 */
(function (global) {
    'use strict';

    var POR_DEFECTO = { min: 6, max: 12, upper: true, special: true };

    function leerReglas(raiz) {
        if (!raiz) return POR_DEFECTO;
        return {
            min: parseInt(raiz.dataset.passwordMin, 10) || POR_DEFECTO.min,
            max: parseInt(raiz.dataset.passwordMax, 10) || POR_DEFECTO.max,
            upper: raiz.dataset.passwordRequireUpper === 'true',
            special: raiz.dataset.passwordRequireSpecial === 'true'
        };
    }

    function evaluar(pwd, reglas) {
        return {
            length: pwd.length >= reglas.min && pwd.length <= reglas.max,
            tooLong: pwd.length > reglas.max,
            upper: !reglas.upper || /[A-Z]/.test(pwd),
            special: !reglas.special || /[^A-Za-z0-9]/.test(pwd)
        };
    }

    function reglaNoCumplida(estado, reglas) {
        if (estado.tooLong) {
            return 'La contraseña no puede tener más de ' + reglas.max + ' caracteres.';
        }
        if (!estado.length) {
            return 'La contraseña debe tener entre ' + reglas.min + ' y ' + reglas.max + ' caracteres.';
        }
        if (!estado.special) {
            return 'Esta contraseña debe incluir caracteres especiales.';
        }
        if (!estado.upper) {
            return 'Esta contraseña debe incluir al menos una letra mayúscula.';
        }
        return '';
    }

    function textoRegla(estado, reglas) {
        if (estado.length) {
            return 'Entre ' + reglas.min + ' y ' + reglas.max + ' caracteres';
        }
        if (estado.tooLong) {
            return 'Máximo ' + reglas.max + ' caracteres';
        }
        return 'Mínimo ' + reglas.min + ' caracteres';
    }

    /**
     * @param {Object} opciones
     *   input    - campo de contrasena
     *   lista    - <ul> con los <li data-rule="...">
     *   contador - elemento donde se muestra n/max
     *   onChange  - callback con el estado, para que el submit pueda reutilizarlo
     */
    function init(opciones) {
        var input = opciones.input;
        var lista = opciones.lista;
        var contador = opciones.contador;
        if (!input) return null;

        var reglas = leerReglas(input.form || input.closest('form') || input);
        var items = lista ? Array.prototype.slice.call(lista.querySelectorAll('[data-rule]')) : [];

        function pintar() {
            var pwd = input.value;
            var estado = evaluar(pwd, reglas);

            items.forEach(function (li) {
                var regla = li.dataset.rule;
                var cumplida = estado[regla];
                li.classList.toggle('is-ok', !!cumplida);
                if (regla === 'length') {
                    var span = li.querySelector('[data-rule-text]');
                    if (span) span.textContent = textoRegla(estado, reglas);
                }
            });

            if (contador) {
                contador.textContent = pwd.length + '/' + reglas.max;
                contador.classList.toggle('is-warn', pwd.length >= reglas.max);
                contador.classList.toggle('is-over', pwd.length > reglas.max);
            }

            lista && lista.classList.toggle('is-active', pwd.length > 0);

            if (typeof opciones.onChange === 'function') {
                opciones.onChange(estado, reglaNoCumplida(estado, reglas));
            }
        }

        input.addEventListener('input', pintar);
        pintar();

        return { reglas: reglas, estado: function () { return evaluar(input.value, reglas); },
                 problema: function () { return reglaNoCumplida(evaluar(input.value, reglas), reglas); } };
    }

    global.PasswordRules = {
        init: init,
        evaluar: evaluar,
        leerReglas: leerReglas,
        reglaNoCumplida: reglaNoCumplida
    };
})(window);

/**
 * attention_list.js — filtros avanzados del listado de atenciones.
 * Los selects y las fechas con la clase ``js-autosubmit`` envían el
 * formulario al cambiar (la búsqueda y el estado ya los maneja crud.js).
 * Al cambiar el tipo se limpia la sub atención, porque sus opciones
 * dependen del tipo elegido. Sin el envío no hay página: vuelve a la 1.
 */
(function () {
  'use strict';
  var form = document.getElementById('toolbarForm');
  if (!form) return;
  form.querySelectorAll('.js-autosubmit').forEach(function (control) {
    control.addEventListener('change', function () {
      if (control.id === 'tipo') {
        var sub = document.getElementById('subtipo');
        if (sub) sub.value = '';
      }
      form.submit();
    });
  });
})();

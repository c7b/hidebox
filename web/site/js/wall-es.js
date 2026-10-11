// SPDX-License-Identifier: MIT
// The exit wall's words in Spanish: stage directions, cue labels and fates (11-brand §9.3 S1).
export default {
  script: ['(Una pared de archivos cifrados. No vemos dentro de ninguno. Cada luz significa: esperando su señal.)',
    '(Alguien abre un enlace. Una vez.)', '(Tercera vista.)', '(Medianoche.)', '(Los demás: abiertos, vencidos, borrados.)',
    '(Queda una luz encendida.)'],
  data: { intro: '(Los últimos archivos guardados en nuestro servidor, por su regla de salida: no de quién, no qué, no si ya se fueron. No vemos dentro de ninguno.)',
    once: '(Una vez: la primera apertura es la señal.)', views: '(Vistas: la última vista permitida es la señal.)',
    time: '(Con hora: el reloj es la señal.)', kept: '(Guardados: la señal la da su dueño al borrar.)',
    end: '(Queda una luz encendida: un archivo que ciframos nosotros.)' },
  views: ['(3 vistas)', '(2 vistas)', '(1 vista)'],
  labels: { once: '(una vez)', views: '(vistas)', time: '(con hora)', kept: '(solo yo)', empty: '' },
  fates: { once: 'su señal: la primera apertura.', views: 'su señal: la última vista.', time: 'su señal: el reloj.',
    kept: 'su señal: que su dueño lo borre.', empty: 'vacío.' },
  yours: '(el tuyo)',
  desc: (n) => `Una pared de casilleros hecha con los últimos ${n} archivos guardados en nuestro servidor: cada etiqueta es solo su regla de salida, nunca un nombre, su contenido ni si ya se fue. No vemos dentro de ninguno. La escena adelanta cada señal hasta que queda una luz: un archivo que ciframos nosotros.`,
};

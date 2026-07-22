/** @type {import('tailwindcss').Config} */
// As categorias de flash sao convertidas em nomes de classe pelo Jinja
// (ex.: bg-{{ color }}-50). O compilador nao infere interpolacoes, entao
// as variantes usadas ficam na safelist.
const flashColors = ['green', 'red', 'amber', 'blue', 'slate'];

module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#1d4ed8',
          dark: '#1e3a8a',
          light: '#3b82f6',
        },
      },
    },
  },
  safelist: [
    ...flashColors.flatMap((color) => [
      `bg-${color}-50`,
      `border-${color}-200`,
      `text-${color}-500`,
      `text-${color}-700`,
      `text-${color}-800`,
      `hover:text-${color}-700`,
    ]),
  ],
  plugins: [],
};

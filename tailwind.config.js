/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#173848',
        teal: '#087e83',
        cream: '#f7f8f6',
      },
      fontFamily: { sans: ['Noto Sans', 'Segoe UI', 'Arial', 'sans-serif'] },
    },
  },
  plugins: [],
}

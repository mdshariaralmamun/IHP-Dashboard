import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
        mono: ['SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', '"Liberation Mono"', '"Courier New"', 'monospace'],
      },
      colors: {
        primary: {
          DEFAULT: 'var(--kaust-primary)',
          hover: 'var(--kaust-primary-hover)',
        },
        apple: {
          bg: 'var(--color-bg)',
          surface: 'var(--color-surface)',
          text: 'var(--color-text)',
          muted: 'var(--color-muted)',
          border: 'var(--color-border)',
          primary: 'var(--color-primary)',
        },
        kaust: {
          blue: 'var(--kaust-blue)',
          green: 'var(--kaust-green)',
          gold: 'var(--kaust-gold)',
          text: 'var(--kaust-text)',
          surface: 'var(--kaust-surface)',
          border: 'var(--kaust-border)',
        },
        status: {
          ai: '#A885D8',
          approved: '#34C759',
          warning: '#FF9500',
          rejected: '#FF3B30',
        },
        orange: {
          50: '#FFF7ED',
          100: '#FFEDD5',
          200: '#FED7AA',
          300: '#FDCC8E',
          400: '#FB923C',
          500: '#FF923C',
          600: '#DD6B20',
          700: '#B45309',
          800: '#92400E',
          900: '#78350F',
        },
      },
      boxShadow: {
        'apple-float': '0 20px 40px -10px rgba(0, 0, 0, 0.08)',
        'apple-float-dark': '0 20px 40px -10px rgba(0, 0, 0, 0.3)',
      },
    },
  },
  plugins: [],
};

export default config;
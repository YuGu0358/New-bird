/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Backgrounds (dark-only)
        ink: {
          950: '#0A0E14', // app body
          900: '#0F1923', // panel bg
          850: '#141C28', // hover container
          800: '#1E2A38', // card
          700: '#26344A', // active state
        },
        // Steel (primary brand)
        steel: {
          50:  '#E8ECF1', // primary text
          100: '#B8C4D0', // body text
          200: '#7C8A9A', // secondary text
          300: '#4A5868', // disabled
          400: '#2A3645', // borders
          500: '#5BA3C6', // PRIMARY accent
          600: '#3D7FA5', // hover
          700: '#7FB8D9', // weak link
          800: '#26344A',
        },
        // Functional / data
        bull: {
          DEFAULT: '#26D9A5',
          weak: '#1A9E7A',
          tint: 'rgba(38,217,165,0.15)',
        },
        bear: {
          DEFAULT: '#FF5C7A',
          weak: '#CC4060',
          tint: 'rgba(255,92,122,0.15)',
        },
        warn: {
          DEFAULT: '#F0B43C',
          tint: 'rgba(240,180,60,0.15)',
        },
        social: {
          DEFAULT: '#A285E8',
          tint: 'rgba(162,133,232,0.15)',
        },
        accent: {
          neon: '#7AFFE0',
          silver: '#D4DBE3',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Monaco', 'monospace'],
      },
      fontSize: {
        // Override defaults to match design system stairs
        'caption': ['11px', { lineHeight: '16px', letterSpacing: '0.06em' }],
        'h3':      ['14px', { lineHeight: '20px', letterSpacing: '0.05em' }],
        'body-sm': ['13px', { lineHeight: '20px' }],
        'body':    ['14px', { lineHeight: '22px' }],
        'h2':      ['18px', { lineHeight: '26px' }],
        'h1':      ['24px', { lineHeight: '32px' }],
        'display': ['32px', { lineHeight: '40px' }],
        'num-md':  ['16px', { lineHeight: '22px' }],
        'num-lg':  ['22px', { lineHeight: '28px' }],
      },
      borderRadius: {
        'sm': '4px',
        DEFAULT: '6px',
        'md': '6px',
        'lg': '8px',
      },
      boxShadow: {
        'focus': '0 0 0 3px rgba(91,163,198,0.20)',
        'focus-error': '0 0 0 3px rgba(255,92,122,0.15)',
      },
      transitionDuration: {
        DEFAULT: '150ms',
        '250': '250ms',
      },
    },
  },
  plugins: [],
};

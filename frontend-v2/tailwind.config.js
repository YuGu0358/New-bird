/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Backgrounds (pure void → elevated surface)
        void:     '#050508',
        surface:  '#0E0F14',
        elevated: '#151620',
        grid:     '#0A0B10',
        // Text
        'text-primary':   '#F0F2FA',
        'text-secondary': '#8B8FA3',
        'text-muted':     '#4A4D5C',
        // Borders
        'border-subtle': '#1F2028',
        'border-accent': '#2D2F40',
        // Neon accents
        cyan: {
          DEFAULT: '#14F1D9',     // primary brand
          dim:     '#0DC4B0',
        },
        magenta: {
          DEFAULT: '#FF2D92',
          dim:     '#CC2475',
        },
        // Functional / data
        profit: {
          DEFAULT: '#00D980',
          dim:     '#00A663',
          tint:    'rgba(0,217,128,0.15)',
        },
        loss: {
          DEFAULT: '#FF3366',
          dim:     '#CC2952',
          tint:    'rgba(255,51,102,0.15)',
        },
        warn: {
          DEFAULT: '#FFAA00',
          tint:    'rgba(255,170,0,0.15)',
        },
        social: {
          DEFAULT: '#A285E8',
          tint:    'rgba(162,133,232,0.15)',
        },
        // Backwards-compat aliases — old code that still references these still works
        'ink': {
          950: '#050508',
          900: '#0E0F14',
          850: '#151620',
          800: '#0E0F14',
          700: '#1F2028',
        },
        'steel': {
          50:  '#F0F2FA',
          100: '#F0F2FA',
          200: '#8B8FA3',
          300: '#4A4D5C',
          400: '#1F2028',
          500: '#14F1D9',     // re-routes "steel-500" hits to neon cyan
          600: '#0DC4B0',
          700: '#14F1D9',
          800: '#1F2028',
        },
        'bull': {
          DEFAULT: '#00D980',
          weak:    '#00A663',
          tint:    'rgba(0,217,128,0.15)',
        },
        'bear': {
          DEFAULT: '#FF3366',
          weak:    '#CC2952',
          tint:    'rgba(255,51,102,0.15)',
        },
        accent: {
          neon:   '#14F1D9',
          silver: '#8B8FA3',
        },
      },
      fontFamily: {
        display: ['"Chakra Petch"', 'Geist', 'sans-serif'],
        sans:    ['Geist', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      fontSize: {
        'caption': ['10px', { lineHeight: '14px', letterSpacing: '0.15em' }],
        'h3':      ['10px', { lineHeight: '14px', letterSpacing: '0.15em' }],
        'body-sm': ['12px', { lineHeight: '18px' }],
        'body':    ['13px', { lineHeight: '20px' }],
        'h2':      ['14px', { lineHeight: '20px', letterSpacing: '0.15em' }],
        'h1':      ['28px', { lineHeight: '34px', letterSpacing: '-0.01em' }],
        'display': ['42px', { lineHeight: '46px', letterSpacing: '-0.01em' }],
        'num-md':  ['18px', { lineHeight: '22px', letterSpacing: '-0.01em' }],
        'num-lg':  ['28px', { lineHeight: '32px', letterSpacing: '-0.02em' }],
      },
      borderRadius: {
        DEFAULT: '0',
        sm: '0',
        md: '0',
        lg: '0',
      },
      boxShadow: {
        'glow-cyan':    '0 0 6px #14F1D9',
        'glow-cyan-lg': '0 0 12px rgba(20,241,217,0.5)',
        'glow-profit':  '0 0 6px #00D980',
        'glow-loss':    '0 0 6px #FF3366',
        'glow-warn':    '0 0 6px #FFAA00',
        'focus':        '0 0 0 1px #14F1D9',
        'focus-error':  '0 0 0 1px #FF3366',
      },
      transitionDuration: {
        DEFAULT: '150ms',
        '250': '250ms',
      },
      animation: {
        pulse: 'pulse 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

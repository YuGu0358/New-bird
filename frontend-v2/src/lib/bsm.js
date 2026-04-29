// Black-Scholes-Merton pricing — teaching/sandbox tool, NOT a production pricing engine.

const DEFAULT_RATE = 0.045;

/**
 * Abramowitz & Stegun 7.1.26 erf approximation. Max error ~1.5e-7.
 * @param {number} x
 * @returns {number}
 */
function erf(x) {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const a1 =  0.254829592;
  const a2 = -0.284496736;
  const a3 =  1.421413741;
  const a4 = -1.453152027;
  const a5 =  1.061405429;
  const p  =  0.3275911;
  const t = 1 / (1 + p * ax);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return sign * y;
}

/**
 * Standard normal CDF.
 * @param {number} x
 * @returns {number}
 */
function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

/**
 * Standard normal PDF.
 * @param {number} x
 * @returns {number}
 */
function normPdf(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}

/**
 * @typedef {Object} BsmInput
 * @property {number} spot       Current underlying price
 * @property {number} strike     Strike price
 * @property {number} t          Years to expiry (e.g. 7/365)
 * @property {number} [r]        Risk-free rate (default 0.045)
 * @property {number} sigma      Annualised IV (e.g. 0.32 for 32%)
 * @property {'call'|'put'} side
 */

/**
 * @typedef {Object} GreeksResult
 * @property {number} price
 * @property {number} delta
 * @property {number} gamma
 * @property {number} theta  Per-day theta
 * @property {number} vega   Per 1-vol-point (1% IV change)
 * @property {number} rho    Per 1% rate change
 */

/**
 * Returns the BSM mid price for the option.
 * @param {BsmInput} input
 * @returns {number}
 */
export function priceOption({ spot, strike, t, r = DEFAULT_RATE, sigma, side }) {
  if (!(spot > 0) || !(strike > 0) || !(sigma > 0) || !(t > 0)) {
    return 0;
  }
  const sqrtT = Math.sqrt(t);
  const d1 = (Math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  if (side === 'call') {
    return spot * normCdf(d1) - strike * Math.exp(-r * t) * normCdf(d2);
  }
  return strike * Math.exp(-r * t) * normCdf(-d2) - spot * normCdf(-d1);
}

/**
 * Returns price plus first-order Greeks for the option.
 * @param {BsmInput} input
 * @returns {GreeksResult}
 */
export function greeks({ spot, strike, t, r = DEFAULT_RATE, sigma, side }) {
  if (!(spot > 0) || !(strike > 0) || !(sigma > 0) || !(t > 0)) {
    return { price: 0, delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0 };
  }
  const sqrtT = Math.sqrt(t);
  const d1 = (Math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  const pdfD1 = normPdf(d1);
  const discount = Math.exp(-r * t);
  const isCall = side === 'call';
  const price = isCall
    ? spot * normCdf(d1) - strike * discount * normCdf(d2)
    : strike * discount * normCdf(-d2) - spot * normCdf(-d1);
  const delta = isCall ? normCdf(d1) : normCdf(d1) - 1;
  const gamma = pdfD1 / (spot * sigma * sqrtT);
  const thetaAnnual = isCall
    ? -(spot * pdfD1 * sigma) / (2 * sqrtT) - r * strike * discount * normCdf(d2)
    : -(spot * pdfD1 * sigma) / (2 * sqrtT) + r * strike * discount * normCdf(-d2);
  const theta = thetaAnnual / 365;
  const vega = (spot * pdfD1 * sqrtT) / 100;
  const rho = isCall
    ? (strike * t * discount * normCdf(d2)) / 100
    : -(strike * t * discount * normCdf(-d2)) / 100;
  return { price, delta, gamma, theta, vega, rho };
}

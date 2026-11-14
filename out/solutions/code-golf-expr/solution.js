// evalExpr(s): tiny arithmetic language (+ - * /, decimals, parens, precedence).
// Recursive descent: expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ;
// factor := number | '(' expr ')' | ('+'|'-') factor. Original work for AIProve.
function evalExpr(s) {
  let i = 0;
  const peek = () => s[i];
  const eat = () => s[i++];
  function skipWs() { while (i < s.length && /\s/.test(s[i])) i++; }
  function parseExpr() {
    let v = parseTerm();
    for (;;) {
      skipWs();
      const c = peek();
      if (c === '+' || c === '-') { eat(); const r = parseTerm(); v = c === '+' ? v + r : v - r; }
      else break;
    }
    return v;
  }
  function parseTerm() {
    let v = parseFactor();
    for (;;) {
      skipWs();
      const c = peek();
      if (c === '*' || c === '/') { eat(); const r = parseFactor(); v = c === '*' ? v * r : v / r; }
      else break;
    }
    return v;
  }
  function parseFactor() {
    skipWs();
    const c = peek();
    if (c === '+' || c === '-') { eat(); const v = parseFactor(); return c === '-' ? -v : v; }
    if (c === '(') { eat(); const v = parseExpr(); skipWs(); if (eat() !== ')') throw new Error('missing )'); return v; }
    let num = '';
    while (i < s.length && /[0-9.]/.test(s[i])) num += eat();
    if (!num) throw new Error('expected number at ' + i);
    return parseFloat(num);
  }
  const v = parseExpr();
  skipWs();
  if (i !== s.length) throw new Error('trailing input at ' + i);
  return v;
}
module.exports = { evalExpr };

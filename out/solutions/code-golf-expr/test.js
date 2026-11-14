const {evalExpr}=require('./solution.js');
const cases=[["1+2*3", 7], ["(1+2)*3", 9], ["10/4", 2.5], ["2.5*4", 10], ["-3+5", 2], ["10-2-3", 5], ["2*(3+4)/7", 2], ["3.5+2.5", 6], ["((2))", 2], ["8/2/2", 2], ["1+2+3+4", 10], ["0.1+0.2", 0.3]];
let fail=0;
for (const [expr, want] of cases) {
  const got=evalExpr(expr);
  if (Math.abs(got-want)>1e-9) { console.log('FAIL', expr, 'got', got, 'want', want); fail++; }
}
if (fail) process.exit(1);
console.log('PASS 12/12');

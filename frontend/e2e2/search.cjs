// generic regex search across backend python files
const fs = require('fs'), path = require('path');
const root = process.argv[2] || 'D:/平台/backend-main-fastapi';
const reStr = process.argv[3] || 'tasks';
const re = new RegExp(reStr, 'g');
function walk(d, acc) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f);
    const s = fs.statSync(p);
    if (s.isDirectory()) { if (/node_modules|__pycache__|\.venv|venv|\.git/.test(f)) continue; walk(p, acc); }
    else if (/\.(py|js|jsx|ts|tsx)$/.test(f)) acc.push(p);
  }
  return acc;
}
const files = walk(root, []);
let count = 0;
for (const f of files) {
  const s = fs.readFileSync(f, 'utf8');
  const lines = s.split('\n');
  for (let i = 0; i < lines.length; i++) {
    re.lastIndex = 0;
    if (re.test(lines[i])) { console.log(f.replace(/\\/g, '/') + ':' + (i + 1) + ': ' + lines[i].trim().slice(0, 160)); count++; if (count > 60) process.exit(0); }
  }
}
console.log('total hits:', count);

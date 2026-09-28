// Run: node tests/test_pose_display_hold.cjs
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=readFileSync(`${__dirname}/../backend/pose_lab.html`,'utf8');
const code=html.slice(html.indexOf('const actionHolds='),html.indexOf('function status('));
let now=0,pending;const banner={textContent:'',style:{}};
const ctx={performance:{now:()=>now},names:{POSE_DAMAGE_SUSPECTED:'破坏',POSE_CLIMBING_SUSPECTED:'攀爬'},$:()=>banner,
 setTimeout:(fn,ms)=>{pending={fn,at:now+ms};return 1},clearTimeout:()=>{pending=null}};
vm.createContext(ctx);vm.runInContext(code,ctx);
const damage='POSE_DAMAGE_SUSPECTED',climb='POSE_CLIMBING_SUSPECTED';
ctx.updateActionWarnings([damage,climb]);
now=5000;ctx.updateActionWarnings([damage,climb]);
assert.match(banner.textContent,/破坏.*攀爬/);assert.equal(pending,null);
now=6000;ctx.updateActionWarnings([climb]);
assert.match(banner.textContent,/破坏（结束后保留）.*攀爬/);assert.equal(pending.at,7000);
now=6999;ctx.updateActionWarnings([climb]);assert.match(banner.textContent,/破坏/);
now=7000;pending.fn();assert.doesNotMatch(banner.textContent,/破坏/);assert.match(banner.textContent,/攀爬/);
now=8000;ctx.updateActionWarnings([]);assert.equal(pending.at,9000);
now=8500;ctx.updateActionWarnings([climb]);assert.equal(pending,null);
now=10000;ctx.updateActionWarnings([]);assert.equal(pending.at,11000);
now=11000;pending.fn();assert.match(banner.textContent,/当前无/);
console.log('Display holds: active duration, exact 1s tail, independent actions, resumption passed');

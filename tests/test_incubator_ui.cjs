const {test}=require('node:test');
const assert=require('node:assert/strict');
require('../ui/static_processing/incubator.js');
const {parse,statistics}=globalThis.QCLIncubator;
const header='time_s,temperature_C,heater,waterLevel';
test('timestamped CRLF recording preserves samples and actuator pulses',()=>{
  const d=parse(`[2026-11-26 19:03:27] ${header}\r\n[2026-11-26 19:03:27] 0,23.42,0,523\r\n[2026-11-26 19:03:28] 1,24,1,520\r\n[2026-11-26 19:03:29] 2,25,0,519`);
  assert.equal(d.rows.length,3);assert.deepEqual(d.rows.map(r=>r.heater),[0,1,0]);assert.equal(d.fields.length,3);assert.equal(d.skipped,0);
});
test('invalid and diagnostic lines are counted, never converted to zero',()=>{
  const d=parse(`booting\n${header}\n0,20,0,500\n1,,1,510\n2,NaN,0,500\n3,24,2,500\n4,24,1,510\npartial`);
  assert.equal(d.rows.length,2);assert.equal(d.skipped,5);
});
test('resets, duplicate times, incompatible headers and unrecognized files fail clearly',()=>{
  for(const end of ['0,21,1,501','-1,21,1,501\n0,21,1,501'])assert.throws(()=>parse(`${header}\n0,20,0,500\n${end}`),/repeats|backwards/);
  assert.throws(()=>parse(`${header}\n0,20,0,500\ntime_s,heater`),/different headers/);
  assert.throws(()=>parse('hello'),/No valid/);
  assert.throws(()=>parse('time_s,other\n0,4'),/No recognized/);
});
test('statistics exclude warmup, include endpoints and use population SD',()=>{
  const rows=[{time_s:0,v:0},{time_s:1,v:2},{time_s:2,v:4}];
  assert.deepEqual(statistics(rows,'v',1,2),{n:2,mean:3,sd:1,min:2,max:4});
  assert.equal(statistics(rows,'v',3,4),null);
  assert.equal(statistics(rows,'v',2,2).sd,0);
});

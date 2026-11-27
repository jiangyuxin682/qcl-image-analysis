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

test('display ranges reject invalid or out-of-recording inputs',()=>{
  const {displayRange}=QCLIncubator;
  assert.deepEqual(displayRange('0.25','0.5',0,1),[.25,.5]);
  for(const [start,end] of [['',1],[0,''],[.5,.4],[.5,.5],[-1,.5],[0,2],['NaN',1]])assert.throws(()=>displayRange(start,end,0,1));
  assert.deepEqual(displayRange(1,1,1,1),[1,1]);
});
test('zoom boundaries interpolate continuous signals without including offscreen extrema',()=>{
  const rows=[{time_s:0,v:100},{time_s:10,v:0},{time_s:20,v:10},{time_s:30,v:100}];
  assert.deepEqual(QCLIncubator.windowPoints(rows,'v',12,18),[{time_s:12,value:2},{time_s:18,value:8}]);
  assert.deepEqual(QCLIncubator.windowPoints(rows,'v',10,20),[{time_s:10,value:0},{time_s:20,value:10}]);
});
test('digital zoom retains entry state, short pulses and exact transition boundaries',()=>{
  const rows=[{time_s:0,v:0},{time_s:10,v:1},{time_s:11,v:0},{time_s:20,v:1}];
  assert.deepEqual(QCLIncubator.windowPoints(rows,'v',5,15,true),[
    {time_s:5,value:0},{time_s:10,value:1},{time_s:11,value:0},{time_s:15,value:0}
  ]);
  assert.deepEqual(QCLIncubator.windowPoints(rows,'v',10.2,10.8,true),[{time_s:10.2,value:1},{time_s:10.8,value:1}]);
  assert.equal(QCLIncubator.windowPoints(rows,'v',10,20,true).at(-1).value,1);
});
test('full-range hour conversion preserves a singleton recording',()=>{
  const rows=[{time_s:123,v:37}];
  assert.deepEqual(QCLIncubator.windowPoints(rows,'v',123+1e-12,123-1e-12),[{time_s:123,value:37}]);
});

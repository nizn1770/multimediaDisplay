// Rotation: slideshow -> week -> slideshow -> month ...
const S={photos:[],idx:0,interval:15,events:[],byDay:{},today:null,tz:null,phase:0};
const WX={0:'☀',1:'🌤',2:'⛅',3:'☁',45:'🌫',48:'🌫',51:'🌦',61:'🌧',63:'🌧',65:'🌧',71:'🌨',73:'🌨',75:'❄',80:'🌦',95:'⛈'};
const wx=c=>WX[c]||WX[Math.floor(c/10)*10]||'';
const ago=t=>{if(!t)return 'never';const m=Math.round((Date.now()/1000-t)/60);return m<1?'just now':m<60?m+' min ago':Math.round(m/60)+' h ago'};
const $=id=>document.getElementById(id);
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()}
async function loadPhotos(){try{const d=await j('/api/photos');S.photos=d.photos;S.ver=d.versions||{};S.interval=d.interval;S.psync=d.last_sync;S.perr=d.error;showSync()}catch(e){}}
async function loadEvents(){try{const d=await j('/api/events');S.events=d.events;S.byDay=d.by_day;S.today=d.today;S.csync=d.last_fetch;S.cerr=d.error;showSync();renderAgenda(d.agenda||[]);$('err').textContent=[d.error&&'Calendar offline (cached)',S.perr&&'Photos offline (cached)'].filter(Boolean).join(' · ')}catch(e){$('err').textContent='Server unreachable'}}
async function loadStatus(){try{const d=await j('/api/status');handleControl(d.control);S.tz=d.timezone;$('night').classList.toggle('hidden',!d.night);
 const w=d.weather;$('weather').textContent=w?`${wx(w.code)} ${Math.round(w.temp)}° ${w.location||''}`:'';
 $('forecast').innerHTML=w&&w.forecast?w.forecast.map(f=>`<span>${D(f.date).toLocaleDateString([], {weekday:'short',timeZone:'UTC'})} ${wx(f.code)} ${Math.round(f.high)}°/${Math.round(f.low)}°</span>`).join(''):'';}catch(e){}}
function tick(){const n=new Date(),o={timeZone:S.tz||undefined};
 $('clock').textContent=n.toLocaleTimeString([], {...o,hour:'numeric',minute:'2-digit'});
 $('date').textContent=n.toLocaleDateString([], {...o,weekday:'long',month:'long',day:'numeric'});}
let cur='imgA';
function nextPhoto(){if(!S.photos.length)return;S.idx=(S.idx+1)%S.photos.length;
 const nxt=cur==='imgA'?'imgB':'imgA',img=$(nxt);
 img.onload=()=>{$(nxt).classList.add('show');$(cur).classList.remove('show');cur=nxt};
 img.onerror=()=>{};const n=S.photos[S.idx];img.src='/photos/'+encodeURIComponent(n)+'?v='+(S.ver[n]||'');}
function iso(d){return d.toISOString().slice(0,10)}
function D(s){const [y,m,dd]=s.split('-').map(Number);return new Date(Date.UTC(y,m-1,dd))}
function render(mode){const t=D(S.today||iso(new Date()));let start,n,cols=7;
 if(mode==='week'){start=new Date(t);start.setUTCDate(t.getUTCDate()-t.getUTCDay());n=7;$('calTitle').textContent='This Week'}
 else{const f=new Date(Date.UTC(t.getUTCFullYear(),t.getUTCMonth(),1));start=new Date(f);start.setUTCDate(1-f.getUTCDay());n=42;
  $('calTitle').textContent=f.toLocaleDateString([], {month:'long',year:'numeric',timeZone:'UTC'})}
 const byId=Object.fromEntries(S.events.map(e=>[e.id+e.calendar,e]));const g=$('grid');g.innerHTML='';
 g.style.gridTemplateColumns=`repeat(${cols},1fr)`;
 for(let i=0;i<n;i++){const d=new Date(start);d.setUTCDate(start.getUTCDate()+i);const k=iso(d);
  const c=document.createElement('div');c.className='day'+(k===S.today?' today':'')+(mode==='month'&&d.getUTCMonth()!==t.getUTCMonth()?' other':'');
  c.innerHTML=`<b>${d.toLocaleDateString([], {weekday:'short',day:'numeric',timeZone:'UTC'})}</b>`;
  for(const e of S.events.filter(e=>(S.byDay[k]||[]).includes(e.id))){const x=document.createElement('div');
   x.className='ev'+(e.all_day?' allday':'');if(e.color)x.style.background=e.color;
   x.textContent=(e.all_day?'':new Date(e.start).toLocaleTimeString([], {hour:'numeric',minute:'2-digit',timeZone:S.tz||undefined})+' ')+e.title;c.appendChild(x)}
  g.appendChild(c)}}
let photoCount=0,timer=null,paused=false,lastSeq=null;
function sched(fn,ms){clearTimeout(timer);if(!paused)timer=setTimeout(fn,ms)}
function showCal(v){render(v);$('calendar').classList.remove('hidden')}
function step(){ // ~8 photos then a calendar view for 30s
 if(photoCount<8){$('calendar').classList.add('hidden');nextPhoto();photoCount++;sched(step,S.interval*1000)}
 else{photoCount=0;S.phase^=1;showCal(S.phase?'week':'month');sched(step,30000)}}
function handleControl(c){if(!c)return;if(lastSeq===null){lastSeq=c.seq;paused=c.paused;return}
 if(c.seq===lastSeq)return;lastSeq=c.seq;paused=c.paused;const a=c.action;
 if(a==='pause'){clearTimeout(timer);return}
 if(a==='next'||a==='resume'||a==='photos'){photoCount=Math.min(photoCount,7);$('calendar').classList.add('hidden');nextPhoto();photoCount++;sched(step,S.interval*1000)}
 else if(a==='prev'){S.idx=(S.idx-2+S.photos.length*2)%Math.max(S.photos.length,1);$('calendar').classList.add('hidden');nextPhoto();sched(step,S.interval*1000)}
 else if(a==='week'||a==='month'){showCal(a);photoCount=0;sched(step,60000)}}
(async()=>{await Promise.all([loadPhotos(),loadEvents(),loadStatus()]);tick();setInterval(tick,1000);
 setInterval(loadPhotos,60000);setInterval(loadEvents,120000);setInterval(loadStatus,5000);
 setTimeout(()=>location.reload(),6*3600*1000); // memory hygiene for long runs
 S.idx=-1;step();})();

function showSync(){$('sync').textContent=`Photos synced ${ago(S.psync)} · Calendar ${ago(S.csync)}`}
setInterval(showSync,30000);
function renderAgenda(a){const el=$('agenda');el.innerHTML='';for(const e of a){const x=document.createElement('div');
 if(e.color)x.style.borderColor=e.color;
 const when=e.all_day?D(e.start).toLocaleDateString([], {weekday:'short',timeZone:'UTC'})+' all day'
  :new Date(e.start).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit',timeZone:S.tz||undefined});
 x.textContent=when+' — '+e.title;el.appendChild(x)}}

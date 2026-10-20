// Rotation: slideshow -> week -> slideshow -> month ...
const S={photos:[],idx:0,interval:15,events:[],byDay:{},today:null,tz:null,phase:0};
const $=id=>document.getElementById(id);
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()}
async function loadPhotos(){try{const d=await j('/api/photos');S.photos=d.photos;S.interval=d.interval;}catch(e){}}
async function loadEvents(){try{const d=await j('/api/events');S.events=d.events;S.byDay=d.by_day;S.today=d.today;$('err').textContent=d.error?'Calendar offline (cached)':''}catch(e){$('err').textContent='Server unreachable'}}
async function loadStatus(){try{const d=await j('/api/status');S.tz=d.timezone;$('night').classList.toggle('hidden',!d.night);
 const w=d.weather;$('weather').textContent=w?`${Math.round(w.temp)}° (H ${Math.round(w.high)} / L ${Math.round(w.low)})`:'';}catch(e){}}
function tick(){const n=new Date(),o={timeZone:S.tz||undefined};
 $('clock').textContent=n.toLocaleTimeString([], {...o,hour:'numeric',minute:'2-digit'});
 $('date').textContent=n.toLocaleDateString([], {...o,weekday:'long',month:'long',day:'numeric'});}
let cur='imgA';
function nextPhoto(){if(!S.photos.length)return;S.idx=(S.idx+1)%S.photos.length;
 const nxt=cur==='imgA'?'imgB':'imgA',img=$(nxt);
 img.onload=()=>{$(nxt).classList.add('show');$(cur).classList.remove('show');cur=nxt};
 img.onerror=()=>{};img.src='/photos/'+encodeURIComponent(S.photos[S.idx]);}
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
   x.className='ev'+(e.all_day?' allday':'');
   x.textContent=(e.all_day?'':new Date(e.start).toLocaleTimeString([], {hour:'numeric',minute:'2-digit',timeZone:S.tz||undefined})+' ')+e.title;c.appendChild(x)}
  g.appendChild(c)}}
let photoCount=0;
function step(){ // ~8 photos then a calendar view for 30s
 if(photoCount<8){$('calendar').classList.add('hidden');nextPhoto();photoCount++;setTimeout(step,S.interval*1000)}
 else{photoCount=0;S.phase^=1;render(S.phase?'week':'month');$('calendar').classList.remove('hidden');setTimeout(step,30000)}}
(async()=>{await Promise.all([loadPhotos(),loadEvents(),loadStatus()]);tick();setInterval(tick,1000);
 setInterval(loadPhotos,60000);setInterval(loadEvents,120000);setInterval(loadStatus,60000);
 setTimeout(()=>location.reload(),6*3600*1000); // memory hygiene for long runs
 S.idx=-1;step();})();

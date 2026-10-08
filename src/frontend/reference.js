
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const rng=s=>()=>(s=s*16807%2147483647)/2147483647;
const fmt=n=>Math.round(n).toLocaleString('en-IN'),f2=n=>n.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const sg=n=>(n<0?'−':'+')+f2(Math.abs(n)),cl=n=>n<0?'dn':'up',inr=n=>(n<0?'−':'')+'₹'+fmt(Math.abs(n));
const IST={timeZone:'Asia/Kolkata'},dt=a=>new Date(Date.now()-a*6e4);
const hh=a=>dt(a).toLocaleTimeString('en-IN',{...IST,hour:'2-digit',minute:'2-digit',hour12:false});
const dts=a=>dt(a).toLocaleDateString('en-IN',{...IST,day:'numeric',month:'short'})+' '+hh(a);
const dl=k=>{const d=new Date();d.setDate(d.getDate()-k);return d.toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'2-digit'})};
const rel=a=>a<1?'Just now':a<60?a+' min ago':Math.round(a/60)+' h ago';
const S={TCS:['Tata Consultancy Services',3912.4,-.8],RELIANCE:['Reliance Industries',2874.1,1.2],HDFCBANK:['HDFC Bank',1688.9,.4],INFY:['Infosys',1521.3,-1.6],ICICIBANK:['ICICI Bank',1249.6,.9],SBIN:['State Bank of India',812.7,2.1],ITC:['ITC',468.2,-.3]};
const IDX=[['NIFTY 50',24812.4,.42],['SENSEX',81230.7,.38],['BANK NIFTY',53410.2,-.12]];
const NEWS=[
{id:1,a:12,src:'Sample Wire',cat:'Earnings',sent:-.62,imp:'High',h:'IT majors trim FY27 revenue outlook as client budgets tighten',s:'Two large services firms flagged slower deal conversion from North American clients.',tk:[['INFY',.91,1],['TCS',.84,1]]},
{id:2,a:47,src:'Market Desk',cat:'Policy',sent:.58,imp:'High',h:'Regulator eases risk-weight norms on retail loans; lenders in focus',s:'Lower capital requirements could free up lending room at large private and state banks.',tk:[['HDFCBANK',.88,1],['ICICIBANK',.86,1],['SBIN',.74,0]]},
{id:3,a:130,src:'Sample Wire',cat:'Corporate',sent:.31,imp:'Medium',h:'Refiner unveils phased green-hydrogen unit, capex split over three years',s:'Management said the first phase will be funded from internal accruals.',tk:[['RELIANCE',.93,1]]},
{id:4,a:205,src:'Market Desk',cat:'Corporate',sent:null,imp:null,h:'Consumer major reports steady monthly volumes in trading update',s:'',tk:[['ITC',.8,1]]},
{id:5,a:340,src:'Exchange Filings',cat:'Earnings',sent:.66,imp:'High',h:'State lender’s provisions come in below street estimates for the quarter',s:'Net interest margin held steady while slippages eased.',tk:[['SBIN',.95,1],['HDFCBANK',.41,0]]},
{id:6,a:520,src:'Brokerage Note',cat:'Analyst',sent:.12,imp:'Low',h:'Brokerages split on private banks after policy move',s:'Some raise targets while others see limited upside at current valuations.',tk:[['ICICIBANK',.77,1],['HDFCBANK',.7,1]]}];
const OLD=[
{id:11,a:8*1440,src:'Exchange Filings',cat:'Earnings',sent:-.48,imp:'High',h:'Private lender flags higher slippages; shares slide in early trade',s:'Stress in unsecured loans drove the rise.',tk:[['ICICIBANK',.9,1],['HDFCBANK',.55,0]]},
{id:12,a:41*1440,src:'Market Desk',cat:'Policy',sent:.52,imp:'Medium',h:'Government raises capex target; infrastructure-linked names in focus',s:'Public-sector lenders may see higher credit demand.',tk:[['SBIN',.6,0],['RELIANCE',.5,0]]},
{id:13,a:120*1440,src:'Sample Wire',cat:'Corporate',sent:.37,imp:'Medium',h:'Conglomerate completes retail unit stake sale at a premium',s:'Proceeds are earmarked for new energy projects.',tk:[['RELIANCE',.92,1]]}];
const EV=id=>NEWS.concat(OLD).find(n=>n.id==id);
const N=400,PN={N:'Normal Rebalancing',W:'News + Normal Rebalancing'};
const H={N:{cash:0,pos:{TCS:[40,.96],RELIANCE:[60,1.04],HDFCBANK:[100,.93],INFY:[90,1.07],ICICIBANK:[120,.9],SBIN:[150,.86],ITC:[200,1.02]}},W:{cash:0,pos:{TCS:[28,.96],RELIANCE:[60,1.02],HDFCBANK:[115,.92],INFY:[62,1.05],ICICIBANK:[135,.89],SBIN:[180,.84],ITC:[200,1.02]}}};
const mkS=(seed,d,v,x2)=>{const r=rng(seed),r2=rng(seed+99);let x=1;return Array.from({length:N},()=>x*=1+d+(r()-.5)*v+(x2?(r2()-.5)*x2:0))};
const RAW={N:mkS(7,.00036,.016,0),W:mkS(7,.0005,.016,.003)};
const posV=k=>Object.entries(H[k].pos).reduce((a,[t,[s]])=>a+s*S[t][1],0),tot=k=>H[k].cash+posV(k);
const E0=k=>1e6*RAW[k][N-1]/RAW[k][0];
['N','W'].forEach(k=>H[k].cash=Math.max(E0(k)-posV(k),20000));
const ser=k=>{const a=RAW[k],f=tot(k)/Math.max(E0(k),1);return a.map(v=>v/a[0]*1e6*f)};
const day=k=>Object.entries(H[k].pos).reduce((a,[t,[s]])=>{const p=S[t][1],c=S[t][2];return a+s*(p-p/(1+c/100))},0);
const hold=k=>{const T=tot(k);return Object.entries(H[k].pos).map(([t,[sh,f]])=>{const p=S[t][1],mv=sh*p,ac=p*f;return{t,p,c:S[t][2],sh,w:mv/T*100,mv,ac,pl:mv-sh*ac}})};
const hs=t=>[...t].reduce((a,c)=>a*31+c.charCodeAt(0),7)%2147483647;
const sp=(t,n=90)=>{const r=rng(hs(t)+1);let x=1;const a=Array.from({length:n},()=>x*=1+(r()-.48)*.022);return a.map(v=>v/a[n-1]*S[t][1])};
const lab=n=>Array.from({length:n},(_,i)=>dl(n-1-i));
const MK=[{o:21,r:1},{o:84,r:1},{o:168,r:1},{o:252,r:1},{o:336,r:1},{o:8,id:11},{o:41,id:12},{o:120,id:13}];
const O=[
{id:'PT-1006',pf:'W',t:'INFY',side:'Sell',q:30,px:1545.2,why:'News signal',ev:1,td:'10:02',te:'10:03',d:'6 Oct',st:'Filled'},
{id:'PT-1005',pf:'W',t:'SBIN',side:'Buy',q:25,px:806.4,why:'News signal',ev:5,td:'15:41',te:null,d:'5 Oct',st:'Pending'},
{id:'PT-1004',pf:'W',t:'HDFCBANK',side:'Buy',q:15,px:1671,why:'News signal',ev:2,td:'09:48',te:'09:49',d:'5 Oct',st:'Filled'},
{id:'PT-1003',pf:'N',t:'TCS',side:'Buy',q:5,px:3880,why:'Scheduled rebalance',ev:null,td:'09:20',te:'09:21',d:'2 Oct',st:'Filled'},
{id:'PT-1002',pf:'N',t:'ITC',side:'Sell',q:12,px:471,why:'Manual',ev:null,td:'11:10',te:null,d:'30 Sep',st:'Failed'},
{id:'PT-1001',pf:'W',t:'ICICIBANK',side:'Sell',q:20,px:1262,why:'News signal',ev:11,td:'10:15',te:'10:16',d:'28 Sep',st:'Filled'}];
const LG=[
{id:1,dec:'Reduce INFY and TCS',st:'Filled',oid:'PT-1006',w:['INFY',9.4,6.1]},
{id:2,dec:'Increase HDFCBANK and ICICIBANK',st:'Filled',oid:'PT-1004',w:['HDFCBANK',15.1,16.9]},
{id:3,dec:'No action: below sentiment threshold',st:'No order'},
{id:4,dec:'Not decided: analysis pending',st:'—'},
{id:5,dec:'Increase SBIN',st:'Pending',oid:'PT-1005',w:['SBIN',14.1,15.8]},
{id:11,dec:'Reduce ICICIBANK',st:'Filled',oid:'PT-1001',w:['ICICIBANK',12.1,9.8]},
{id:12,dec:'No action: position limit reached',st:'No order'},
{id:13,dec:'Increase RELIANCE',st:'Filled',oid:null,w:['RELIANCE',15.2,17.0]}];
const st={q:'',cat:'',sen:'',src:'',age:'',range:252,met:'v',pf:'W',tab:'Holdings',sort:['mv',-1],lq:'',ls:'',op:'',os:'',oq:''};
const badge=s=>`<span class="b ${{Filled:'ok',Failed:'bad',Pending:'pe'}[s]||''}">${s}</span>`;
const cls=(t,w)=>`<button class="chip" data-a="tk" data-v="${t}">${mono(t)}<b>${t}</b><span data-p="${t}">${f2(S[t][1])}</span><span data-c="${t}" class="${cl(S[t][2])}">${sg(S[t][2])}%</span></button>`;
const sentB=n=>n.sent==null?'<span>Analysis pending</span>':`<span><span class="sb"><i style="left:${n.sent>=0?50:50+n.sent*50}%;width:${Math.abs(n.sent)*50}%;background:${n.sent>=0?'var(--grn)':'var(--red)'}"></i></span>Sentiment <b>${sg(n.sent)}</b></span>`;
const sel=(k,l,o)=>`<select data-f="${k}" aria-label="${l}"><option value="">${l}: all</option>${o.map(x=>`<option value="${x[0]}"${st[k]==x[0]?' selected':''}>${x[1]}</option>`).join('')}</select>`;
const pg=()=>location.hash.slice(2)||'news';
/* chart */
let CH;
function chart(L,lb,mk,fy,h,ft){const M=innerWidth<=720,W=M?440:900;if(M)h=Math.round(h*.9);const P={l:58,r:14,t:12,b:30},n=L[0].y.length,all=L.flatMap(l=>l.y);let lo=Math.min(...all),hi=Math.max(...all);const pd=(hi-lo)*.1||1;lo-=pd;hi+=pd;
const X=i=>P.l+i*(W-P.l-P.r)/(n-1),Y=v=>P.t+(hi-v)*(h-P.t-P.b)/(hi-lo);let g='';
for(let k=0;k<5;k++){const v=lo+(hi-lo)*k/4;g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${P.l-8}" y="${Y(v)+4}" text-anchor="end">${fy(v)}</text>`}
[0,1/3,2/3,1].forEach((k,j)=>{const i=Math.round(k*(n-1));g+=`<text x="${X(i)}" y="${h-8}" text-anchor="${j?j==3?'end':'middle':'start'}">${lb[i]}</text>`});
g+=L.map(l=>`<polyline fill="none" stroke="${l.c}" stroke-width="2.4" stroke-linejoin="round" points="${l.y.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ')}"/>`).join('');
const T=L[L.length-1].y;g+=`<line id="cx" y1="${P.t}" y2="${h-P.b}" stroke="var(--mut)" stroke-dasharray="3 3" visibility="hidden"/>`;
g+=mk.map(m=>`<circle cx="${X(m.i)}" cy="${Y(T[m.i])}" r="${M?9:6.5}" fill="${m.c}" stroke="var(--bg)" stroke-width="2" tabindex="0" role="button" aria-label="${m.l}" data-a="${m.a}" data-v="${m.v}"><title>${m.l}</title></circle>`).join('');
if(ft)CH={L,lb,P,W,n,X,ft};
return `<div class="chw"${ft?' data-h="1"':''}><svg viewBox="0 0 ${W} ${h}" role="img" aria-label="Chart">${g}</svg><div id="tt" class="tt" hidden></div></div>`}
/* drawers */
const dh=t=>`<div class="dh"><span>${t}</span><button data-a="x">${ic('close')}Close</button></div>`;
const dr=h=>{$('#dr').innerHTML=h;$('#dr').classList.add('open');$('#scrim').classList.add('on');$('#dr').scrollTop=0;$('#dr button')?.focus()};
const close=()=>{$('#dr').classList.remove('open');$('#scrim').classList.remove('on')};
const trow=n=>n.tk.map(([t,r,d])=>`<tr><td><button class="lnk" data-a="tk" data-v="${t}">${t}</button></td><td>${d?'Direct mention':'Correlation-based'}</td><td class="n">${r.toFixed(2)}</td><td class="n"><span data-p="${t}">${f2(S[t][1])}</span></td><td class="n"><span data-c="${t}" class="${cl(S[t][2])}">${sg(S[t][2])}%</span></td></tr>`).join('');
function evH(id){const n=EV(id),l=LG.find(x=>x.id==id);
return `${dh('Event brief')}<h2 style="margin-top:12px;font-size:26px;line-height:1.15">${n.h}</h2><p class="m">${dts(n.a)} IST, ${n.src}</p><p>${n.s||'Summary not available yet.'} <span class="m">Article link is not included in sample data.</span></p>
<dl class="kv"><div><dt>Category</dt><dd>${n.cat}</dd></div><div><dt>Sentiment</dt><dd>${n.sent==null?'—':sg(n.sent)}</dd></div><div><dt>Impact</dt><dd>${n.imp||'—'}</dd></div><div><dt>Analysis</dt><dd>${n.sent==null?'Analysis pending':'Analyzed'}</dd></div></dl>
<h3>Affected stocks</h3><div class="tw"><table><thead><tr><th>Stock</th><th>Link</th><th class="n">Relevance</th><th class="n">Price</th><th class="n">Day</th></tr></thead><tbody>${trow(n)}</tbody></table></div>
${n.tk.slice(0,2).map(([t])=>{const a=sp(t);return `<h4>${t} around the event</h4>`+chart([{c:'var(--ink)',y:a}],lab(90),[{i:60,c:'var(--red)',a:'tk',v:t,l:'Event time'}],v=>fmt(v),150)+`<p class="m">Observed ${sg((a[62]/a[60]-1)*100)}% in the two sessions after the event. This is movement after the news, not proof that the news caused it.</p>`}).join('')}
<h3>Portfolio actions</h3>${l?`<p>${l.dec}. ${l.oid?'Order '+l.oid+' ('+l.st+').':'No linked order record.'}</p>`:'<p class="m">No portfolio action recorded.</p>'}`}
function stH(t){const k=st.pf,p=hold(k).find(x=>x.t==t),a=sp(t),mk=[];
NEWS.concat(OLD).filter(n=>n.tk.some(x=>x[0]==t)).forEach(n=>{const i=89-Math.floor(n.a/1440);if(i>=0)mk.push({i,c:'var(--red)',a:'ev',v:n.id,l:'News: '+n.h})});
[21,84].forEach(o=>{if(89-o>=0)mk.push({i:89-o,c:'var(--ink)',a:'rb',v:o,l:'Rebalance'})});
const tx=O.filter(o=>o.pf==k&&o.t==t&&o.st=='Filled').map(o=>({d:o.d,side:o.side,q:o.q,px:o.px,why:o.why,ev:o.ev}));const r=rng(hs(t)+(k=='W'?5:1)),ne=NEWS.find(n=>n.tk.some(x=>x[0]==t));
[8,35,66].forEach((o,i)=>{const side=r()>.35?'Buy':'Sell';tx.push({d:dl(o),side,q:Math.round(5+r()*25),px:S[t][1]*(.9+r()*.12),why:k=='W'&&i==0&&ne?'News signal':'Scheduled rebalance',ev:k=='W'&&i==0&&ne?ne.id:null})});
return `${dh('Stock position')}<h2 style="margin-top:12px;font-size:30px;line-height:1.1">${t}<span class="m" style="font-size:15px;font-weight:500"> ${S[t][0]}</span></h2>
<div class="big" style="font-size:2.6rem">₹<span data-p="${t}">${f2(S[t][1])}</span> <span data-c="${t}" class="${cl(S[t][2])}" style="font-size:1.1rem">${sg(S[t][2])}%</span></div>
<p class="m">Source: yfinance, may be delayed and is not exchange-grade. Updated ${hh(0)} IST.</p>
<div class="seg" role="group" aria-label="Portfolio">${['N','W'].map(x=>`<button class="${k==x?'on'+(x=='W'?' r':''):''}" data-a="pfd" data-v="${x}:${t}">${PN[x]}</button>`).join('')}</div>
<dl class="kv"><div><dt>Shares</dt><dd>${p.sh}</dd></div><div><dt>Weight</dt><dd>${p.w.toFixed(1)}%</dd></div><div><dt>Average cost</dt><dd>₹${f2(p.ac)}</dd></div><div><dt>Market value</dt><dd>${inr(p.mv)}</dd></div><div><dt>Unrealized P&amp;L</dt><dd class="${cl(p.pl)}">${inr(p.pl)}</dd></div></dl>
${chart([{c:'var(--ink)',y:a}],lab(90),mk,v=>fmt(v),200)}<p class="m">Red dots are news events, black dots are rebalances.</p>
<h3>Related news</h3>${NEWS.filter(n=>n.tk.some(x=>x[0]==t)).map(n=>`<p style="margin:6px 0"><button class="lnk" data-a="ev" data-v="${n.id}">${n.h}</button> <span class="m">${rel(n.a)}</span></p>`).join('')||'<p class="m">No recent stories.</p>'}
<h3>Purchase and sale history</h3><div class="tw"><table><thead><tr><th>Date</th><th>Side</th><th class="n">Qty</th><th class="n">Execution price</th><th class="n">Fees</th><th>Reason</th></tr></thead><tbody>${tx.map(x=>`<tr><td>${x.d}</td><td>${x.side}</td><td class="n">${x.q}</td><td class="n">${f2(x.px)}</td><td class="n">${f2(x.q*x.px*.001)}</td><td>${x.ev?`<button class="lnk" data-a="ev" data-v="${x.ev}">${x.why}</button>`:x.why}</td></tr>`).join('')}</tbody></table></div>`}
const rbH=o=>`${dh('Rebalance')}<h2 style="margin-top:12px">Scheduled rebalance, ${dl(o)}</h2><p>The 21-trading-day rule moved positions back toward target weights in both portfolios. Order-level detail for this sample date is not recorded.</p>`;
function ledH(id){const n=EV(id),l=LG.find(x=>x.id==id),a=sp(n.tk[0][0]),ok=[['News event',`${dts(n.a)} IST, ${n.src}`,1],['Model signal',n.sent==null?'Not recorded. Analysis pending.':`Sentiment ${sg(n.sent)}, impact ${n.imp}`,n.sent!=null],['Affected ticker',n.tk.map(x=>x[0]+' ('+x[1].toFixed(2)+')').join(', '),1],['Portfolio decision',l.dec+' (News + Normal)',n.sent!=null],['Rebalance or order',l.oid?'Order '+l.oid:'Not recorded',!!l.oid],['Execution',l.oid?l.st:'Not recorded',l.st=='Filled']];
return `${dh('Event ledger')}<h2 style="margin-top:12px;font-size:24px;line-height:1.15">${n.h}</h2><ol class="ch">${ok.map(x=>`<li class="${x[2]?'':'nr'}"><b>${x[0]}</b> <span class="b">${x[2]?'Verified':'Not recorded'}</span><br>${x[1]}</li>`).join('')}</ol>
${l.w?`<h3>Weight change</h3><p>${l.w[0]}: ${l.w[1]}% before, ${l.w[2]}% after.</p>`:''}
<h3>Performance after the event</h3><p>${n.tk[0][0]} moved ${sg((a[62]/a[60]-1)*100)}% in the two sessions after the event. Observed movement only.</p>
<p><b>Event-level P&amp;L attribution: unavailable.</b> <span class="m">It needs event-to-order-to-P&amp;L records the backend does not store yet.</span></p><p><button class="lnk" data-a="ev" data-v="${id}">Open news brief</button></p>`}
/* pages */
const flt=()=>NEWS.filter(n=>(!st.q||(n.h+n.tk.map(x=>x[0]).join(' ')).toLowerCase().includes(st.q.toLowerCase()))&&(!st.cat||n.cat==st.cat)&&(!st.sen||n.sent!=null&&(st.sen=='pos'?n.sent>.15:st.sen=='neg'?n.sent<-.15:Math.abs(n.sent)<=.15))&&(!st.src||n.src==st.src)&&(!st.age||n.a<=+st.age));
const row=n=>`<article class="row ${n.imp=='High'?'hi':''} ${n.fresh?'fresh':''}"><div class="meta"><time>${hh(n.a)} IST</time><span>${rel(n.a)}</span><span>${n.src}</span>${n.fresh||n.a<=15?'<mark>NEW</mark>':''}<span class="cat">${ic(CI[n.cat])}${n.cat}</span></div><h3><button class="hl" data-a="ev" data-v="${n.id}">${n.h}</button></h3>${n.s?`<p>${n.s}</p>`:''}<div class="chips">${n.tk.map(x=>cls(x[0])).join('')}</div><div class="ind">${sentB(n)}<span>Impact <b>${n.imp||'—'}</b></span></div></article>`;
const feed=()=>{const l=flt();return l.length?l.map(row).join(''):'<p class="empty">No stories match these filters. <button class="lnk" data-a="clr">Clear filters</button></p>'};
const side=()=>{const m={},c={};NEWS.forEach(n=>n.tk.forEach(([t,r])=>{m[t]=(m[t]||0)+r;c[t]=(c[t]||0)+1}));return `<h2>Most affected stocks</h2>${Object.entries(m).sort((a,b)=>b[1]-a[1]).slice(0,5).map(([t])=>`<button class="ar" data-a="tk" data-v="${t}"><span><b>${mono(t)}${t}</b><br><span class="m">${c[t]} ${c[t]>1?'stories':'story'} today</span></span>${spk(t,S[t][1],S[t][2])}<span class="n"><span data-p="${t}">${f2(S[t][1])}</span><br><span data-c="${t}" class="${cl(S[t][2])}">${sg(S[t][2])}%</span></span></button>`).join('')}`};
const News=()=>`<h1>Market Pulse</h1><p class="sub">Headlines that move your watchlist, with the stocks they touch and where prices stand.</p>
<div class="filters"><input data-f="q" placeholder="Search headline or ticker" value="${st.q}" aria-label="Search headlines or tickers">${sel('cat','Category',['Earnings','Policy','Corporate','Analyst','Macro'].map(x=>[x,x]))}${sel('sen','Sentiment',[['pos','Positive'],['neu','Neutral'],['neg','Negative']])}${sel('src','Source',['Sample Wire','Market Desk','Exchange Filings','Brokerage Note'].map(x=>[x,x]))}${sel('age','Time',[[60,'Last hour'],[240,'Last 4 hours'],[1440,'Last 24 hours']])}</div>
<div class="cols"><div id="feed">${feed()}</div><aside class="side" id="side">${side()}</aside></div>`;
const tr=(y)=>{let pk=y[0];return y.map(v=>(pk=Math.max(pk,v),(v/pk-1)*100))};
const Y_=()=>[['N','var(--ink)'],['W','var(--red)']].map(([k,c])=>{const y=ser(k).slice(-st.range);return{k,c,y:st.met=='v'?y:st.met=='r'?y.map(v=>(v/y[0]-1)*100):tr(y)}});
const sw=()=>`<div class="seg" role="group" aria-label="Strategy">${['N','W'].map(x=>`<button class="${st.pf==x?'on'+(x=='W'?' r':''):''}" data-a="pf" data-v="${x}">${PN[x]}</button>`).join('')}</div>`;
const stats=k=>{const y=ser(k).slice(-st.range),r=y.slice(1).map((v,i)=>v/y[i]-1),m=r.reduce((a,b)=>a+b)/r.length,sd=Math.sqrt(r.reduce((a,b)=>a+(b-m)**2,0)/r.length);return{vol:sd*Math.sqrt(252)*100,sh:m/sd*Math.sqrt(252),dd:Math.min(...tr(y))}};
function tab(){const k=st.pf;
if(st.tab=='Holdings'){const T=tot(k);let rs=hold(k);const[sk,sd]=st.sort;rs.sort((a,b)=>(a[sk]>b[sk]?1:-1)*sd*(sk=='t'?-1:1));
const C=[['t','Stock'],['p','Price'],['c','Day change'],['sh','Shares'],['w','Weight'],['mv','Market value'],['ac','Average cost'],['pl','Unrealized P&L']];
return `<div class="bar">${sw()}<span class="m">Cash ${inr(H[k].cash)}</span></div><div class="al" role="img" aria-label="Allocation">${hold(k).map((p,i)=>`<i title="${p.t} ${p.w.toFixed(1)}%" style="width:${p.w}%;background:${i%2?'var(--ink)':'var(--mut)'};border-right:2px solid var(--bg)"></i>`).join('')}</div><div class="lg" style="margin-bottom:12px">${hold(k).map(p=>`<span>${p.t} ${p.w.toFixed(1)}%</span>`).join('')}</div>
<div class="tw hd"><table><thead><tr>${C.map(c=>`<th class="${c[0]=='t'?'':'n'}"><button data-a="sort" data-v="${c[0]}">${c[1]}${sk==c[0]?(sd<0?' ▼':' ▲'):''}</button></th>`).join('')}</tr></thead><tbody>${rs.map(p=>`<tr data-a="tk" data-v="${p.t}" tabindex="0"><td><b>${p.t}</b> <span class="m">${S[p.t][0]}</span></td><td class="n">${f2(p.p)}</td><td class="n ${cl(p.c)}">${sg(p.c)}%</td><td class="n">${p.sh}</td><td class="n">${p.w.toFixed(1)}%</td><td class="n">${inr(p.mv)}</td><td class="n">${f2(p.ac)}</td><td class="n ${cl(p.pl)}">${inr(p.pl)}</td></tr>`).join('')}</tbody></table></div>`}
if(st.tab=='Performance'){const a=stats('N'),b=stats('W'),pl=k=>hold(k).reduce((s,p)=>s+p.pl,0);
const R=[['Volatility (annualized)','How much returns swing from day to day.',a.vol.toFixed(1)+'%',b.vol.toFixed(1)+'%'],['Sharpe ratio','Return per unit of volatility, risk-free rate taken as zero.',a.sh.toFixed(2),b.sh.toFixed(2)],['Max drawdown','Largest fall from a peak in the selected range.',a.dd.toFixed(1)+'%',b.dd.toFixed(1)+'%'],['Unrealized P&L','Gain or loss on positions still held.',inr(pl('N')),inr(pl('W'))],['Realized P&L (sample)','Gain or loss locked in by sales.','₹18,420','₹41,960'],['Turnover (sample)','Share of the portfolio traded over the period.','34%','58%'],['Transaction costs (sample)','Estimated at 0.10% per trade.','₹6,240','₹9,870']];
return `<div class="tw"><table><thead><tr><th>Metric</th><th class="n">${PN.N}</th><th class="n">${PN.W}</th></tr></thead><tbody>${R.map(r=>`<tr><td><b>${r[0]}</b><br><span class="m">${r[1]}</span></td><td class="n">${r[2]}</td><td class="n">${r[3]}</td></tr>`).join('')}</tbody></table></div><p class="m">Benchmark comparison is hidden because no benchmark data is connected.</p>`}
if(st.tab=='Activity'){const l=O.filter(o=>o.pf==k);return `<div class="bar">${sw()}<span class="m">Paper Trading, simulated</span></div><ol class="tl">${l.map(o=>`<li class="${o.why=='News signal'?'news':''}"><b>${o.side} ${o.q} <button class="lnk" data-a="tk" data-v="${o.t}">${o.t}</button></b> at ${f2(o.px)} ${badge(o.st)}<br><span class="m">${o.ev?`<button class="lnk" data-a="ev" data-v="${o.ev}">${o.why}</button>`:o.why}. Decided ${o.d} ${o.td}, ${o.te?'executed '+o.te:'not executed'}.</span></li>`).join('')}</ol>`}
const R=[['Rebalance interval','21 trading days','21 trading days'],['Volume trigger','Not used','News acts at 1.5× the 20-day average volume'],['News sentiment threshold','Not used','Acts when sentiment is beyond ±0.50'],['Position limit','20% per stock','20% per stock'],['Transaction costs','0.10% per trade','0.10% per trade']];
return `<div class="tw"><table><thead><tr><th>Setting</th><th>${PN.N}</th><th>${PN.W}</th></tr></thead><tbody>${R.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('')}</tbody></table></div>`}
function Port(){const rs=[['1M',21],['3M',63],['1Y',252],['All',400]],a=['N','W'].map(k=>{const y=ser(k).slice(-st.range);return{k,v:y[y.length-1],r:(y[y.length-1]/y[0]-1)*100,d:day(k)}}),df=a[1].r-a[0].r,Ls=Y_(),n=Ls[0].y.length,lb=lab(400).slice(-n);
const mk=MK.filter(m=>399-m.o>=400-n).map(m=>({i:399-m.o-(400-n),c:m.r?'var(--ink)':'var(--red)',a:m.r?'rb':'ev',v:m.r?m.o:m.id,l:m.r?'Rebalance, '+dl(m.o):'News: '+EV(m.id).h}));
const fy=st.met=='v'?v=>'₹'+(v/1e5).toFixed(1)+'L':v=>v.toFixed(1)+'%',ft=st.met=='v'?inr:v=>sg(v)+'%';
return `<h1>Portfolio</h1><p class="sub">Two paper portfolios, same capital, same dates. Paper Trading only; figures are sample data.</p>
<section class="hero" aria-label="Strategy comparison">${a.map((p,i)=>`${i?`<div class="gap"><span>News-aware minus Normal, ${rs.find(x=>x[1]==st.range)[0]}</span><b class="">${sg(df)} pts</b><span>Not attributed to news alone.</span></div>`:''}<div class="pf ${i?'w':''}"><h2>${PN[p.k]}</h2><div class="big">${inr(p.v)}</div><div>Return <b class="${cl(p.r)}">${sg(p.r)}%</b>, today <b class="${cl(p.d)}">${inr(p.d)}</b></div></div>`).join('')}</section>
<div class="bar"><div class="seg" role="group" aria-label="Range">${rs.map(r=>`<button class="${st.range==r[1]?'on':''}" data-a="rng" data-v="${r[1]}">${r[0]}</button>`).join('')}</div><div class="seg" role="group" aria-label="Metric">${[['v','Value'],['r','Return'],['d','Drawdown']].map(m=>`<button class="${st.met==m[0]?'on':''}" data-a="met" data-v="${m[0]}">${m[1]}</button>`).join('')}</div></div>
<div class="lg" style="margin-bottom:8px"><span><i style="background:var(--ink)"></i>${PN.N}</span><span><i style="background:var(--red)"></i>${PN.W}</span><span class="m">Red dots: news events. Black dots: rebalances. Select one for details.</span></div>
${chart(Ls,lb,mk,fy,340,ft)}
<div class="tabs" role="tablist">${['Holdings','Performance','Activity','Strategy'].map(t=>`<button role="tab" class="${st.tab==t?'on':''}" data-a="tab" data-v="${t}">${t}</button>`).join('')}</div>${tab()}`}
const ledRows=()=>LG.filter(l=>{const n=EV(l.id);return(!st.ls||l.st==st.ls)&&(!st.lq||(n.h+n.tk.map(x=>x[0]).join(' ')).toLowerCase().includes(st.lq.toLowerCase()))}).map(l=>{const n=EV(l.id);return `<tr data-a="led" data-v="${l.id}" tabindex="0"><td data-l="Time">${dts(n.a)}</td><td class="wr" data-l="Event"><b>${n.h}</b></td><td data-l="Stocks">${n.tk.map(x=>x[0]).join(', ')}</td><td data-l="Sentiment / impact">${n.sent==null?'Not analyzed':sg(n.sent)+', '+n.imp}</td><td data-l="Decision">${l.dec}</td><td data-l="Order status">${badge(l.st)}</td></tr>`}).join('')||'<tr><td colspan="6">No events match these filters.</td></tr>';
const Ledger=()=>`<h1>Event Ledger</h1><p class="sub">Every news event and what the portfolio did about it. Only verified links are shown; gaps are marked, not filled in.</p>
<div class="filters"><input data-f="lq" placeholder="Search event or ticker" value="${st.lq}" aria-label="Search events">${sel('ls','Order status',['Filled','Pending','No order','—'].map(x=>[x,x]))}</div>
<div class="tw cw"><table><thead><tr><th>Time</th><th>News event</th><th>Affected stocks</th><th>Sentiment / impact</th><th>Portfolio decision</th><th>Order status</th></tr></thead><tbody id="lb">${ledRows()}</tbody></table></div>`;
const ordRows=()=>O.filter(o=>(!st.op||o.pf==st.op)&&(!st.os||o.side==st.os)&&(!st.oq||o.t.includes(st.oq.toUpperCase()))).map(o=>`<tr><td data-l="Decided"><span>${o.d} ${o.td}<br><span class="m">${o.te?'Executed '+o.te:'Not executed'}</span></span></td><td data-l="Portfolio">${o.pf=='W'?'News + Normal':'Normal'}</td><td data-l="Stock"><button class="lnk" data-a="tk" data-v="${o.t}">${o.t}</button></td><td data-l="Side">${o.side}</td><td class="n" data-l="Qty">${o.q}</td><td class="n" data-l="Price">${f2(o.px)}</td><td class="n" data-l="Cost">${f2(o.q*o.px*.001)}</td><td data-l="Reason">${o.ev?`<button class="lnk" data-a="ev" data-v="${o.ev}">${o.why}</button>`:o.why}</td><td data-l="Status">${badge(o.st)}</td></tr>`).join('')||'<tr><td colspan="9">No orders match these filters.</td></tr>';
const Orders=()=>`<h1>Orders</h1><p class="sub">Paper Trading history. Every order here is simulated; nothing is sent to a live broker.</p>
<div class="filters"><input data-f="oq" placeholder="Ticker" value="${st.oq}" aria-label="Filter by ticker" style="flex:0 1 140px;min-width:120px">${sel('op','Portfolio',[['N','Normal'],['W','News + Normal']])}${sel('os','Side',[['Buy','Buy'],['Sell','Sell']])}<button class="btn" data-a="new" style="margin-left:auto">${ic('plus')}New paper order</button></div>
<div class="tw cw"><table><thead><tr><th>Decided / executed</th><th>Portfolio</th><th>Stock</th><th>Side</th><th class="n">Qty</th><th class="n">Price</th><th class="n">Cost</th><th>Reason</th><th>Status</th></tr></thead><tbody id="ob">${ordRows()}</tbody></table></div>`;
/* paper order modal */
let od={pf:'W',t:'INFY',side:'Buy',q:10,step:0,id:''},oc=1007;
const est=()=>{const px=S[od.t]?.[1]||0,v=od.q*px,c=v*.001,p=H[od.pf],sh=p.pos[od.t]?.[0]||0,b=od.side=='Buy';let err='';
if(!S[od.t])err='Choose a listed ticker.';else if(!(od.q>0&&Number.isInteger(od.q)))err='Enter a whole number of shares.';else if(!b&&od.q>sh)err=`This portfolio holds ${sh} shares.`;else if(b&&v+c>p.cash)err='Not enough paper cash for this order.';
return{px,v,c,sh,err,cash:p.cash+(b?-(v+c):v-c),pos:sh+(b?1:-1)*od.q}};
const estH=()=>{const e=est();return `<div class="est"><div><span>Reference price</span><b>₹${f2(e.px)}</b></div><div><span class="m">yfinance, as of ${hh(0)} IST</span></div><div><span>Estimated trade value</span><b>${inr(e.v)}</b></div><div><span>Estimated cost (0.10%)</span><b>${inr(e.c)}</b></div><div><span>Cash after</span><b>${inr(e.cash)}</b></div><div><span>${od.t||'Position'} shares after</span><b>${e.pos}</b></div></div>${e.err?`<p class="err">${e.err}</p>`:''}`};
const omH=()=>{const h=`<h2>${od.step==2?'Paper order filled':'New paper order'} <span class="b">Paper Trading</span></h2>`;
if(od.step==0)return `${h}<label>Portfolio<select data-o="pf">${['N','W'].map(x=>`<option value="${x}"${od.pf==x?' selected':''}>${PN[x]}</option>`).join('')}</select></label><label>Ticker<input data-o="t" list="tl" value="${od.t}" autocomplete="off"></label><div class="seg" style="margin-top:12px" role="group" aria-label="Side">${['Buy','Sell'].map(s=>`<button class="${od.side==s?'on':''}" data-a="oside" data-v="${s}">${s}</button>`).join('')}</div><label>Shares<input type="number" min="1" step="1" data-o="q" value="${od.q}"></label><div id="est">${estH()}</div><div class="act"><button data-a="oc">Cancel</button><button class="btn" data-a="orev">Review order</button></div>`;
const e=est();
if(od.step==1)return `${h}<p>${od.side} <b>${od.q} ${od.t}</b> in ${PN[od.pf]} at about ₹${f2(e.px)}. Estimated value ${inr(e.v)} plus ${inr(e.c)} cost. This is a simulated order.</p><div class="act"><button data-a="oback">Back</button><button class="btn" data-a="oplace">Place paper order</button></div>`;
return `${h}<p>Order ${od.id} was filled in simulation. No live broker was contacted.</p><div class="act"><button data-a="oc">Close</button><button class="btn k" data-a="oact">View in portfolio activity</button></div>`};
const om=()=>{const m=$('#md');m.innerHTML=omH();if(!m.open)m.showModal()};
/* actions */
const A={x:close,ev:id=>dr(evH(id)),tk:t=>dr(stH(t)),led:id=>dr(ledH(id)),rb:o=>dr(rbH(o)),rng:v=>{st.range=+v;go()},met:v=>{st.met=v;go()},tab:v=>{st.tab=v;go()},pf:v=>{st.pf=v;go()},
pfd:v=>{const[k,t]=v.split(':');st.pf=k;dr(stH(t));if(pg()=='portfolio')go()},sort:v=>{st.sort=[v,st.sort[0]==v?-st.sort[1]:-1];go()},
clr:()=>{Object.assign(st,{q:'',cat:'',sen:'',src:'',age:''});go()},bell:()=>{$('#bc').hidden=true;location.hash='#/news'},
new:()=>{od.step=0;om()},oside:v=>{od.side=v;om()},oc:()=>$('#md').close(),oback:()=>{od.step=0;om()},orev:()=>{if(est().err){$('#est').innerHTML=estH();return}od.step=1;om()},
oplace:()=>{const e=est();if(e.err)return;const p=H[od.pf],b=od.side=='Buy',[sh,f]=p.pos[od.t]||[0,1],ac=sh*S[od.t][1]*f;p.cash=e.cash;
if(b)p.pos[od.t]=[sh+od.q,(ac+od.q*e.px)/((sh+od.q)*S[od.t][1])];else if(sh-od.q>0)p.pos[od.t]=[sh-od.q,f];else delete p.pos[od.t];
od.id='PT-'+oc++;O.unshift({id:od.id,pf:od.pf,t:od.t,side:od.side,q:od.q,px:e.px,why:'Manual',ev:null,td:hh(0),te:hh(0),d:'6 Oct',st:'Filled'});od.step=2;om()},
oact:()=>{$('#md').close();st.tab='Activity';st.pf=od.pf;if(pg()=='portfolio')go();else location.hash='#/portfolio'}};
document.addEventListener('click',e=>{const b=e.target.closest('[data-a]');if(b&&A[b.dataset.a])A[b.dataset.a](b.dataset.v,b)});
document.addEventListener('keydown',e=>{if(e.key=='Escape')close();if(e.key=='Enter'&&e.target.matches('[data-a]:not(button)'))e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))});
document.addEventListener('input',e=>{const t=e.target,f=t.dataset.f,o=t.dataset.o;
if(f){st[f]=t.value;const p=pg();if(p=='news')$('#feed').innerHTML=feed();else if(p=='ledger')$('#lb').innerHTML=ledRows();else if(p=='orders')$('#ob').innerHTML=ordRows()}
if(o){od[o]=o=='q'?+t.value:o=='t'?t.value.toUpperCase().trim():t.value;$('#est').innerHTML=estH()}});
$('#gs').addEventListener('change',e=>{const t=e.target.value.toUpperCase().trim();if(S[t])A.tk(t);e.target.value=''});
document.addEventListener('pointermove',e=>{const s=e.target.closest?.('.chw[data-h]'),tt=$('#tt'),cx=$('#cx');if(!s||!CH){if(tt&&CH){tt.hidden=true;cx.setAttribute('visibility','hidden')}return}
const r=s.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*CH.W,i=Math.max(0,Math.min(CH.n-1,Math.round((x-CH.P.l)/(CH.W-CH.P.l-CH.P.r)*(CH.n-1)))),X=CH.X(i);
cx.setAttribute('x1',X);cx.setAttribute('x2',X);cx.setAttribute('visibility','visible');tt.hidden=false;tt.style.left=Math.min(Math.max(X/CH.W*100,16),84)+'%';
tt.innerHTML=CH.lb[i]+CH.L.map(l=>`<br>${PN[l.k]}: <b>${CH.ft(l.y[i])}</b>`).join('')});
/* shell */
const IC={news:'<path d="M4 4h13v16H6a2 2 0 0 1-2-2z"/><path d="M17 8h3v10a2 2 0 0 1-2 2"/><path d="M8 8h5M8 12h5M8 16h3"/>',portfolio:'<path d="M12 3v9h9"/><path d="M20.5 15A9 9 0 1 1 9 3.5"/>',ledger:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',orders:'<path d="M7 4 3 8l4 4"/><path d="M3 8h14"/><path d="m17 20 4-4-4-4"/><path d="M21 16H7"/>',universe:'<circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="1.8"/><circle cx="19" cy="7" r="1.8"/><circle cx="18" cy="18" r="1.8"/><path d="M10.2 10.2 6.3 7.3M14.8 10.5 17.4 8.3M14 14l3 2.8"/>',bell:'<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',close:'<path d="M6 6l12 12M18 6 6 18"/>',plus:'<path d="M12 5v14M5 12h14"/>',bars:'<path d="M5 20V10M12 20V4M19 20v-7"/>',earn:'<path d="M5 20V10M12 20V4M19 20v-7"/>',policy:'<path d="M3 10 12 4l9 6"/><path d="M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/>',corp:'<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V4h6v3"/>',analyst:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',macro:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'};
const CI={Earnings:'earn',Policy:'policy',Corporate:'corp',Analyst:'analyst',Macro:'macro'};
const ic=n=>`<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${IC[n]}</svg>`;
const mono=t=>`<span class="mono" aria-hidden="true">${t?t.slice(0,2):ic('bars')}</span>`;
const spk=(k,p,c)=>{const n=32,r=rng(hs(k)+3),o=p/(1+c/100),m=Math.max(Math.abs(p-o),p*.004),a=Array.from({length:n},(_,i)=>o+(p-o)*i/(n-1)+(i&&i<n-1?(r()-.5)*m*1.4:0)),lo=Math.min(...a,o),hi=Math.max(...a,o),Y=v=>2+(hi-v)/(hi-lo||1)*20;
return `<svg class="sk" viewBox="0 0 64 24" aria-hidden="true"><line x1="0" x2="64" y1="${Y(o)}" y2="${Y(o)}" stroke="var(--line)" stroke-dasharray="2 2"/><polyline fill="none" stroke="${c<0?'var(--red)':'var(--grn)'}" stroke-width="1.6" stroke-linejoin="round" points="${a.map((v,i)=>(i*64/(n-1)).toFixed(1)+','+Y(v).toFixed(1)).join(' ')}"/></svg>`};
const pulse=()=>{const it=IDX.map(i=>`<span class="pi">${mono('')}<em>${i[0]}</em><b>${f2(i[1])}</b><span class="${cl(i[2])}">${sg(i[2])}%</span>${spk(i[0],i[1],i[2])}</span>`).join('')+Object.keys(S).map(t=>`<button class="pi" data-a="tk" data-v="${t}">${mono(t)}<em>${t}</em><b data-p="${t}">${f2(S[t][1])}</b><span data-c="${t}" class="${cl(S[t][2])}">${sg(S[t][2])}%</span>${spk(t,S[t][1],S[t][2])}</button>`).join('');$('#pulse').innerHTML=`<div class="pt">${it}<span style="display:contents" aria-hidden="true">${it.replace(/<button /g,'<button tabindex="-1" ')}</span></div>`};
const stamp=()=>$('#stat').innerHTML=`<span><span class="dot"></span><b>SAMPLE DATA</b> Feed not connected, stories are simulated</span><span>Updated ${hh(0)} IST</span><span><b>Paper Trading</b> simulated orders only</span><span>Prices from yfinance, may be delayed</span>`;
const flash=e=>{e.classList.remove('fl');void e.offsetWidth;e.classList.add('fl')};
const upd=t=>{$$(`[data-p="${t}"]`).forEach(e=>{e.textContent=f2(S[t][1]);flash(e)});$$(`[data-c="${t}"]`).forEach(e=>{e.textContent=sg(S[t][2])+'%';e.className=cl(S[t][2]);flash(e)})};
/* Stock Universe: 3D graph of holdings, peers, correlations and news links */
const UV=(()=>{
const esc=s=>s.replace(/&/g,'&amp;'),cmp=(v,a,b)=>Math.max(a,Math.min(b,v));
const SEC={TCS:'IT',INFY:'IT',RELIANCE:'Energy',HDFCBANK:'Banks',ICICIBANK:'Banks',SBIN:'Banks',ITC:'Consumer'};
const PEER=`KOTAKBANK|Kotak Mahindra Bank|Banks|3.9
AXISBANK|Axis Bank|Banks|3.7
WIPRO|Wipro|IT|2.8
HCLTECH|HCL Technologies|IT|4.6
TECHM|Tech Mahindra|IT|1.4
ONGC|ONGC|Energy|3.4
NTPC|NTPC|Energy|3.3
HINDUNILVR|Hindustan Unilever|Consumer|5.6
NESTLEIND|Nestlé India|Consumer|2.3
MARUTI|Maruti Suzuki|Auto|4
SUNPHARMA|Sun Pharma|Pharma|4.1
LT|Larsen & Toubro|Industrials|5
BHARTIARTL|Bharti Airtel|Telecom|10.5
TATASTEEL|Tata Steel|Metals|2`.split('\n').map(l=>l.split('|'));
const NO=[...Object.keys(S).map(t=>({t,n:S[t][0],s:SEC[t],held:1,m:0})),...PEER.map(([t,n,s,m])=>({t,n,s,held:0,m:+m}))].map((o,i)=>({...o,i,news:0}));
const ix=Object.fromEntries(NO.map(o=>[o.t,o.i]));
/* layout: sectors on a flattened sphere, nodes pushed apart */
const secs=[...new Set(NO.map(o=>o.s))],cen={},R=rng(20240731);
secs.forEach((s,k)=>{const y=1-2*(k+.5)/secs.length,r=Math.sqrt(1-y*y),th=k*2.4;cen[s]=[Math.cos(th)*r*250,y*190,Math.sin(th)*r*250]});
NO.forEach(o=>{const c=cen[o.s];o.r0=o.held?22:5+Math.sqrt(o.m)*1.3;o.b=[c[0]+(R()-.5)*120,c[1]+(R()-.5)*90,c[2]+(R()-.5)*120]});
for(let it=0;it<90;it++)for(const a of NO)for(const b of NO)if(a.i<b.i){const d=[0,1,2].map(k=>b.b[k]-a.b[k]),L=Math.hypot(...d)||1,mn=a.r0+b.r0+36;
 if(L<mn)for(let k=0;k<3;k++){const p=d[k]/L*(mn-L)/2;a.b[k]-=p;b.b[k]+=p}}
const FLOOR=Math.min(...NO.map(o=>o.b[1]-o.r0))-45;
/* sample correlations (no correlation feed is connected) */
const XS=new Set(['Banks|Industrials','Energy|Metals','Auto|Metals','Energy|Industrials','Auto|Banks','Banks|Consumer']);
const CE=[];for(let i=0;i<NO.length;i++)for(let j=i+1;j<NO.length;j++){const a=NO[i],b=NO[j],h=hs(a.t+b.t)/2147483647;
 const r=a.s===b.s?.62+h*.28:XS.has(a.s+'|'+b.s)||XS.has(b.s+'|'+a.s)?.5+h*.18:.2+h*.2;if(r>=.4)CE.push({a:i,b:j,r:+r.toFixed(2)})}
/* state (kept when you leave and return to the tab) */
const F={H:0,N:0,C:1,Nw:1,th:.65};
let W={},NE=[],cv,ctx,w=0,h=0,raf=0,yaw=.5,pitch=-.35,T=[0,0,0],dist=700,dist0=700,goal=null,auto=true,used=false,selI=-1,hovI=-1,nb=new Set(),pr=[],C={};
let cY,sY,cP,sP;
const reduced=matchMedia('(prefers-reduced-motion:reduce)').matches;if(reduced)auto=false;
const readC=()=>{const s=getComputedStyle(document.documentElement),g=k=>s.getPropertyValue(k).trim();C={bg:g('--bg'),ink:g('--ink'),red:g('--red'),mut:g('--mut'),line:g('--line')}};
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',readC);
/* news links come from the app's own stories: named stocks link to indirectly affected ones */
function build(){W=Object.fromEntries(hold(st.pf).map(p=>[p.t,p]));NO.forEach(o=>{o.news=0;if(S[o.t])o.held=W[o.t]?1:0});const m=new Map();
 NEWS.forEach(n=>{const d=n.tk.filter(x=>x[2]),ind=n.tk.filter(x=>!x[2]);
  const add=(a,b,dir)=>{const k=Math.min(a,b)+'|'+Math.max(a,b),e=m.get(k);if(!e)m.set(k,{a,b,dir,ns:[n]});else{e.ns.push(n);if(!dir||e.a!==a)e.dir=false}};
  d.forEach(x=>NO[ix[x[0]]].news=1);ind.forEach(x=>{const o=NO[ix[x[0]]];if(!o.news)o.news=2});
  d.forEach(x=>ind.forEach(y=>add(ix[x[0]],ix[y[0]],true)));
  for(let i=0;i<d.length;i++)for(let j=i+1;j<d.length;j++)add(ix[d[i][0]],ix[d[j][0]],false)});
 NE=[...m.values()]}
const rad=o=>o.held?8+Math.sqrt(W[o.t].w)*3.4:5+Math.sqrt(o.m)*1.3;
const vis=o=>o.i===selI||((!F.H||o.held)&&(!F.N||o.news));
const cOK=e=>F.C&&e.r>=F.th&&vis(NO[e.a])&&vis(NO[e.b]),nOK=e=>F.Nw&&vis(NO[e.a])&&vis(NO[e.b]);
const nbrs=i=>{const s=new Set();CE.forEach(e=>{if(cOK(e)){if(e.a===i)s.add(e.b);if(e.b===i)s.add(e.a)}});NE.forEach(e=>{if(nOK(e)){if(e.a===i)s.add(e.b);if(e.b===i)s.add(e.a)}});return s};
const counts=()=>{const e=$('#uv-cnt');if(e)e.textContent=NO.filter(vis).length+' stocks · '+CE.filter(cOK).length+' correlation links · '+NE.filter(nOK).length+' news links'};
const pj=(x,y,z)=>{x-=T[0];y-=T[1];z-=T[2];const x1=x*cY+z*sY,z1=-x*sY+z*cY,y2=y*cP-z1*sP,z2=y*sP+z1*cP,d=dist+z2,s=700/Math.max(d,1);return{x:w/2+x1*s,y:h/2-y2*s,s,z:z2,ok:d>60}};
const fa=z=>1-.5*cmp((z+300)/700,0,1);
function size(){const r=cv.getBoundingClientRect();w=r.width;h=r.height;const d=devicePixelRatio||1;cv.width=w*d;cv.height=h*d;ctx.setTransform(d,0,0,d,0,0);
 dist0=cmp(700/(Math.min(w,h)*.0017),520,1350);if(!goal&&!used)dist=dist0}
function frame(ts){if(!cv.isConnected){raf=0;return}const t=ts/1000;
 if(auto&&selI<0)yaw-=.0006;
 if(goal){const k=reduced?1:.1;for(let i=0;i<3;i++)T[i]+=(goal.T[i]-T[i])*k;dist+=(goal.d-dist)*k;if(Math.abs(dist-goal.d)<1&&Math.abs(T[0]-goal.T[0])<.5)goal=null}
 cY=Math.cos(yaw);sY=Math.sin(yaw);cP=Math.cos(pitch);sP=Math.sin(pitch);ctx.clearRect(0,0,w,h);
 pr=NO.map(o=>{const d=reduced?[0,0,0]:[Math.sin(t*.5+o.i)*5,Math.sin(t*.4+o.i*2)*5,Math.cos(t*.45+o.i*3)*5];
  const p=pj(o.b[0]+d[0],o.b[1]+d[1],o.b[2]+d[2]);p.sh=pj(o.b[0]+d[0],FLOOR,o.b[2]+d[2]);return p});
 ctx.strokeStyle=C.line;ctx.lineWidth=1;ctx.globalAlpha=.8;
 for(let k=-5;k<=5;k++){const g=k*80;[[g,-400,g,400],[-400,g,400,g]].forEach(([a,b,c,d])=>{const p=pj(a,FLOOR,b),q=pj(c,FLOOR,d);if(p.ok&&q.ok){ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke()}})}
 const order=NO.filter(o=>vis(o)&&pr[o.i].ok).sort((a,b)=>pr[b.i].z-pr[a.i].z),dimOf=i=>selI>=0&&i!==selI&&!nb.has(i);
 ctx.fillStyle=C.ink;for(const o of order){const p=pr[o.i],q=p.sh;ctx.globalAlpha=(dimOf(o.i)?.04:.11)*fa(p.z);ctx.beginPath();ctx.ellipse(q.x,q.y,rad(o)*p.s*1.15,rad(o)*p.s*.4,0,0,6.283);ctx.fill()}
 ctx.setLineDash([]);
 for(const e of CE){if(!cOK(e))continue;const a=pr[e.a],b=pr[e.b];if(!a.ok||!b.ok)continue;const hl=e.a===selI||e.b===selI,dm=selI>=0&&!hl;
  ctx.globalAlpha=(dm?.04:hl?.9:.16+(e.r-.4)*.5)*fa((a.z+b.z)/2);ctx.strokeStyle=hl?C.ink:C.mut;ctx.lineWidth=(.6+(e.r-.4)*3.2)*(a.s+b.s)/2*(hl?1.5:1);
  ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}
 for(const e of NE){if(!nOK(e))continue;const a=pr[e.a],b=pr[e.b];if(!a.ok||!b.ok)continue;const hl=e.a===selI||e.b===selI,dm=selI>=0&&!hl;
  ctx.globalAlpha=(dm?.08:hl?1:.6)*fa((a.z+b.z)/2);ctx.strokeStyle=C.red;ctx.fillStyle=C.red;ctx.lineWidth=(hl?2.2:1.5)*(a.s+b.s)/2;
  ctx.setLineDash([6,5]);ctx.lineDashOffset=reduced?0:-t*18;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.setLineDash([]);
  if(e.dir){const L=Math.hypot(b.x-a.x,b.y-a.y)||1,ux=(b.x-a.x)/L,uy=(b.y-a.y)/L,Rb=rad(NO[e.b])*b.s+5,px=b.x-ux*Rb,py=b.y-uy*Rb,z=7*b.s;
   ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px-ux*z-uy*z*.5,py-uy*z+ux*z*.5);ctx.lineTo(px-ux*z+uy*z*.5,py-uy*z-ux*z*.5);ctx.fill()}}
 for(const o of order){const p=pr[o.i],r=rad(o)*p.s,al=(dimOf(o.i)?.2:1)*fa(p.z);
  if(o.i===selI||o.i===hovI){ctx.globalAlpha=.5;ctx.strokeStyle=C.mut;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(p.x,p.y+r);ctx.lineTo(p.sh.x,p.sh.y);ctx.stroke();ctx.setLineDash([])}
  ctx.globalAlpha=al;ctx.beginPath();ctx.arc(p.x,p.y,r,0,6.283);ctx.fillStyle=o.held?C.ink:C.bg;ctx.fill();
  if(!o.held){ctx.lineWidth=1.5;ctx.strokeStyle=C.mut;ctx.stroke()}
  const g=ctx.createRadialGradient(p.x-r*.35,p.y-r*.4,r*.05,p.x,p.y,r);g.addColorStop(0,'rgba(255,255,255,.5)');g.addColorStop(.55,'rgba(255,255,255,0)');g.addColorStop(1,'rgba(0,0,0,.2)');ctx.fillStyle=g;ctx.fill();
  if(o.news){ctx.strokeStyle=C.red;ctx.lineWidth=2.4;ctx.beginPath();ctx.arc(p.x,p.y,r+3.5,0,6.283);ctx.stroke();
   if(o.news===1&&!reduced){const q=(t*.8)%1;ctx.globalAlpha=al*.3*(1-q);ctx.lineWidth=2;ctx.beginPath();ctx.arc(p.x,p.y,r+4+q*12,0,6.283);ctx.stroke()}}
  if(o.i===selI){ctx.globalAlpha=1;ctx.strokeStyle=C.red;ctx.lineWidth=3;ctx.beginPath();ctx.arc(p.x,p.y,r+7,0,6.283);ctx.stroke()}}
 ctx.globalAlpha=1;ctx.font='700 12px Archivo,system-ui,sans-serif';ctx.textBaseline='middle';
 for(const o of order.filter(o=>o.i===selI||o.i===hovI||(selI>=0&&nb.has(o.i)))){const p=pr[o.i],r=rad(o)*p.s,txt=o.t+(o.i===hovI?(o.held?'  '+W[o.t].w.toFixed(1)+'%':'  not held'):''),bw=ctx.measureText(txt).width+14,x=p.x+r+8,y=p.y-9;
  ctx.fillStyle=C.bg;ctx.globalAlpha=.95;ctx.strokeStyle=o.i===selI?C.red:C.line;ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(x,y-9,bw,20,3);ctx.fill();ctx.stroke();
  ctx.globalAlpha=1;ctx.fillStyle=C.ink;ctx.fillText(txt,x+7,y+1)}
 raf=requestAnimationFrame(frame)}
/* detail panel */
function panel(i){const d=$('#uv-det');if(!d)return;if(i<0){d.style.display='none';return}const o=NO[i],p=W[o.t],px=S[o.t]?`<span class="m">Price</span><b>₹${f2(S[o.t][1])} <span class="${cl(S[o.t][2])}">${sg(S[o.t][2])}%</span></b>`:'';
 const cl2=CE.filter(e=>(e.a===i||e.b===i)&&cOK(e)).map(e=>({j:e.a===i?e.b:e.a,r:e.r})).sort((a,b)=>b.r-a.r);
 const ns=NEWS.filter(n=>n.tk.some(x=>x[0]===o.t));
 d.innerHTML=`<div class="uv-ph"><div><h2>${o.t}</h2><p class="m">${esc(o.n)} · ${o.s}</p></div><button class="uv-x" data-u="x" aria-label="Close details">×</button></div>
 ${o.held?`<div class="uv-kv"><span class="m">Portfolio weight</span><b>${p.w.toFixed(1)}%</b><i class="uv-bar" style="grid-column:1/-1"><u style="width:${Math.min(100,p.w/20*100)}%"></u></i><span class="m">Position value</span><b>${inr(p.mv)}</b>${px}</div>`
 :`<div class="uv-kv"><span class="m">Portfolio weight</span><b>Not held</b>${o.m?`<span class="m">Market value</span><b>~₹${o.m} lakh cr</b>`:''}${px}</div>${o.m?'<p class="m" style="margin:8px 0 0">Sample peer. No price feed or stories are connected for it.</p>':''}`}
 ${S[o.t]?`<p style="margin:10px 0 0"><button class="lnk" data-a="tk" data-v="${o.t}">Open stock details</button></p>`:''}
 <h3>Correlation links (${cl2.length})</h3><p class="m uv-nt">Sample 90-day co-movement, shown as an illustration. Stocks that move together do not necessarily drive each other.</p>
 <div class="uv-cl">${cl2.map(c=>`<button data-u="${c.j}"><b>${NO[c.j].t}</b><i class="uv-bar"><u style="width:${c.r*100}%"></u></i><em>${c.r.toFixed(2)}</em></button>`).join('')||'<p class="m uv-nt">None at the current strength filter.</p>'}</div>
 <h3>News connections (${ns.length})</h3><p class="m uv-nt">Red links join stocks named in the same story. An arrow points to a stock linked only indirectly. A link is not evidence the story moved that price.</p>
 ${ns.map(n=>{const x=n.tk.find(y=>y[0]===o.t);return `<div class="uv-nw"><button class="lnk" data-a="ev" data-v="${n.id}">${n.h}</button><span class="m">${x[2]?'Named in story':'Indirect link'} · relevance ${x[1].toFixed(2)} · ${rel(n.a)}</span></div>`}).join('')||'<p class="m uv-nt">No stories link this stock right now.</p>'}
 <div class="uv-ft">${S[o.t]?`Price as of ${hh(0)} IST (yfinance, may be delayed).${ns.length?' Latest story '+rel(Math.min(...ns.map(n=>n.a)))+'.':''}`:'Sample data, not updated.'}</div>`;
 d.style.display='block';d.scrollTop=0}
function pick(i){selI=i;nb=nbrs(i);used=true;auto=false;goal={T:[...NO[i].b],d:dist0*.62};panel(i);if(innerWidth<=720){const f=$('#uv-flt');if(f)f.open=false}}
function drop(){selI=-1;nb=new Set();panel(-1)}
function find(){const q=$('#uv-q').value.trim().toLowerCase(),m=$('#uv-msg');if(!q)return;
 const o=NO.find(o=>o.t.toLowerCase()===q)||NO.find(o=>o.t.toLowerCase().startsWith(q)||o.n.toLowerCase().includes(q));m.textContent=o?'':'No match';
 if(o){if(!vis(o)){F.H=F.N=0;$('#uv-fH').checked=$('#uv-fN').checked=false;counts()}pick(o.i);$('#uv-q').blur()}}
const pan=(dx,dy)=>{const s=700/dist,r=[cY,0,sY],u=[sP*sY,cP,-sP*cY];for(let k=0;k<3;k++)T[k]+=-r[k]*dx/s+u[k]*dy/s};
function hit(e){const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;let best=-1,bz=1e9;
 for(const o of NO){if(!vis(o))continue;const p=pr[o.i];if(!p||!p.ok)continue;if(Math.hypot(p.x-mx,p.y-my)<=rad(o)*p.s+6&&p.z<bz){bz=p.z;best=o.i}}return best}
const page=()=>`<h1 class="uv-h">Stock Universe</h1><p class="sub uv-sub">How your holdings connect to the wider market. Grey lines show stocks that moved together. Red lines show stocks named in the same story. Neither one proves that a stock caused another to move.</p>
<div class="uv-top">${sw()}<input id="uv-q" list="uv-tk" placeholder="Find a stock" aria-label="Find a stock in the graph" autocomplete="off"><datalist id="uv-tk">${NO.map(o=>`<option value="${o.t}">${esc(o.n)}</option>`).join('')}</datalist><button class="uv-b" id="uv-rs">Reset view</button><span class="uv-m" id="uv-msg" role="status"></span></div>
<div class="uv-stage"><canvas id="uv-cv" tabindex="0" role="img" aria-label="Interactive 3D graph of connected stocks. Use the search box to focus a stock. Arrow keys rotate, plus and minus zoom."></canvas>
<details class="uv-pn" id="uv-flt" open><summary>Filters &amp; legend</summary><div class="uv-fb">
<label class="uv-ck"><input type="checkbox" id="uv-fH"${F.H?' checked':''}> Portfolio holdings only</label>
<label class="uv-ck"><input type="checkbox" id="uv-fN"${F.N?' checked':''}> News-affected stocks only</label>
<label class="uv-ck"><input type="checkbox" id="uv-sC"${F.C?' checked':''}> Correlation links</label>
<label class="uv-ck"><input type="checkbox" id="uv-sN"${F.Nw?' checked':''}> News links</label>
<div class="uv-rg"><span>Min. correlation</span><b id="uv-tv">${F.th.toFixed(2)}</b></div><input type="range" id="uv-th" min="0.4" max="0.9" step="0.05" value="${F.th}" aria-label="Minimum correlation">
<p class="m uv-cnt" id="uv-cnt"></p>
<div class="uv-lg">
<svg viewBox="0 0 34 18"><circle cx="17" cy="9" r="7" fill="var(--ink)"/></svg><span>Held · size = portfolio weight</span>
<svg viewBox="0 0 34 18"><circle cx="17" cy="9" r="5" fill="var(--bg)" stroke="var(--mut)" stroke-width="1.5"/></svg><span>Not held · size = market value</span>
<svg viewBox="0 0 34 18"><circle cx="17" cy="9" r="5" fill="var(--bg)" stroke="var(--mut)" stroke-width="1.5"/><circle cx="17" cy="9" r="8" fill="none" stroke="var(--red)" stroke-width="2"/></svg><span>In a current story</span>
<svg viewBox="0 0 34 18"><line x1="1" y1="9" x2="33" y2="9" stroke="var(--mut)" stroke-width="2"/></svg><span>Correlation: solid grey, thicker = stronger</span>
<svg viewBox="0 0 34 18"><line x1="1" y1="9" x2="26" y2="9" stroke="var(--red)" stroke-width="2" stroke-dasharray="4 3"/><path d="M33 9l-7-4v8z" fill="var(--red)"/></svg><span>News link: red dashed, arrow = indirect</span></div>
<p class="uv-warn"><b>Correlation is not causation.</b> A news link shows a shared story, not a measured price effect.</p></div></details>
<aside class="uv-pn" id="uv-det" aria-live="polite"></aside>
<div class="uv-hint"><b>Drag</b> rotate · <b>Shift-drag / two fingers</b> pan · <b>Scroll / pinch</b> zoom · click a stock to focus</div></div>
<p class="m">Holdings, prices and stories are the app’s own. Peers and correlations are sample data: no correlation feed is connected.</p>`;
function mount(){cv=$('#uv-cv');ctx=cv.getContext('2d');build();readC();if(selI>=0){nb=nbrs(selI)}
 const ptr=new Map();let moved=0,pd=0;const pdist=()=>{const [a,b]=[...ptr.values()];return Math.hypot(a[0]-b[0],a[1]-b[1])||1};
 cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);ptr.set(e.pointerId,[e.clientX,e.clientY]);moved=0;goal=null;auto=false;used=true;if(ptr.size===2)pd=pdist();cv.style.cursor='grabbing'});
 cv.addEventListener('pointermove',e=>{
  if(!ptr.has(e.pointerId)){hovI=hit(e);cv.style.cursor=hovI>=0?'pointer':'grab';return}
  const p=ptr.get(e.pointerId),dx=e.clientX-p[0],dy=e.clientY-p[1];moved+=Math.abs(dx)+Math.abs(dy);ptr.set(e.pointerId,[e.clientX,e.clientY]);
  if(ptr.size===2){const nd=pdist();dist=cmp(dist*pd/nd,170,1500);pd=nd;pan(dx/2,dy/2)}
  else if(e.shiftKey||e.buttons&6)pan(dx,dy);else{yaw-=dx*.006;pitch=cmp(pitch-dy*.006,-1.35,.5)}});
 cv.addEventListener('pointerup',e=>{const was=ptr.size===1&&moved<6;ptr.delete(e.pointerId);cv.style.cursor='grab';if(was){const k=hit(e);k>=0?pick(k):drop()}});
 cv.addEventListener('pointercancel',e=>ptr.delete(e.pointerId));
 cv.addEventListener('pointerleave',()=>{hovI=-1});
 cv.addEventListener('contextmenu',e=>e.preventDefault());
 cv.addEventListener('wheel',e=>{e.preventDefault();goal=null;used=true;dist=cmp(dist*Math.exp(e.deltaY*.0012),170,1500)},{passive:false});
 cv.addEventListener('keydown',e=>{const k=e.key,m={ArrowLeft:()=>yaw+=.08,ArrowRight:()=>yaw-=.08,ArrowUp:()=>pitch=cmp(pitch+.06,-1.35,.5),ArrowDown:()=>pitch=cmp(pitch-.06,-1.35,.5),'+':()=>dist=cmp(dist*.9,170,1500),'=':()=>dist=cmp(dist*.9,170,1500),'-':()=>dist=cmp(dist/.9,170,1500),Escape:drop}[k];if(m){e.preventDefault();goal=null;auto=false;used=true;m()}});
 $('#uv-det').addEventListener('click',e=>{const b=e.target.closest('[data-u]');if(!b)return;b.dataset.u==='x'?drop():pick(+b.dataset.u)});
 $('#uv-rs').onclick=()=>{drop();yaw=.5;pitch=-.35;goal={T:[0,0,0],d:dist0};auto=!reduced;used=false};
 const upd=()=>{F.H=$('#uv-fH').checked?1:0;F.N=$('#uv-fN').checked?1:0;F.C=$('#uv-sC').checked?1:0;F.Nw=$('#uv-sN').checked?1:0;F.th=+$('#uv-th').value;$('#uv-tv').textContent=F.th.toFixed(2);if(selI>=0){nb=nbrs(selI);panel(selI)}counts()};
 ['#uv-fH','#uv-fN','#uv-sC','#uv-sN','#uv-th'].forEach(s=>$(s).addEventListener('input',upd));
 $('#uv-q').addEventListener('change',find);$('#uv-q').addEventListener('keydown',e=>{if(e.key==='Enter')find()});$('#uv-q').addEventListener('input',()=>$('#uv-msg').textContent='');
 if(innerWidth<=720)$('#uv-flt').open=false;
 new ResizeObserver(size).observe(cv);size();counts();panel(selI);cancelAnimationFrame(raf);raf=requestAnimationFrame(frame)}
/* a new story arrived while the tab is open */
const refresh=()=>{if(!cv||!cv.isConnected)return;build();if(selI>=0){nb=nbrs(selI);panel(selI)}counts()};
return{page,mount,refresh}})();
function go(){const p=pg();$$('#nav a').forEach(a=>a.classList.toggle('on',a.hash=='#/'+p));$('#app').innerHTML=({news:News,portfolio:Port,ledger:Ledger,orders:Orders,universe:UV.page}[p]||News)();if(p=='universe')UV.mount()}
let mq=innerWidth<=720;addEventListener('resize',()=>{const m=innerWidth<=720;if(m!=mq){mq=m;go()}});
$('#nav').addEventListener('click',e=>{const a=e.target.closest('a');if(!a)return;e.preventDefault();close();if(location.hash!==a.hash)location.hash=a.hash;else{go();scrollTo(0,0)}});
addEventListener('hashchange',()=>{go();scrollTo(0,0)});
$('#tl').innerHTML=Object.keys(S).map(t=>`<option value="${t}">${S[t][0]}</option>`).join('');
const runner=()=>{const it=NEWS.map(n=>`<button data-a="ev" data-v="${n.id}"><span class="tm">${hh(n.a)}</span><b class="rh">${n.h}</b>${n.tk.slice(0,2).map(x=>`<span>${x[0]} <span data-c="${x[0]}" class="${cl(S[x[0]][2])}">${sg(S[x[0]][2])}%</span></span>`).join('')}</button>`).join('');
$('#run').innerHTML=`<b>LATEST</b><div class="rw"><div class="rt" style="--d:${NEWS.length*12}s;animation-duration:var(--d)">${it}<span style="display:contents" aria-hidden="true">${it.replace(/<button /g,'<button tabindex="-1" ')}</span></div></div>`};
$$('#nav a').forEach((a,i)=>a.insertAdjacentHTML('afterbegin',ic(['news','portfolio','ledger','orders','universe'][i])));$('.bell').insertAdjacentHTML('afterbegin',ic('bell'));$('.av').innerHTML=ic('user');
pulse();stamp();runner();go();
setInterval(()=>{if(pg()!='news')return;const k=Object.keys(S),t=k[Math.floor(Math.random()*k.length)],d=(Math.random()-.5)*.004;S[t][1]*=1+d;S[t][2]+=d*100;upd(t)},4000);
setTimeout(()=>{const h0=document.documentElement.scrollHeight;NEWS.unshift({id:7,a:0,fresh:1,src:'Market Desk',cat:'Macro',sent:.44,imp:'Medium',h:'Software exporters rally as rupee slips past a key level',s:'A weaker rupee lifts earnings expectations for dollar-billing firms.',tk:[['TCS',.82,1],['INFY',.8,1]]});stamp();runner();if(pg()=='universe')UV.refresh();
const b=$('#bc');b.hidden=false;b.textContent=+b.textContent+1;
if(pg()=='news'){$('#feed').innerHTML=feed();$('#side').innerHTML=side();if(scrollY>40)scrollBy(0,document.documentElement.scrollHeight-h0)}
setTimeout(()=>{delete NEWS[0].fresh;$('.row.fresh')?.classList.remove('fresh')},4500)},7000);

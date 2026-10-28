import {useEffect,useRef,useState} from 'react';
import ChartJS from 'chart.js/auto';
import {getJSON} from './api.js';

ChartJS.defaults.font.family="'Manrope',sans-serif";ChartJS.defaults.font.weight=500;
ChartJS.defaults.color='#0B2545';ChartJS.defaults.borderColor='rgba(11,37,69,.1)';
const INK='#0B2545',PAL=['#0B2545','#2F80ED','#7CC4F0','#FF6B3D','#5B7DB1','#B0E0E6'];
const CAT={Bullet:'#0B2545',Blitz:'#2F80ED',Rapid:'#7CC4F0',Classical:'#FF6B3D'};
const SHAPE=['circle','rect','triangle','rectRot','star','crossRot'];
const fmt=(v,t)=>v==null?'\u2014':t==='percent'?(v*100).toFixed(1)+'%':typeof v==='number'?v.toLocaleString('en-US',{maximumFractionDigits:3}):v;

function useData(path){const [s,set]=useState({d:null,e:null});
  useEffect(()=>{let on=1;getJSON(path).then(d=>on&&set({d,e:null}),e=>on&&set({d:null,e:e.message}));return()=>{on=0}},[path]);return s}
const Load=({path,children})=>{const {d,e}=useData(path);
  if(e)return <div className="state err"><b>This panel failed to load.</b> {e}</div>;
  if(!d)return <div className="sk"/>;
  if(d.available===false)return <div className="state"><b>Not computed yet.</b> {d.reason}</div>;
  return children(d)};
const P=({t,cap,children,cls=''})=><section className={'panel '+cls}><h3>{t}</h3>{children}{cap&&<p className="cap">{cap}</p>}</section>;
const Chart=({cfg,h=300})=>{const r=useRef();
  useEffect(()=>{const c=new ChartJS(r.current,{...cfg,options:{maintainAspectRatio:false,animation:{duration:900,easing:'easeOutQuart'},...cfg.options}});return()=>c.destroy()},[JSON.stringify(cfg)]);
  return <div className="cv" style={{height:h}}><canvas ref={r}/></div>};
const ax=(x,y,extra={})=>({scales:{x:{title:{display:!!x,text:x},...extra.x},y:{title:{display:!!y,text:y},...extra.y}},plugins:{legend:{labels:{usePointStyle:true}}}});

function T({cols,rows,max=12}){const [s,setS]=useState({k:null,d:1});
  const R=s.k?[...rows].sort((a,b)=>(a[s.k]>b[s.k]?1:-1)*s.d):rows;
  return <div className="tw" style={{maxHeight:max*40}}><table><thead><tr>{cols.map(c=>
    <th key={c.key} className={c.type?'num':''} tabIndex={0} onClick={()=>setS({k:c.key,d:s.k===c.key?-s.d:1})}
      onKeyDown={e=>e.key==='Enter'&&setS({k:c.key,d:s.k===c.key?-s.d:1})}>{c.label}{s.k===c.key?(s.d>0?' \u25B2':' \u25BC'):''}</th>)}</tr></thead>
    <tbody>{R.map((r,i)=>{const low=r.n!=null&&r.n<30;return <tr key={i} className={(low?'low ':'')+(r.is_total?'tot':'')}>{cols.map((c,j)=>
      <td key={c.key} className={c.type&&c.type!=='text'?'num':''}>{c.r?c.r(r):fmt(r[c.key],c.type)}{j===0&&low&&<em className="tag">low n</em>}</td>)}</tr>})}</tbody></table></div>}

const NAV=[['overview','Overview','Module 1'],['schema','Schema','Module 1'],['olap','OLAP explorer','Module 1'],['lake','Data lake vs warehouse','Module 2'],['explore','Data exploration','Module 3'],['mining','Classification & regression','Module 4'],
  ['clusters','Clustering','Module 5'],['rules','Association rules','Module 6'],['cheat','Cheat triage','Extension'],['method','Methodology & limits','Module 3']];

function Overview(){const {d:m}=useData('/api/olap/monthly');
  return <Load path="/api/overview">{o=><>
    <div className="kpis">{[['est_games_total','estimated games (weighted)'],['sample_games','games in our sample'],['players','players'],['analysed_games','Stockfish-analysed games']].map(([k,l])=>
      <div key={k}><b>{o.kpis[k].toLocaleString('en-US')}</b><span>{l}</span></div>)}</div>
    <P t="Estimated games per month" cap="Weighted estimates (est_games). 2016-05 and 2017-07 are missing from the source files and shown as breaks, not zeros.">
      {m?<Chart cfg={{type:'line',data:{labels:m.rows.map(r=>r.month),datasets:[{label:'est_games',data:m.rows.map(r=>r.est_games),borderColor:INK,backgroundColor:'rgba(124,196,240,.35)',fill:true,spanGaps:false,tension:.3,pointRadius:2}]},options:ax('Month','Estimated games')}}/>:<div className="sk"/>}</P>
    <div className="g2"><P t="Category mix: estimate vs sample" cap="Classical is about 1.9% of real games but 20% of our sample. Never read share from the sample (rule R1).">
      <Chart cfg={{type:'bar',data:{labels:o.category_mix.map(c=>c.category),datasets:[{label:'est_share (real)',data:o.category_mix.map(c=>c.est_share*100),backgroundColor:INK},{label:'sample_share',data:o.category_mix.map(c=>c.sample_share*100),backgroundColor:'#7CC4F0'}]},options:ax('Category','Share of games (%)')}}/></P>
      <P t="Warehouse tables" cap="Row counts in PostgreSQL."><T cols={[{key:'table',label:'Table'},{key:'rows',label:'Rows',type:'integer'}]} rows={o.table_rows}/></P></div>
    <P t="Pipeline" cap="Raw files to dashboard."><div className="flow">{['Raw files','Staging','Warehouse','OLAP','Mining','API','UI'].map(s=><span key={s}>{s}</span>)}</div></P></>}</Load>}

const OPS={rollup:{level:'year'},drilldown:{year:2017},slice:{dimension:'category',value:'Blitz'},dice:{categories:'Blitz,Rapid',years:'2016,2017'},pivot:{rows:'category',cols:'rating_band',measure:'est_games'}};
function Olap(){const [op,setOp]=useState('rollup');const [p,setP]=useState(OPS.rollup);const [sql,setSql]=useState(false);
  const pick=o=>{setOp(o);setP(OPS[o])};
  const q=new URLSearchParams(p).toString();
  return <><div className="ops">{Object.keys(OPS).map(o=><button key={o} className={'nb'+(o===op?' on':'')} onClick={()=>pick(o)}>{o==='rollup'?'Roll-up':o==='drilldown'?'Drill-down':o[0].toUpperCase()+o.slice(1)}</button>)}</div>
    <div className="ctl">{Object.entries(p).map(([k,v])=><label key={k}>{k}<input value={v} onChange={e=>setP({...p,[k]:e.target.value})}/></label>)}</div>
    <Load path={`/api/olap/${op}?${q}`}>{d=>{const ch=d.chart,ok=ch&&ch.type!=='none'&&ch.type!=='heatmap',cr=d.rows.filter(r=>!r.is_total);return <>
      <P t={d.title} cap={d.note}>
        <div className="meta"><span className="badge">{d.elapsed_ms} ms</span><button className="lnk" onClick={()=>setSql(!sql)}>{sql?'Hide SQL':'Show SQL'}</button></div>
        {sql&&<pre className="code">{d.sql}</pre>}
        {ok&&<Chart cfg={{type:ch.type==='line'?'line':'bar',data:{labels:cr.map(r=>r[ch.x]),datasets:ch.series.map((s,i)=>({label:s,data:cr.map(r=>r[s]),backgroundColor:PAL[i%6],borderColor:PAL[i%6],pointStyle:SHAPE[i%6]}))},
          options:{...ax(ch.x,'Value'),scales:{x:{stacked:ch.type==='stacked_bar'},y:{stacked:ch.type==='stacked_bar'}}}}}/>}</P>
      <P t="Result table" cap="Click a header to sort. Greyed rows have n < 30."><T cols={d.columns} rows={d.rows}/></P></>}}</Load></>}

function CM({m,cl}){return <div className="cm" style={{gridTemplateColumns:`auto repeat(${cl.length},1fr) auto`}}><i/>{cl.map(c=><i key={c}>{c}</i>)}<i>recall</i>
  {m.map((r,i)=>{const s=r.reduce((a,b)=>a+b,0)||1;return [<i key={'l'+i}>{cl[i]}</i>,...r.map((v,j)=><b key={i+'_'+j} style={{background:`rgba(11,37,69,${.08+.8*v/s})`,color:v/s>.45?'#fff':INK}}>{v.toLocaleString()}</b>),<i key={'r'+i}>{(r[i]/s*100).toFixed(0)}%</i>]})}</div>}
function Mining(){return <>
  <Load path="/api/mining/classification">{c=><>
    <P t="Predicting game result" cap={`${c.n_train.toLocaleString()} train / ${c.n_test.toLocaleString()} test rows. ${c.note}`}>
      <T cols={[{key:'name',label:'Model'},{key:'accuracy',label:'Accuracy',type:'percent'},{key:'macro_f1',label:'Macro F1',type:'number'}]} rows={c.models}/></P>
    <div className="g3">{c.models.map(m=><P key={m.name} t={m.name} cap="Rows are true class, columns are predicted."><CM m={m.confusion_matrix} cl={c.classes}/></P>)}</div>
    <div className="g2"><P t="Information gain" cap="Bits of result entropy each attribute explains.">
      <Chart h={240} cfg={{type:'bar',data:{labels:c.information_gain.map(x=>x.attribute),datasets:[{label:'bits',data:c.information_gain.map(x=>x.info_gain_bits),backgroundColor:INK}]},options:{...ax('Information gain (bits)',''),indexAxis:'y'}}}/></P>
      <P t="Tree rules" cap="Decision tree, entropy criterion."><pre className="code">{c.tree_rules}</pre></P></div></>}</Load>
  <Load path="/api/mining/regression">{r=><>
    <div className="kpis"><div><b>{r.simple.r2_test}</b><span>R² (simple, test)</span></div><div><b>{r.multiple.r2_test}</b><span>R² (multiple, test)</span></div><div><b>{r.simple.slope_per_100_elo}</b><span>ACPL per +100 Elo</span></div></div>
    <div className="g2"><P t="ACPL against Elo" cap="ACPL = average centipawn loss: lower is better play (Stockfish depth 12).">
      <Chart cfg={{type:'line',data:{labels:r.binned.map(b=>b.elo_bin),datasets:[{label:'mean ACPL',data:r.binned.map(b=>b.mean_acpl),showLine:false,pointStyle:'rectRot',pointRadius:6,backgroundColor:'#FF6B3D'},{label:'fitted',data:r.binned.map(b=>b.fitted_acpl),borderColor:INK,pointRadius:0}]},options:ax('Elo bin','ACPL')}}/></P>
      <P t="Coefficients" cap={r.multiple.formula}><T cols={[{key:'term',label:'Term'},{key:'value',label:'Coefficient',type:'number'}]} rows={Object.entries(r.multiple.coefficients).map(([term,value])=>({term,value}))}/></P></div></>}</Load></>}

function Clusters(){return <Load path="/api/mining/clusters">{c=>{const F=['avg_elo','abs_elo_gap','plies','median_duration_s','pct_forfeit'],mx=F.map(f=>Math.max(...c.clusters.map(x=>x[f]))||1);return <>
  <div className="kpis"><div><b>{c.k}</b><span>clusters (k-means)</span></div><div><b>{c.silhouette}</b><span>silhouette</span></div></div>
  <P t="Cluster profiles" cap={c.note}><T max={8} cols={[{key:'name',label:'Cluster'},{key:'pct_games',label:'% games',type:'number'},{key:'avg_elo',label:'Avg Elo',type:'number'},{key:'abs_elo_gap',label:'Elo gap',type:'number'},{key:'plies',label:'Plies',type:'number'},{key:'median_duration_s',label:'Median s',type:'number'},{key:'pct_forfeit',label:'% on time',type:'number'},{key:'white_score',label:'White score',type:'number'}]} rows={c.clusters}/></P>
  <P t="Features compared" cap="Each feature scaled to its largest cluster value so bars are comparable."><Chart h={340} cfg={{type:'bar',data:{labels:F,datasets:c.clusters.map((x,i)=>({label:x.name,data:F.map((f,j)=>x[f]/mx[j]),backgroundColor:PAL[i%6]}))},options:ax('Feature','Relative to max')}}/></P>
  <Load path="/api/mining/hierarchical">{h=><P t="Hierarchical clustering" cap={`Agglomerative, ${h.linkage_method} linkage, ${h.n_samples} sampled games. Cutting the tree at the dashed line gives ${h.cut.n_clusters} clusters.`}><Dendro h={h}/></P>}</Load></>}}</Load>}

function Rules(){const [mc,setMc]=useState(.5),[ml,setMl]=useState(1.2),[so,setSo]=useState('lift');
  return <><div className="ctl"><label>min confidence<input type="number" step=".05" value={mc} onChange={e=>setMc(e.target.value)}/></label>
    <label>min lift<input type="number" step=".1" value={ml} onChange={e=>setMl(e.target.value)}/></label>
    <label>sort by<select value={so} onChange={e=>setSo(e.target.value)}><option>lift</option><option>confidence</option><option>support</option></select></label></div>
  <Load path={`/api/mining/rules?min_confidence=${mc}&min_lift=${ml}&sort=${so}&limit=50`}>{r=>
    <P t={`${r.total_rules.toLocaleString()} rules`} cap="Lift favours rare deep lines; read it together with support and confidence."><T max={14} cols={[{key:'antecedent',label:'If played'},{key:'consequent',label:'Then'},{key:'support',label:'Support',type:'percent'},{key:'confidence',label:'Confidence',type:'percent'},{key:'lift',label:'Lift',type:'number'},
      {key:'s',label:'In plain English',r:x=>`When ${x.antecedent} are played, ${x.consequent} follows ${(x.confidence*100).toFixed(0)}% of the time.`}]} rows={r.rows}/></P>}</Load>
  <Load path="/api/mining/apriori_benchmark">{b=><P t="Apriori vs FP-Growth" cap="FP-Growth avoids candidate generation, so it stays fast as support drops.">
    <Chart cfg={{type:'bar',data:{labels:b.runs.map(r=>r.min_support),datasets:[{label:'Apriori',data:b.runs.map(r=>r.apriori_seconds),backgroundColor:INK},{label:'FP-Growth',data:b.runs.map(r=>r.fpgrowth_seconds),backgroundColor:'#7CC4F0'}]},options:ax('Minimum support','Seconds')}}/></P>}</Load></>}

function Cheat(){const [sig,setSig]=useState('both');return <>
  <div className="banner">Statistical triage only. A high score means worth a human look, not that the player cheated.</div>
  <GameLookup/>
  <Load path="/api/cheat/summary">{s=><div className="g2">
    <P t="Signal counts" cap="both = uniform move timing and top-1% move quality. timing_only and quality_only = one signal. none = neither."><Chart h={240} cfg={{type:'bar',data:{labels:s.signal_counts.map(x=>x.signal),datasets:[{label:'sides',data:s.signal_counts.map(x=>x.count),backgroundColor:PAL}]},options:{...ax('Signal','Scored sides'),scales:{y:{type:'logarithmic',title:{display:true,text:'Scored sides (log scale)'}}},plugins:{legend:{display:false}}}}}/></P>
    <P t="Timing flags vs matched controls" cap={`${s.tier1_validation.pairs} matched pairs. ${s.tier1.flag_rule}`}><T cols={[{key:'m',label:'Measure'},{key:'f',label:'Flagged',type:'number'},{key:'c',label:'Control',type:'number'}]} rows={[{m:'Mean ACPL',f:s.tier1_validation.flagged_mean_acpl,c:s.tier1_validation.control_mean_acpl},{m:'Match rate',f:s.tier1_validation.flagged_match,c:s.tier1_validation.control_match}]}/></P></div>}</Load>
  <div className="ctl">{['both','timing_only','quality_only'].map(x=><button key={x} className={'nb'+(x===sig?' on':'')} onClick={()=>setSig(x)}>{x}</button>)}</div>
  <Load path={`/api/cheat/top?signal=${sig}&limit=25`}>{t=><P t={`${t.total} flagged sides`} cap="z_cv: how much more uniform than normal this player's move times are (more negative is more uniform). ACPL: average centipawn loss (lower is more engine-like). match_rate: share of moves equal to Stockfish's first choice."><T max={12} cols={[{key:'category',label:'Category'},{key:'rating_band',label:'Band'},{key:'elo',label:'Elo',type:'integer'},{key:'z_cv',label:'z_cv',type:'number'},{key:'acpl',label:'ACPL',type:'number'},{key:'match_rate',label:'Match rate',type:'percent'},{key:'score',label:'Score',type:'number'},
    {key:'u',label:'Game',r:x=><a href={x.lichess_url} target="_blank" rel="noopener noreferrer">View on Lichess</a>}]} rows={t.rows}/></P>}</Load>
  <Load path="/api/cheat/classifier">{c=>{const ms=[...new Set(c.rows.map(r=>r.model))];return <>
    <div className="banner soft">Labels are simulated (engine moves injected into real games). This measures how separable simulated assistance is, not accuracy at catching real cheaters.</div>
    <div className="g2"><P t="AUC against share of moves substituted" cap="Higher means simulated assistance is easier to separate."><Chart cfg={{type:'line',data:{labels:[...new Set(c.rows.map(r=>r.p_substituted))],datasets:ms.map((m,i)=>({label:m,data:c.rows.filter(r=>r.model===m).map(r=>r.auc),borderColor:PAL[i*3%6],pointStyle:SHAPE[i]}))},options:ax('Share of moves substituted','AUC')}}/></P>
      <P t="Precision at 0.5% prevalence" cap="At a 1% false-positive rate."><T cols={[{key:'model',label:'Model'},{key:'p_substituted',label:'Substituted',type:'percent'},{key:'auc',label:'AUC',type:'number'},{key:'prec_at_fpr1pct_prev0.5pct',label:'Precision',type:'percent'}]} rows={c.rows}/>
        <p className="call">Even at 80% substitution, precision is only about 33%: false alarms from the honest majority outnumber the true catches.</p></P></div></>}}</Load></>}


const Sel=({v,set,o})=><select value={v} onChange={e=>set(e.target.value)}>{o.map(x=><option key={x}>{x}</option>)}</select>;
const Txt=({children})=><div className="txt">{children}</div>;

function Schema(){return <Load path="/api/schema">{s=>{const f=s.fact_tables[0],c=s.fact_tables[1];
  const N={'game_fact':[290,200,190,76],'cheat_score':[700,200,170,76],'dim_player (white)':[20,40,180,56],'dim_player (black)':[20,364,180,56],'dim_time':[300,20,170,56],'dim_opening':[300,384,170,56],'dim_timecontrol':[560,20,190,56]};
  const mid=k=>[N[k][0]+N[k][2]/2,N[k][1]+N[k][3]/2];
  const E=[...f.dimensions.map(d=>['game_fact',d]),['cheat_score','dim_time'],['cheat_score','dim_opening'],['cheat_score','dim_timecontrol'],['cheat_score','dim_player (white)']].filter(([a,b])=>N[a]&&N[b]);
  return <><P t="Fact constellation" cap={`Two fact tables share the same dimensions. ${f.name}: ${f.grain} (${f.rows.toLocaleString()} rows). ${c.name}: ${c.grain} (${c.rows.toLocaleString()} rows).`}>
    <svg viewBox="0 0 900 470" className="schema">{E.map(([a,b],i)=>{const p=mid(a),q=mid(b);return <line key={i} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} className={a==='cheat_score'?'ed2':'ed'}/>})}
      {Object.entries(N).map(([k,[x,y,w,h]])=>{const fact=k==='game_fact'||k==='cheat_score',r=s.dimensions.find(d=>d.name===k.split(' ')[0]),rows=fact?(k==='game_fact'?f.rows:c.rows):r&&r.rows;
        return <g key={k} className={fact?'nf':'nd'}><rect x={x} y={y} width={w} height={h}/><text x={x+w/2} y={y+h/2-(rows?4:-5)} textAnchor="middle">{k}</text>{rows&&<text x={x+w/2} y={y+h/2+16} textAnchor="middle" className="rw">{rows.toLocaleString()} rows</text>}
          {k==='game_fact'&&<title>game_id is a degenerate dimension: it identifies the game but has no dimension table of its own.</title>}</g>})}</svg></P>
    <div className="g2"><P t="Grain" cap="Measure additivity decides how a number may be aggregated."><Txt><p><b>{f.name}:</b> {f.grain}.</p><p><b>{c.name}:</b> {c.grain}.</p><p>game_id is a degenerate dimension (hover the fact table in the diagram).</p></Txt></P>
      <P t="Measures" cap="Non-additive measures need sample_weight to aggregate."><T cols={[{key:'name',label:'Measure'},{key:'additive',label:'Additive',r:x=>x.additive?'yes':'no'},{key:'note',label:'Note'}]} rows={[...f.measures,...c.measures]}/></P></div></>}}</Load>}

function Lake(){return <><P t="Where our data lives" cap="Data moves left to right and gets cleaner and smaller at each zone."><div className="flow">{['Raw zone: .pgn.zst files, 64.7 GB','Curated zone: staging CSV','Warehouse: PostgreSQL star schema'].map(s=><span key={s}>{s}</span>)}</div></P>
  <P t="Data lake vs data warehouse" cap="Lake = our raw zone. Warehouse = our PostgreSQL."><T max={8} cols={[{key:'a',label:''},{key:'b',label:'Data lake (raw zone)'},{key:'c',label:'Data warehouse (PostgreSQL)'}]} rows={[
    {a:'Data',b:'Raw, as downloaded (.pgn.zst)',c:'Cleaned, structured star schema'},{a:'Schema',b:'Schema-on-read',c:'Schema-on-write'},{a:'Users',b:'Data engineers, data scientists',c:'Analysts, dashboards'},
    {a:'Cost of storage',b:'Cheap, large (64.7 GB)',c:'Higher per GB, smaller (about 1M games)'},{a:'Flexibility',b:'High, any question later',c:'Fixed to modelled questions, fast'}]}/></P></>}

function Explore(){const [mt,setMt]=useState('acpl'),[by,setBy]=useState('rating_band'),[hm,setHm]=useState('plies');return <>
  <Load path="/api/explore/summary">{s=><P t="Summary statistics" cap="Sample-based and unweighted: describes our sampled games, not all of Lichess."><T cols={['variable','count','mean','std','min','q1','median','q3','max'].map((k,i)=>({key:k,label:k,type:i?'number':undefined}))} rows={s.rows}/></P>}</Load>
  <div className="ctl"><label>metric<Sel v={mt} set={setMt} o={['acpl','match_rate','elo']}/></label><label>group by<Sel v={by} set={setBy} o={['rating_band','category']}/></label></div>
  <Load path={`/api/explore/boxplot?metric=${mt}&by=${by}`}>{b=><P t={`${mt} by ${by}`} cap="Box = middle 50% of values, diamond = median, thin bar = whiskers. ACPL falls as rating rises.">
    <Chart cfg={{type:'bar',data:{labels:b.rows.map(r=>r.group),datasets:[{label:'whiskers',grouped:false,data:b.rows.map(r=>[r.whisker_low,r.whisker_high]),backgroundColor:'rgba(11,37,69,.45)',barPercentage:.06,categoryPercentage:1},{label:'q1 to q3',grouped:false,data:b.rows.map(r=>[r.q1,r.q3]),backgroundColor:'#7CC4F0',borderColor:INK,borderWidth:1.5,barPercentage:.5},{type:'line',label:'median',data:b.rows.map(r=>r.median),showLine:false,pointStyle:'rectRot',pointRadius:8,backgroundColor:'#FF6B3D',borderColor:INK}]},options:ax(by,mt)}}/></P>}</Load>
  <div className="ctl"><label>histogram of<Sel v={hm} set={setHm} o={['plies','white_elo','acpl']}/></label></div>
  <div className="g2"><Load path={`/api/explore/histogram?metric=${hm}&bins=30`}>{h=><P t={`Distribution of ${hm}`} cap="Number of sampled games per bin."><Chart cfg={{type:'bar',data:{labels:h.bins.map(b=>`${b.from}-${b.to}`),datasets:[{label:'games',data:h.bins.map(b=>b.count),backgroundColor:'#2F80ED',barPercentage:1,categoryPercentage:1}]},options:{...ax(hm,'Sample games'),plugins:{legend:{display:false}}}}}/></P>}</Load>
    <Load path="/api/explore/scatter?x=elo&y=acpl&n=2000">{s=><P t="Elo against ACPL" cap="Random sample of player-sides. Higher rating, lower ACPL (better play).">
      <Chart cfg={{type:'scatter',data:{datasets:Object.keys(CAT).map((k,i)=>({label:k,data:s.points.filter(p=>p.category===k),backgroundColor:CAT[k]+'99',pointStyle:SHAPE[i],pointRadius:4}))},options:ax('Elo','ACPL')}}/></P>}</Load></div>
  <P t="Preprocessing steps" cap="Module 3: KDD preparation."><Txt><p><b>Cleaning.</b> Games shorter than 10 plies are dropped. Unparseable games are skipped and counted.</p><p><b>Integration.</b> Players, openings, time and time control go into dimension tables, linked by surrogate keys.</p><p><b>Transformation.</b> Time-control buckets from estimated duration = base + 40 x increment (Bullet up to 179 s, Blitz up to 479, Rapid up to 1499, else Classical). Elo is split into 6 rating bands. Result becomes a white score (1, 0.5, 0).</p><p><b>Reduction.</b> Stratified sampling.</p></Txt></P></>}

function Dendro({h}){const n=h.leaves.length,M=h.merges,X={},Y={},ord=[];
  (function w(i){if(i<n)return ord.push(i);w(M[i-n].left);w(M[i-n].right)})(n+M.length-1);
  ord.forEach((id,k)=>{X[id]=30+k*(840/Math.max(n-1,1));Y[id]=0});
  const mx=Math.max(...M.map(m=>m.distance)),y=d=>360-d/mx*330,segs=[];
  M.forEach((m,i)=>{const id=n+i;X[id]=(X[m.left]+X[m.right])/2;Y[id]=m.distance;segs.push(`M${X[m.left]},${y(Y[m.left])}V${y(m.distance)}H${X[m.right]}V${y(Y[m.right])}`)});
  return <svg viewBox="0 0 900 380" className="schema">{segs.map((d,i)=><path key={i} d={d} className="dg"/>)}
    {h.cut&&<g><line x1="0" x2="900" y1={y(h.cut.distance)} y2={y(h.cut.distance)} className="cut"/><text x="880" y={y(h.cut.distance)-6} textAnchor="end" className="rw">cut: {h.cut.n_clusters} clusters</text></g>}</svg>}

function Method(){return <><div className="g2"><P t="Sampling" cap="Equal allocation across cells keeps small cells (Classical, 2400+) large enough to analyse."><Txt><p>60 monthly files, 288,688,572 games read. Stratified reservoir sampling by month, time-control category and rating band (up to 800 games per cell), keeping 954,538 games.</p></Txt></P>
  <P t="Weights" cap="Rule R1: never mix sample counts with estimated counts."><Txt><p>Each game carries sample_weight = games seen in its cell / games kept, so population statistics are unbiased. The weights sum to about 282.4M games.</p></Txt></P></div>
  <P t="Missing months" cap="Drawn as breaks in every time chart, never as zeros."><Txt><p>2016-05 and 2017-07 are missing from the downloaded files. Yearly totals for 2016 and 2017 are therefore lower than reality.</p></Txt></P>
  <P t="KDD process" cap="Knowledge discovery in databases."><div className="flow">{['Selection: Lichess files','Preprocessing and cleaning','Transformation: warehouse','Data mining: OLAP, rules, clusters, classification, regression','Evaluation: dashboard'].map(s=><span key={s}>{s}</span>)}</div></P>
  <P t="Limitations" cap="What the numbers cannot tell you."><Txt><ul>{['11 of 954,538 staging rows were not loaded (cause not investigated).','Clock data exists only for part of 2017 and for 2018.','Stockfish analysis covers about 51,000 clock-bearing games (depth 12).','Cheat scores are statistical triage signals with no ground truth.','The classifier is trained on simulated assistance.','ACPL values are specific to depth 12 and fast time controls.'].map(l=><li key={l}>{l}</li>)}</ul></Txt></P></>}

function GameLookup(){const [v,setV]=useState(''),[id,setId]=useState('');
  const go=e=>{e.preventDefault();setId(v.trim().replace(/^https?:\/\/lichess\.org\//,'').split(/[/?#]/)[0].slice(0,8))};
  return <P t="Check a game" cap="Paste a Lichess link or the 8-character game ID. Only games we analysed (about 51,000, from 2017 to 2018) have a score. A high score means worth a human look, nothing more.">
    <form className="ctl" onSubmit={go}><label>Lichess link or game ID<input style={{minWidth:340}} value={v} onChange={e=>setV(e.target.value)} placeholder="https://lichess.org/v5QwS0a3"/></label><button className="nb on" type="submit">Look up</button></form>
    {id&&<Load path={`/api/cheat/game?game_id=${id}`}>{g=><T cols={[{key:'side',label:'Side'},{key:'category',label:'Category'},{key:'rating_band',label:'Band'},{key:'elo',label:'Elo',type:'integer'},{key:'z_cv',label:'z_cv',type:'number'},{key:'acpl',label:'ACPL',type:'number'},{key:'match_rate',label:'Match rate',type:'percent'},{key:'timing_pct',label:'Timing pctile',type:'percent'},{key:'quality_pct',label:'Quality pctile',type:'percent'},{key:'score',label:'Score',type:'number'},{key:'signal',label:'Signal'}]} rows={g.rows}/>}</Load>}</P>}

const PG={schema:Schema,lake:Lake,explore:Explore,method:Method,overview:Overview,olap:Olap,mining:Mining,clusters:Clusters,rules:Rules,cheat:Cheat};
export default function App(){
  const [pg,setPg]=useState(location.hash.slice(2)||'overview');
  useEffect(()=>{const h=()=>{setPg(location.hash.slice(2)||'overview');scrollTo(0,0)};addEventListener('hashchange',h);
    let raf;const s=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(()=>document.documentElement.style.setProperty('--sy',scrollY))};addEventListener('scroll',s,{passive:true});
    return()=>{removeEventListener('hashchange',h);removeEventListener('scroll',s)}},[]);
  const C=PG[pg]||Overview,cur=NAV.find(n=>n[0]===pg)||NAV[0];
  return <><div className="bg"><i style={{'--p':.12}}/><i style={{'--p':.28}}/><i style={{'--p':.2}}/></div>
    <aside><a className="logo" href="#/overview">Chess<br/>Warehouse</a><nav>{NAV.map(n=><a key={n[0]} href={'#/'+n[0]} className={n[0]===cur[0]?'on':''}>{n[1]}</a>)}</nav></aside>
    <main key={pg}><header className="hero"><div className="ghost" style={{'--p':.35}}>{cur[1].split(' ')[0]}</div><span className="tagm">{cur[2]}</span><h1 style={{'--p':-.12}}>{cur[1]}</h1></header>
      <C/><footer>Data: Lichess standard rated games, Jan 2013 to Feb 2018 (60 of 62 months). Sample-weighted estimates.</footer></main></>}

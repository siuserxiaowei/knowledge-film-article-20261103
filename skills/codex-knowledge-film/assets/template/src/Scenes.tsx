import type {FilmScene, Theme} from './types';

// Register each newly implemented scene here. The preview guard rejects a
// custom/unknown scene until its dedicated drawing has actually been added.
export const SUPPORTED_KINDS = ['title','queue','budget','comparison','process'];

const clamp = (x:number) => Math.max(0,Math.min(1,x));
const ease = (x:number) => {const a=clamp(x);return a*a*(3-2*a);};
const str = (v:unknown, fallback='') => typeof v==='string' ? v : fallback;
const numbers = (v:unknown, fallback:number[]) => Array.isArray(v) ? v.map(Number).filter(Number.isFinite) : fallback;
const labels = (v:unknown, fallback:string[]) => Array.isArray(v) ? v.map(String) : fallback;

const Person = ({x,y,scale=1,color,opacity=1,walk=0}:{x:number;y:number;scale?:number;color:string;opacity?:number;walk?:number}) => <g transform={`translate(${x},${y}) scale(${scale})`} fill={color} opacity={opacity}>
  <circle cy={-68} r={12}/>
  <path d="M-13-49 Q0-58 13-49 L18-10 Q0-1-18-10Z"/>
  <path d={`M-8-8 L${-11-walk*5} 25 M8-8 L${11+walk*5} 25`} stroke={color} strokeWidth={8} strokeLinecap="round" fill="none"/>
  <path d={`M-13-42 L${-24+walk*4}-12 M13-42 L${24-walk*4}-12`} stroke={color} strokeWidth={7} strokeLinecap="round" fill="none"/>
</g>;

const Queue = ({scene,t,p,theme}:{scene:FilmScene;t:number;p:number;theme:Theme}) => {
  const visual=scene.visual??{};
  const mode=str(visual.mode,'ordered');
  const ordered=mode==='ordered';
  const blocked=mode==='blocked';
  const count=Math.max(3,Math.min(12,Number(visual.count)||8));
  const text=labels(visual.labels,['等候的人','出口']);
  return <svg viewBox="0 0 1920 1080" width="100%" height="100%" role="img" aria-label={ordered?'一列人依次通过出口，通道保持畅通':'人群挤向同一个出口，互相阻挡'}>
    <path d="M210 761H1730" stroke={theme.accent} strokeWidth={2} opacity={.35}/>
    <path d="M1400 375H1610V760H1400Z" fill="none" stroke={theme.accent} strokeWidth={6}/>
    <path d="M1420 395H1590V760H1420Z" fill={theme.accent} opacity={ordered?.09:.04}/>
    <text x={1505} y={350} fill={theme.accent} textAnchor="middle" fontSize={34} letterSpacing={7}>出口</text>
    <path d="M1530 560H1680m-30-20 30 20-30 20" fill="none" stroke={theme.accent} strokeWidth={4} opacity={ordered?.8:.2}/>
    {ordered && <>
      <path d="M250 610H1390 M250 795H1390" stroke={theme.accent} opacity={.18} strokeWidth={2} strokeDasharray="10 15"/>
      {Array.from({length:9},(_,i)=><path key={i} d={`M${290+i*115} 730h40m-12-9 12 9-12 9`} fill="none" stroke={theme.accent} opacity={.14+.17*(.5+.5*Math.sin(t*2-i))} strokeWidth={2}/>)}
    </>}
    {Array.from({length:count},(_,i)=>{
      const phase=(t*.075+i/count)%1;
      const orderX=245+phase*1300;
      const clusterX=1020+(i%4)*83+(blocked?35:0)*ease(p*3)+Math.sin(t*2+i)*7;
      const clusterY=650+Math.floor(i/4)*57+Math.cos(t*1.7+i)*5;
      return <Person key={i} x={ordered?orderX:clusterX} y={ordered?717:clusterY} scale={ordered?1.1:.98}
        color={ordered?theme.foreground:(i%3===0?theme.danger:theme.foreground)}
        opacity={ordered?Math.min(1,(1-phase)*8):.82} walk={Math.sin(t*(ordered?5:1.7)+i)}/>;
    })}
    {!ordered && <>
      <path d="M720 550q140 0 260 85" stroke={theme.danger} strokeWidth={3} fill="none" opacity={.5}/>
      <path d="M954 612l26 23-37-1" stroke={theme.danger} strokeWidth={3} fill="none" opacity={.5}/>
      <text x={590} y={520} fill={theme.danger} fontSize={32} textAnchor="middle">{text[0]}</text>
      <text x={1470} y={840} fill={theme.danger} fontSize={28} textAnchor="middle">{text[1]}</text>
    </>}
    {ordered && <>
      <text x={640} y={845} fill={theme.foreground} opacity={.65} fontSize={30} textAnchor="middle">{text[0]}</text>
      <text x={1505} y={840} fill={theme.accent} fontSize={30} textAnchor="middle">{text[1]}</text>
    </>}
  </svg>;
};

const Budget = ({scene,t,p,theme}:{scene:FilmScene;t:number;p:number;theme:Theme}) => {
  const visual=scene.visual??{};
  const focused=str(visual.mode)==='focused';
  const switching=str(visual.mode)==='switching';
  const text=labels(visual.labels,['书','手机']);
  const values=numbers(visual.values,[70,30]);
  const pageTurn=ease((p-.45)*3);
  return <svg viewBox="0 0 1920 1080" width="100%" height="100%" role="img" aria-label={focused?'桌上的书继续展开阅读，手机通知保持安静':'桌上打开的书和亮起通知的手机分走注意力'}>
    <ellipse cx={945} cy={818} rx={650} ry={50} fill="#000" opacity={.22}/>
    <path d="M260 725 1580 725 1700 810 180 810Z" fill={theme.accent} opacity={.12}/>
    <path d="M180 810H1700M320 810V865M1570 810V865" stroke={theme.accent} strokeWidth={3} opacity={.4}/>
    <g transform="translate(400,445)">
      <path d="M0 0Q145-34 290 0V280Q145 245 0 280Z" fill={theme.foreground} opacity={.92}/>
      <path d="M290 0Q435-34 580 0V280Q435 245 290 280Z" fill={theme.foreground} opacity={.82}/>
      <path d="M290 0V280" stroke={theme.background} opacity={.3} strokeWidth={3}/>
      {Array.from({length:7},(_,i)=><g key={i} stroke={theme.background} opacity={.3} strokeWidth={3} fill="none">
        <path d={`M35 ${45+i*27}Q145 ${25+i*27} 255 ${45+i*27}`}/>
        <path d={`M325 ${45+i*27}Q435 ${25+i*27} 545 ${45+i*27}`}/>
      </g>)}
      {focused && <path d={`M35 128Q145 108 ${35+220*ease(p*2)} ${128-20*Math.sin(ease(p*2)*Math.PI)}`} stroke={theme.accent} strokeWidth={11} opacity={.65} fill="none"/>}
      {focused && <path d={`M290 0Q${290-200*pageTurn} ${-40-40*pageTurn} ${290-260*pageTurn} ${280-10*pageTurn}Q${290-90*pageTurn} 250 290 280Z`} fill={theme.foreground} opacity={pageTurn<.95?.32:0}/>} 
    </g>
    <g transform={`translate(1280,${focused?450:450+Math.sin(t*10)*1.5}) rotate(${focused?-7:Math.sin(t*7)*1.4})`}>
      <rect width={165} height={283} rx={23} fill={theme.background} stroke={theme.accent} strokeWidth={4}/>
      <rect x={11} y={13} width={143} height={250} rx={14} fill={focused?theme.accent:theme.foreground} opacity={focused?.04:.13}/>
      <rect x={57} y={8} width={50} height={5} rx={3} fill={theme.accent} opacity={.6}/>
      <circle cx={82} cy={273} r={4} fill={theme.accent} opacity={.5}/>
      {!focused && Array.from({length:3},(_,i)=>{
        const pulse=.45+.4*(.5+.5*Math.sin(t*2-i));
        return <g key={i} transform={`translate(22,${50+i*58})`} opacity={pulse}>
          <rect width={122} height={40} rx={6} fill={i===0?theme.danger:theme.accent}/>
          <circle cx={17} cy={18} r={7} fill={theme.background} opacity={.6}/>
          <path d="M33 13H107M33 23H84" stroke={theme.background} strokeWidth={3} opacity={.65}/>
        </g>;
      })}
      {focused && <><path d="m60 120 13 14 30-35" stroke={theme.accent} strokeWidth={5} fill="none"/><text x={82} y={180} textAnchor="middle" fontSize={19} fill={theme.accent}>稍后再看</text></>}
    </g>
    {Array.from({length:9},(_,i)=>{
      const phase=(t*.22+i*.11)%1;
      const toPhone=!focused&&(i%2===0||switching);
      const x=960+(toPhone?350:-230)*phase;
      const y=350+110*phase-70*Math.sin(phase*Math.PI);
      return <circle key={i} cx={x} cy={y} r={5} fill={toPhone?theme.danger:theme.accent} opacity={.5*Math.sin(phase*Math.PI)}/>;
    })}
    <text x={690} y={850} textAnchor="middle" fontSize={28} fill={theme.foreground} opacity={.8}>{text[0]}</text>
    <text x={1360} y={850} textAnchor="middle" fontSize={28} fill={focused?theme.accent:theme.danger}>{text[1]}</text>
    <g transform="translate(590,320)">
      {Array.from({length:10},(_,i)=><rect key={i} x={i*76} width={58} height={16} rx={4} fill={i<Math.round((values[0]??70)/10)?theme.accent:theme.danger} opacity={.35+.3*ease(p*2)}/>)}
      <text x={350} y={-25} textAnchor="middle" fontSize={20} fill={theme.foreground} opacity={.5}>注意力预算 · 示意</text>
    </g>
  </svg>;
};

const Comparison = ({scene,p,theme}:{scene:FilmScene;p:number;theme:Theme}) => {
  const visual=scene.visual??{};
  const names=labels(visual.labels,['方案一','方案二']);
  const vals=numbers(visual.values,[60,85]);
  return <svg viewBox="0 0 1920 1080" width="100%" height="100%" role="img" aria-label="两个方案的可视比较，数值为示意">
    {[0,1].map(i=><g key={i} transform={`translate(${560+i*800},780)`}>
      <rect x={-85} y={-340*ease(p*2)*(vals[i]??50)/100} width={170} height={340*ease(p*2)*(vals[i]??50)/100} rx={5} fill={i?theme.accent:theme.danger} opacity={.8}/>
      <text y={-390} textAnchor="middle" fill={theme.foreground} fontSize={45}>{names[i]}</text>
      <text y={60} textAnchor="middle" fill={theme.foreground} fontSize={28}>{Math.round((vals[i]??50)*ease(p*2))} · 示意</text>
    </g>)}
  </svg>;
};

const Process = ({scene,p,theme}:{scene:FilmScene;p:number;theme:Theme}) => {
  const names=labels(scene.visual?.labels,['发生了什么','怎样改变','得到什么']);
  return <svg viewBox="0 0 1920 1080" width="100%" height="100%" role="img" aria-label={names.join('，然后')}>
    <path d="M360 560H1570" stroke={theme.accent} strokeWidth={2} opacity={.3}/>
    {names.slice(0,4).map((name,i)=>{
      const x=340+i*1240/Math.max(1,Math.min(4,names.length)-1);
      const on=ease(p*names.length-i*.65);
      return <g key={i} opacity={.25+.75*on}>
        <circle cx={x} cy={560} r={68} fill={theme.background} stroke={theme.accent} strokeWidth={3}/>
        <text x={x} y={576} textAnchor="middle" fontFamily="FilmDisplay" fontSize={48} fill={theme.accent}>{i+1}</text>
        <text x={x} y={710} textAnchor="middle" fontSize={32} fill={theme.foreground}>{name}</text>
      </g>;
    })}
  </svg>;
};

export const SceneArt = ({scene,t,duration,theme}:{scene:FilmScene;t:number;duration:number;theme:Theme}) => {
  const p=clamp(t/Math.max(.1,duration));
  if(scene.kind==='queue') return <Queue scene={scene} t={t} p={p} theme={theme}/>;
  if(scene.kind==='budget') return <Budget scene={scene} t={t} p={p} theme={theme}/>;
  if(scene.kind==='comparison') return <Comparison scene={scene} p={p} theme={theme}/>;
  if(scene.kind==='process') return <Process scene={scene} p={p} theme={theme}/>;
  if(scene.kind==='title') return <div style={{position:'absolute',inset:0,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',textAlign:'center',padding:'0 150px',gap:35}}>
    <div style={{fontSize:28,letterSpacing:8,color:theme.accent,opacity:.65}}>{str(scene.visual?.eyebrow,'KNOWLEDGE IN MOTION')}</div>
    <div style={{fontSize:78,lineHeight:1.5,color:theme.foreground,maxWidth:1500}}>{scene.title}</div>
    <div style={{width:460,height:2,background:theme.accent,opacity:.45}}/>
    <div style={{fontSize:25,color:theme.foreground,opacity:.6}}>{str(scene.visual?.note)}</div>
  </div>;
  return <div style={{position:'absolute',inset:0,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:30,color:theme.danger,textAlign:'center'}}>
    <div style={{fontSize:46}}>此场景需要专用画面</div>
    <div style={{fontSize:28}}>请在 src/Scenes.tsx 实现 {scene.kind}，再导出成片。</div>
  </div>;
};

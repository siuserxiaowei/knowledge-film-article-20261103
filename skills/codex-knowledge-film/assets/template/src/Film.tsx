import {useEffect,useState} from 'react';
import {loadFont} from '@remotion/fonts';
import {Audio} from '@remotion/media';
import {AbsoluteFill,Html5Audio,Sequence,cancelRender,continueRender,delayRender,interpolate,staticFile,useCurrentFrame,useRemotionEnvironment,useVideoConfig} from 'remotion';
import spec from '../content/film.json';
import timelineJson from './generated/timeline.json';
import type {FilmScene,FilmTimeline,Theme} from './types';
import {SceneArt,SUPPORTED_KINDS} from './Scenes';

const timeline=timelineJson as FilmTimeline;
const canonical=(value:unknown):unknown=>Array.isArray(value)?value.map(canonical):value!==null&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical((value as Record<string,unknown>)[key])])):value;
const serializedSpec=JSON.stringify(canonical(spec));
const registeredKinds=SUPPORTED_KINDS.join(',');
let fontPromise:Promise<unknown>|null=null;
const fonts=()=>fontPromise??=Promise.all([
  loadFont({family:'FilmSerif',url:staticFile('fonts/NotoSerifSC.ttf'),weight:'200 900'}),
  loadFont({family:'FilmDisplay',url:staticFile('fonts/CormorantGaramond.ttf'),weight:'300 700'}),
]);

const SceneLayer=({scene,theme}:{scene:FilmScene;theme:Theme})=>{
  const frame=useCurrentFrame();
  const {fps}=useVideoConfig();
  const t=frame/fps,duration=scene.durationInFrames/fps;
  const edge=Math.min(.3,duration/4);
  const opacity=interpolate(t,[0,edge,Math.max(edge,duration-edge),duration],[0,1,1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  return <AbsoluteFill style={{opacity}}>
    {scene.kind!=='title'&&<div style={{position:'absolute',top:90,left:140,right:140,textAlign:'center',color:theme.foreground,fontSize:53,lineHeight:1.4,letterSpacing:3}}>{scene.title}</div>}
    <SceneArt scene={scene} t={t} duration={duration} theme={theme}/>
  </AbsoluteFill>;
};

export const Film=()=>{
  const frame=useCurrentFrame();
  const {fps,width,height}=useVideoConfig();
  const {isRendering}=useRemotionEnvironment();
  const [handle]=useState(()=>delayRender('Load film fonts and verify prepared content'));
  const [checked,setChecked]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    setChecked(false);
    setError('');
    const verify=async()=>{
      await fonts();
      if(!timeline.ready) throw new Error('尚未准备时间轴。请先运行 npm run prepare:film。');
      const bytes=new TextEncoder().encode(serializedSpec);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
      if(digest!==timeline.specHash) throw new Error('文稿或声音设置已改变。请重新准备时间轴，不要使用旧配音。');
      const missing=timeline.scenes.find(scene=>!SUPPORTED_KINDS.includes(scene.kind));
      if(missing) throw new Error(`场景 ${missing.id} 尚未实现专用画面。请在 src/Scenes.tsx 完成 ${missing.kind} 并登记 SUPPORTED_KINDS。`);
    };
    verify().then(()=>{if(active)setChecked(true);continueRender(handle);}).catch((e:unknown)=>{
      const message=e instanceof Error?e.message:String(e);
      if(active){setError(message);setChecked(true);}
      if(isRendering) cancelRender(e); else continueRender(handle);
    });
    return()=>{active=false;};
  },[handle,isRendering,serializedSpec,registeredKinds,timeline.ready,timeline.specHash]);
  const theme=timeline.theme;
  const t=frame/fps;
  const caption=timeline.captions.find(c=>frame>=c.startFrame&&frame<c.endFrame);
  const audioSrc=timeline.audioSrc?staticFile(timeline.audioSrc):null;
  const scale=Math.min(width/1920,height/1080);
  return <AbsoluteFill style={{background:theme.background,fontFamily:'FilmSerif',overflow:'hidden',color:theme.foreground}}>
    <div style={{position:'absolute',width:1920,height:1080,left:(width-1920*scale)/2,top:(height-1080*scale)/2,transform:`scale(${scale})`,transformOrigin:'top left'}}>
    <AbsoluteFill style={{background:`radial-gradient(ellipse at 50% 45%, ${theme.accent}1C, transparent 70%)`}}/>
    {!checked?null:error?<AbsoluteFill style={{alignItems:'center',justifyContent:'center',textAlign:'center',gap:25,padding:150}}>
      <div style={{fontSize:58,color:theme.accent}}>知识短片工坊</div>
      <div style={{fontSize:34,lineHeight:1.7}}>{error}</div>
    </AbsoluteFill>:<>
      {timeline.scenes.map(scene=><Sequence key={scene.id} name={scene.title} from={scene.startFrame} durationInFrames={scene.durationInFrames}>
        <SceneLayer scene={scene} theme={theme}/>
      </Sequence>)}
      {caption&&<div style={{position:'absolute',left:100,right:100,top:932,fontSize:43,lineHeight:1.6,letterSpacing:1.8,textAlign:'center',color:theme.foreground,whiteSpace:'nowrap',opacity:Math.min(1,(t-caption.startSeconds)/.15,(caption.endSeconds-t)/.15),textShadow:'0 2px 12px #000'}}>{caption.text}</div>}
      <div style={{position:'absolute',right:100,bottom:40,fontSize:19,letterSpacing:3,color:theme.foreground,opacity:.4}}>机制示意</div>
      {audioSrc&&(isRendering?<Audio name={timeline.narrated?'旁白与配乐':'本地合成配乐'} src={audioSrc}/>:<Html5Audio name={timeline.narrated?'旁白与配乐':'本地合成配乐'} src={audioSrc} useWebAudioApi={false}/>)}
    </>}
    </div>
  </AbsoluteFill>;
};

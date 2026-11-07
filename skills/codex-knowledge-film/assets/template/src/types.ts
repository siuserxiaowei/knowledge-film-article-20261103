export type Theme = {background:string;foreground:string;accent:string;danger:string};
export type FilmScene = {
  id:string;kind:string;title:string;visual?:Record<string,unknown>;
  startSeconds:number;endSeconds:number;startFrame:number;durationInFrames:number;
};
export type FilmCaption = {
  id:string;sceneId:string;text:string;startSeconds:number;endSeconds:number;
  startFrame:number;endFrame:number;
};
export type FilmTimeline = {
  version:number;ready:boolean;specHash:string;title:string;
  fps:number;width:number;height:number;durationSeconds:number;durationInFrames:number;
  audioSrc:string|null;narrated:boolean;provenance:unknown;theme:Theme;
  scenes:FilmScene[];captions:FilmCaption[];
};

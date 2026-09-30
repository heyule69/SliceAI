export type EditOptions = { pace:'light'|'standard'|'tight'; cleanup:string[]; speech:string[]; subtitles:'none'|'basic'|'checked'; music:'original'|'reduce'; normalize:boolean };
export const defaults = ():EditOptions => ({pace:'standard',cleanup:['repeats','offtopic','greetings'],speech:['retakes','silence'],subtitles:'checked',music:'original',normalize:true});
export const questions = [
 {key:'pace',title:'想剪得多紧凑？',hint:'保留完整事情，不强行限制时长。',multi:false,options:[
  ['light','轻度整理','保留大部分原话和聊天节奏'],['standard','标准精简','删冗余，保留故事与反应','推荐'],['tight','紧凑利落','减少枝节，突出关键过程']]},
 {key:'cleanup',title:'哪些内容可以删掉？',hint:'可多选，也可以全部保留。',multi:true,options:[
  ['repeats','重复表达','同一个意思反复讲述'],['offtopic','无关闲聊','保留与主事件有关的铺垫和后续'],['greetings','例行招呼与谢礼','有笑点或影响故事的互动保留']]},
 {key:'speech',title:'说话和停顿怎么整理？',hint:'笑声、情绪反应和必要停顿默认保留。',multi:true,options:[
  ['fillers','无意义的语气词','仅删除能独立定位的“嗯、那个”等'],['retakes','口吃和重说','保留说完整的那一次'],['silence','缩短长空白','只压缩检测到的长静音，避免误删反应']]},
 {key:'subtitles',title:'要加字幕吗？',hint:'字幕可在预览后改字、调时间。',multi:false,options:[
  ['checked','加字幕，并核对','按片段原声整理字幕，不确定的文字标记待核对','推荐'],['basic','直接添加字幕','使用已有转写，生成更快'],['none','不加字幕','保留干净画面']]},
 {key:'music',title:'声音需要处理吗？',hint:'选择后直接处理，也可以先试听效果。',multi:false,options:[
  ['original','保留原声','保留主播和背景声音','推荐'],['reduce','降低背景音乐','减弱背景音乐，优先保留主播声音']]}
] as const;
export function summary(options:EditOptions):{title:string;value:string}[] {
 return [...questions.map(q=>{const value=options[q.key];return {title:q.title,value:q.options.filter(o=>Array.isArray(value)?value.includes(o[0]):value===o[0]).map(o=>o[1]).join('、')||'全部保留'};}),{title:'音量',value:options.normalize?'均衡音量':'保持原音量'}];
}

/** Keep interactive nodes mounted while frequent worker progress events arrive. */
const rendered = new WeakMap<HTMLElement,string>();
export function patchHTML(element:HTMLElement,html:string){
 if(rendered.get(element)!==html){element.innerHTML=html;rendered.set(element,html);}
}
export function reconcileTaskRows(container:HTMLElement,rows:{id:string;html:string}[],empty:string){
 const existing=new Map([...container.querySelectorAll<HTMLElement>(':scope > [data-task-row]')].map(el=>[el.dataset.taskRow!,el]));
 if(!rows.length){patchHTML(container,empty);return;}
 if(!existing.size)container.replaceChildren();
 const keep=new Set(rows.map(row=>row.id));
 for(const [id,node] of existing)if(!keep.has(id))node.remove();
 rows.forEach((row,index)=>{
  const template=document.createElement('template');template.innerHTML=row.html;
  const fresh=template.content.firstElementChild as HTMLElement;fresh.dataset.taskRow=row.id;
  let node=existing.get(row.id);
  if(!node){node=fresh;}
  else for(const selector of ['.task-source','.task-result','.task-status','.task-action','.task-delete']){
   const target=node.querySelector<HTMLElement>(selector)!,source=fresh.querySelector<HTMLElement>(selector)!;
   target.className=source.className;patchHTML(target,source.innerHTML);
  }
  if(container.children[index]!==node)container.insertBefore(node,container.children[index]||null);
 });
 rendered.delete(container);
}

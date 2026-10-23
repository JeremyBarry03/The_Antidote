const clamp=(value,min,max)=>Math.max(min,Math.min(Math.max(min,max),value));
const inside=(point,box,pad=0)=>point.x>=box.x-pad&&point.x<=box.x+box.width+pad
  &&point.y>=box.y-pad&&point.y<=box.y+box.height+pad;

// Prefer a diagonal behind the bow, then choose the side with clear map space.
export function placeCallout({anchor, width, height, viewport, heading=0, obstacles=[],avoid=[],preferredSide}) {
  const radians=heading*Math.PI/180,forward={x:Math.sin(radians),y:-Math.cos(radians)};
  const margin=8,gap=14;
  const candidates=[[-1,-1],[1,-1],[-1,1],[1,1]].flatMap(([dx,dy])=>[[0,0],[0,height+10],[width+10,0]].map(([ox,oy])=>{
    const rawX=dx>0?anchor.x+gap+ox:anchor.x-width-gap-ox;
    const rawY=dy>0?anchor.y+gap+oy:anchor.y-height-gap-oy;
    const x=clamp(rawX,margin,viewport.width-width-margin);
    const y=clamp(rawY,margin,viewport.height-height-52);
    const center={x:x+width/2,y:y+height/2},distance=Math.hypot(center.x-anchor.x,center.y-anchor.y)||1;
    const direction={x:(center.x-anchor.x)/distance,y:(center.y-anchor.y)/distance};
    const box={x,y,width,height};
    const side=(center.y<anchor.y?'n':'s')+(center.x<anchor.x?'w':'e');
    const overlap=avoid.reduce((cost,other)=>{
      const intersection=Math.max(0,Math.min(x+width+6,other.x+other.width)-Math.max(x-6,other.x))
        *Math.max(0,Math.min(y+height+6,other.y+other.height)-Math.max(y-6,other.y));
      return cost+(intersection?5000+intersection*10:0);
    },0);
    const score=(Math.abs(x-rawX)+Math.abs(y-rawY))*3+(ox+oy)*.5+overlap
      +30*(direction.x*forward.x+direction.y*forward.y)
      +(preferredSide&&side!==preferredSide?12:0)
      +(inside(anchor,box,12)?100000:0)
      +obstacles.reduce((cost,p)=>cost+(inside(p,box,12)?300:0),0);
    return {x,y,width,height,side,score,anchor};
  }));
  return candidates.sort((a,b)=>a.score-b.score)[0];
}

const overlaps=(a,b,gap=5)=>a.x<b.x+b.width+gap&&a.x+a.width+gap>b.x
  &&a.y<b.y+b.height+gap&&a.y+a.height+gap>b.y;

// Assign a side once. Keep the vessel-relative offset, and only push a label
// when it actually collides. Older labels retain priority over newer arrivals.
// Unlike rescoring all four sides each frame, the chosen stack offset persists.
export class StableCalloutLayout {
  slots=new Map();
  viewportKey='';

  clear(){this.slots.clear();this.viewportKey='';}

  layout(items,viewport){
    const key=`${Math.round(viewport.width)}:${Math.round(viewport.height)}`;
    if(key!==this.viewportKey){this.clear();this.viewportKey=key;}
    const current=new Map(items.map(item=>[item.id,item]));
    for(const id of this.slots.keys())if(!current.has(id))this.slots.delete(id);
    for(const item of items)if(!this.slots.has(item.id))this.slots.set(item.id,null);
    const placed=[],results=new Map(),margin=8;
    const points=items.map(item=>item.anchor).concat({x:viewport.width-35,y:20});
    const icons=points.map(p=>({x:p.x-10,y:p.y-10,width:20,height:20}));
    for(const [id,saved] of this.slots){
      const item=current.get(id),{anchor,width,height}=item;
      let slot=saved;
      if(!slot){
        const seed=placeCallout({...item,viewport,obstacles:points,avoid:placed});
        slot={dx:seed.x-anchor.x,dy:seed.y-anchor.y,side:seed.side};
        this.slots.set(id,slot);
      }
      const maxX=viewport.width-width-margin,maxY=viewport.height-height-52;
      const desired={x:clamp(anchor.x+slot.dx,margin,maxX),y:clamp(anchor.y+slot.dy,margin,maxY),width,height};
      const blocked=[...placed,...icons];
      let box=desired;
      if(blocked.some(other=>overlaps(box,other))){
        // First try a vertical stack at the existing x. Keep that new offset
        // even after the conflict clears, rather than snapping to the old side.
        const ys=[desired.y,margin,maxY,...blocked.flatMap(b=>[b.y-height-6,b.y+b.height+6])];
        const xs=[desired.x,margin,maxX,...placed.flatMap(b=>[b.x-width-6,b.x+b.width+6])];
        let options=[];
        for(const x of xs)for(const y of ys){
          const candidate={x:clamp(x,margin,maxX),y:clamp(y,margin,maxY),width,height};
          if(blocked.some(other=>overlaps(candidate,other)))continue;
          const distance=Math.abs(candidate.y-desired.y)+Math.abs(candidate.x-desired.x)*4;
          options.push({...candidate,distance});
        }
        options.sort((a,b)=>a.distance-b.distance||a.y-b.y||a.x-b.x);
        if(options.length){box=options[0];slot.dx=box.x-anchor.x;slot.dy=box.y-anchor.y;}
      }
      const side=(box.y+height/2<anchor.y?'n':'s')+(box.x+width/2<anchor.x?'w':'e');
      const result={...box,anchor,side,slot:slot.side};
      results.set(id,result);placed.push(result);
    }
    return results;
  }
}

// A thin leader keeps a displaced label attached without a large filled wedge.
export function calloutPath(box) {
  const {x,y,width:w,height:h,anchor}=box,r=4;
  const end=anchor.y<y?{x:clamp(anchor.x,x+r,x+w-r),y}
    :anchor.y>y+h?{x:clamp(anchor.x,x+r,x+w-r),y:y+h}
    :{x:anchor.x<x?x:x+w,y:clamp(anchor.y,y+r,y+h-r)};
  const distance=Math.hypot(end.x-anchor.x,end.y-anchor.y)||1;
  const tip={x:anchor.x+(end.x-anchor.x)/distance*9,y:anchor.y+(end.y-anchor.y)/distance*9};
  const path=`M${tip.x} ${tip.y} L${end.x} ${end.y} M${x+r} ${y} H${x+w-r} Q${x+w} ${y} ${x+w} ${y+r} V${y+h-r} Q${x+w} ${y+h} ${x+w-r} ${y+h} H${x+r} Q${x} ${y+h} ${x} ${y+h-r} V${y+r} Q${x} ${y} ${x+r} ${y} Z`;
  return {path,tip};
}

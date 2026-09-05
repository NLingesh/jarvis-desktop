import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import './OrbEngine.css';

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing' | 'notification' | 'offline' | 'error' | 'working' | 'panel-open';
export interface OrbEngineProps {
  state: OrbState; rms?: number; onToggleTalk?: () => void; onClick?: () => void;
  onExpandPanel?: () => void; onSingleClick?: () => void;
  onQuickAction?: (action: 'talk' | 'chat' | 'settings') => void;
  onDragMove?: (dx: number, dy: number) => void; onDragEnd?: () => void;
  onContextMenu?: () => void; quickActionsOpen?: boolean;
  onCloseQuickActions?: () => void; className?: string; style?: React.CSSProperties; wakePulse?: boolean;
}
export const STATE_COLORS: Record<OrbState, { core: string; glow: string; particle: string }> = {
  idle: { core: '#62f6e0', glow: 'rgba(0,220,255,.45)', particle: '#9ffff5' },
  listening: { core: '#00ffff', glow: 'rgba(0,255,255,.7)', particle: '#bfffff' },
  thinking: { core: '#ff9c55', glow: 'rgba(255,84,32,.65)', particle: '#ffd0a8' },
  speaking: { core: '#ff805d', glow: 'rgba(255,65,35,.65)', particle: '#ffe0c2' },
  processing: { core: '#ffb020', glow: 'rgba(255,176,32,.5)', particle: '#ffe0a0' },
  notification: { core: '#62f6e0', glow: 'rgba(0,220,255,.5)', particle: '#bfffff' },
  offline: { core: '#596579', glow: 'rgba(70,90,110,.2)', particle: '#778899' },
  error: { core: '#ff4466', glow: 'rgba(255,68,102,.5)', particle: '#ffb0bd' },
  working: { core: '#ffb020', glow: 'rgba(255,176,32,.5)', particle: '#ffe0a0' },
  'panel-open': { core: '#62f6e0', glow: 'rgba(0,220,255,.3)', particle: '#bfffff' },
};
const QUICK_ACTIONS = [{ id: 'talk' as const, label: 'Talk', icon: '🎙️', angle: 0 }, { id: 'chat' as const, label: 'Chat', icon: '💬', angle: 90 }, { id: 'settings' as const, label: 'Settings', icon: '⚙️', angle: 180 }];

const OrbEngine: React.FC<OrbEngineProps> = ({ state, rms = 0, onToggleTalk, onClick, onExpandPanel, onSingleClick, onQuickAction, onDragMove, onDragEnd, onContextMenu, quickActionsOpen = false, onCloseQuickActions, className, style }) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{ renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; core: THREE.Mesh; aura: THREE.Mesh; points: THREE.Points; lines: THREE.LineSegments; rings: THREE.Mesh[]; nodes: THREE.Vector3[] } | null>(null);
  const stateRef = useRef(state); stateRef.current = state;
  const rmsRef = useRef(rms); rmsRef.current = rms;
  const frameRef = useRef(0);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(false);
  const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const isPanelOpen = state === 'panel-open';
  const label = useMemo(() => ({ idle: 'JARVIS is idle', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', processing: 'Processing', notification: 'New notification', offline: 'Offline', error: 'Connection error', working: 'Working', 'panel-open': 'Panel open' }[state]), [state]);

  useEffect(() => {
    const host = hostRef.current; if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' }); } catch { return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5)); renderer.setClearColor(0, 0); host.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(42, 1, .1, 100); camera.position.z = 4.2;
    const group = new THREE.Group(); scene.add(group);
    const nodes: THREE.Vector3[] = []; const count = 72;
    for (let i=0;i<count;i++) { const y=1-(i/(count-1))*2, r=Math.sqrt(1-y*y), a=i*2.39996; nodes.push(new THREE.Vector3(Math.cos(a)*r, y, Math.sin(a)*r)); }
    const positions = new Float32Array(count*3); nodes.forEach((n,i)=>positions.set([n.x,n.y,n.z],i*3));
    const pointMat = new THREE.PointsMaterial({ color: 0x9ffff5, size: .065, transparent: true, opacity: .9, blending: THREE.AdditiveBlending, depthWrite: false });
    const points = new THREE.Points(new THREE.BufferGeometry(), pointMat); points.geometry.setAttribute('position', new THREE.BufferAttribute(positions,3)); group.add(points);
    const edge: number[] = []; nodes.forEach((a,i)=>nodes.forEach((b,j)=>{ if (j>i && a.distanceTo(b)<.48) edge.push(a.x,a.y,a.z,b.x,b.y,b.z); }));
    const lineMat = new THREE.LineBasicMaterial({ color: 0x37e8e0, transparent: true, opacity: .28, blending: THREE.AdditiveBlending, depthWrite: false });
    const lines = new THREE.LineSegments(new THREE.BufferGeometry(),lineMat); lines.geometry.setAttribute('position',new THREE.Float32BufferAttribute(edge,3)); group.add(lines);
    const core = new THREE.Mesh(new THREE.SphereGeometry(.48,32,32), new THREE.MeshBasicMaterial({ color: 0x45f5df, transparent:true, opacity:.72, blending:THREE.AdditiveBlending })); group.add(core);
    const aura = new THREE.Mesh(new THREE.SphereGeometry(.78,24,24), new THREE.MeshBasicMaterial({ color:0x00dfff, transparent:true, opacity:.1, blending:THREE.AdditiveBlending, depthWrite:false })); group.add(aura);
    const rings: THREE.Mesh[] = []; for(let i=0;i<2;i++){const ring=new THREE.Mesh(new THREE.TorusGeometry(.82+i*.12,.012,8,96),new THREE.MeshBasicMaterial({color:0xff815d,transparent:true,opacity:.55,blending:THREE.AdditiveBlending})); ring.rotation.x=i?1.1:.35; ring.visible=false; group.add(ring); rings.push(ring);}
    sceneRef.current={renderer,scene,camera,core,aura,points,lines,rings,nodes};
    const resize=()=>{const w=Math.max(host.clientWidth,1),h=Math.max(host.clientHeight,1);renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}; resize(); const ro=new ResizeObserver(resize); ro.observe(host);
    const animate=(time:number)=>{frameRef.current=requestAnimationFrame(animate); const s=stateRef.current, audio=Math.min(1,rmsRef.current*2.2), active=s==='listening'||s==='speaking'; const speed=reduced?0:s==='thinking'?1.5:active?.75:.22; group.rotation.y=time*.00025*speed; group.rotation.x=Math.sin(time*.0003)*.08; const pulse=1+Math.sin(time*.002)*.035+(s==='speaking'?audio*.22:0); core.scale.setScalar(pulse); aura.scale.setScalar(1+Math.sin(time*.0015)*.08+audio*.3); pointMat.size=.045+(active?.018:0)+audio*.035; pointMat.opacity=s==='offline'?.2:.65+audio*.35; lineMat.opacity=s==='offline'?.06:(s==='thinking'?.6:.25)+audio*.25; const hot=s==='thinking'||s==='speaking'||s==='processing'; rings.forEach((r,i)=>{r.visible=hot;r.rotation.z=time*.001*(i?-.8:1);(r.material as THREE.MeshBasicMaterial).opacity=hot?.6+audio*.3:.0;}); renderer.render(scene,camera);}; animate(0);
    return ()=>{cancelAnimationFrame(frameRef.current);ro.disconnect();renderer.dispose();host.removeChild(renderer.domElement);scene.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.LineSegments||o instanceof THREE.Points){o.geometry.dispose();(o.material as THREE.Material).dispose();}});sceneRef.current=null;};
  }, [reduced]);
  const click=useCallback((e:React.MouseEvent)=>{e.stopPropagation();if(!dragRef.current)(isPanelOpen?onClick:onSingleClick)?.();},[isPanelOpen,onClick,onSingleClick]);
  const down=useCallback((e:React.MouseEvent)=>{if(e.button!==0)return;const sx=e.clientX,sy=e.clientY;let moved=false;const move=(ev:MouseEvent)=>{const dx=ev.clientX-sx,dy=ev.clientY-sy;if(Math.abs(dx)>3||Math.abs(dy)>3){moved=true;dragRef.current=true;setDragging(true);onDragMove?.(dx,dy);}};const up=()=>{window.removeEventListener('mousemove',move);window.removeEventListener('mouseup',up);if(moved)onDragEnd?.();dragRef.current=false;setDragging(false);};window.addEventListener('mousemove',move);window.addEventListener('mouseup',up);},[onDragMove,onDragEnd]);
  const key=useCallback((e:React.KeyboardEvent)=>{if(e.key==='Enter')onExpandPanel?.();if(e.key===' ')onToggleTalk?.();if(e.key==='Escape')onCloseQuickActions?.();},[onExpandPanel,onToggleTalk,onCloseQuickActions]);
  return <div ref={hostRef} className={`orb-engine orb-state-${state} ${isPanelOpen?'panel-open ':''}${className||''}`} style={{width:isPanelOpen?'var(--orb-size-small)':'var(--orb-size)',height:isPanelOpen?'var(--orb-size-small)':'var(--orb-size)',transform:dragging?'scale(1.08)':undefined,...style}} onClick={click} onDoubleClick={e=>{e.stopPropagation();onExpandPanel?.();}} onMouseDown={down} onContextMenu={e=>{e.preventDefault();onContextMenu?.();}} onKeyDown={key} role="button" tabIndex={0} aria-label={label} aria-pressed={state==='listening'} title={label}>
    <div className="orb-core-glow" aria-hidden="true" /><span className="orb-wordmark" aria-hidden="true">JARVIS</span>{state==='notification'&&<div className="orb-badge" aria-label="Notification"/>}
    {quickActionsOpen&&onQuickAction&&<div className="orb-quick-actions" role="menu" aria-label="Quick actions">{QUICK_ACTIONS.map(a=><button key={a.id} className="orb-quick-action" style={{transform:`translate(${Math.cos(a.angle*Math.PI/180)*55}px,${Math.sin(a.angle*Math.PI/180)*55}px)`}} onClick={e=>{e.stopPropagation();onQuickAction(a.id)}} role="menuitem" aria-label={a.label}><span className="quick-action-icon">{a.icon}</span><span className="quick-action-label">{a.label}</span></button>)}</div>}
  </div>;
};
export default OrbEngine;

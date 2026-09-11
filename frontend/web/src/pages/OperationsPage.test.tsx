import {StrictMode, type ReactNode} from 'react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {apiFetch} from '../api/client';
import {OperationsPage as Fixed} from './OperationsPage';
vi.mock('../api/client',()=>({apiFetch:vi.fn(),apiFetchBlob:vi.fn()}));
vi.mock('../components/AppShell',()=>({AppShell:({children}:{children:ReactNode})=><div>{children}</div>}));
type Request={resolve:(v:unknown)=>void,reject:(e:Error)=>void,signal?:AbortSignal|null};
let requests:Request[];
let observing=false;
beforeEach(()=>{vi.useFakeTimers();requests=[];observing=false;vi.mocked(apiFetch).mockImplementation((path,init)=>{
 if(path!=="/api/mqtt/monitor" || !observing) return Promise.resolve(snapshot(0)) as ReturnType<typeof apiFetch>;
 return new Promise((resolve,reject)=>requests.push({resolve,reject,signal:init?.signal}));
});});
const mount=async(strict=false)=>{let view:ReturnType<typeof render>;await act(async()=>{view=render(strict?<StrictMode><Fixed/></StrictMode>:<Fixed/>);});observing=true;return view!;};
afterEach(()=>{cleanup();vi.useRealTimers();vi.resetAllMocks();});
const click=(name:string)=>fireEvent.click(screen.getByRole('button',{name}));
const snapshot=(n:number)=>({connected:true,client_id:'client',subscriptions:[],received_messages:n,reconnects:0,errors:0,buffer_capacity:100,recent_messages:[],recent_events:[],test_publish_enabled:false});
const count=()=>screen.getByText('Messages observed').parentElement!.querySelector('.summary-card__value')!.textContent;
const resolve=async(i:number,n:number)=>{await act(async()=>{requests[i].resolve(snapshot(n));});};
const reject=async(i:number)=>{await act(async()=>{requests[i].reject(new Error('late failure'));});};
const tick=async(ms:number)=>{await act(async()=>{vi.advanceTimersByTime(ms);});};

describe('patched component regression checks',()=>{
 it('starts only on request and serializes polls until settlement plus one second',async()=>{
  await mount();expect(requests).toHaveLength(0);click('Start listening');await tick(5000);expect(requests).toHaveLength(1);
  await resolve(0,100);await tick(999);expect(requests).toHaveLength(1);await tick(1);expect(requests).toHaveLength(2);
 });
 it('pause aborts request and ignores late success even if transport ignores abort',async()=>{
  await mount();click('Start listening');click('Pause display');expect(requests[0].signal?.aborted).toBe(true);
  await resolve(0,100);expect(count()).toBe('0');await tick(5000);expect(requests).toHaveLength(1);
 });
 it('pause ignores late failure',async()=>{
  await mount();click('Start listening');click('Pause display');await reject(0);
  expect(screen.queryByRole('alert')).toBeNull();await tick(5000);expect(requests).toHaveLength(1);
 });
 it('resume begins a new request and ignores the old paused response',async()=>{
  await mount();click('Start listening');click('Pause display');click('Resume display');expect(requests).toHaveLength(2);
  await resolve(1,200);await resolve(0,100);expect(count()).toBe('200');expect(requests[1].signal?.aborted).toBe(false);
 });
 it('stop/restart isolates old response from new lifetime',async()=>{
  await mount();click('Start listening');click('Stop listening');click('Start listening');
  await resolve(1,200);await resolve(0,100);expect(count()).toBe('200');expect(requests[0].signal?.aborted).toBe(true);
 });
 it('unmount aborts and late completion never schedules another poll',async()=>{
  const view=await mount();click('Start listening');view.unmount();expect(requests[0].signal?.aborted).toBe(true);
  await resolve(0,100);await tick(5000);expect(requests).toHaveLength(1);expect(vi.getTimerCount()).toBe(0);
 });
 it('live failure displays error then next successful poll clears it',async()=>{
  await mount();click('Start listening');await reject(0);expect(screen.getByRole('alert').textContent).toBe('late failure');
  await tick(1000);await resolve(1,200);expect(count()).toBe('200');expect(screen.queryByRole('alert')).toBeNull();
 });
 it('strict mode and stop clear scheduled timer',async()=>{
  await mount(true);click('Start listening');expect(requests).toHaveLength(1);await resolve(0,100);
  click('Stop listening');await tick(5000);expect(requests).toHaveLength(1);
 });
});

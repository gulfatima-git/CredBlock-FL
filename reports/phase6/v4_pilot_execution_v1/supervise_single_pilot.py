"""One authorized evaluator launch; external read-only process monitoring.

No retries, stop signals, evaluator imports, scientific instrumentation or changes.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,os,subprocess,sys,time,ctypes
from ctypes import wintypes
import psutil
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
def now():return datetime.now(timezone(timedelta(hours=5))).isoformat()
def save(name,d):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(d,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
class FT(ctypes.Structure):_fields_=[('low',wintypes.DWORD),('high',wintypes.DWORD)]
k.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(FT)]*4;k.GetProcessTimes.restype=wintypes.BOOL
k.CloseHandle.argtypes=[wintypes.HANDLE]
def cpu(handle):
    c,e,kt,ut=FT(),FT(),FT(),FT()
    if not k.GetProcessTimes(handle,ctypes.byref(c),ctypes.byref(e),ctypes.byref(kt),ctypes.byref(ut)):return None
    return dict(kernel_seconds=((kt.high<<32)|kt.low)/1e7,user_seconds=((ut.high<<32)|ut.low)/1e7,creation_ticks=(c.high<<32)|c.low,exit_ticks=(e.high<<32)|e.low)
def main():
    cfg=json.loads((OUT/'launch_preflight.json').read_bytes());assert cfg['status']=='PASS_ESSENTIAL_GUARDS_APPROVED_SINGLE_PILOT'
    grant=json.loads(Path(cfg['approval_path']).read_bytes());assert grant['authorized_variants']==['CFV1_RA_CS_005_SEED1003_TEST'] and grant['execution_authorized'] is True
    assert not Path(cfg['output_root']).exists()
    args=[sys.executable,'-B','-u','-m','src.phase6.continuation_driver_v4','--output',cfg['output_root'],'--certificate',cfg['certificate_path'],'--approval',cfg['approval_path']]
    save('ONE_EVALUATOR_LAUNCH_ATTEMPT.json',dict(at=now(),command=args,maximum_launch_attempts=1,retry_authorized=False))
    start=time.perf_counter();started=now();handles={};seen={};peak_tree_rss=0
    with (OUT/'evaluator_stdout.log').open('xb') as stdout,(OUT/'evaluator_stderr.log').open('xb') as stderr,(OUT/'resource_samples.jsonl').open('x',encoding='utf-8') as resources:
        p=subprocess.Popen(args,cwd=str(ROOT),stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        save('launched_process.json',dict(at=started,launcher_pid=p.pid,supervisor_pid=os.getpid(),command=args,creation_time=psutil.Process(p.pid).create_time()))
        print(json.dumps(dict(event='authorized_single_evaluator_launched',launcher_pid=p.pid,at=started)),flush=True)
        root=psutil.Process(p.pid)
        while True:
            tree=[]
            try:processes=[root]+root.children(recursive=True)
            except psutil.Error:processes=[]
            for proc in processes:
                try:
                    mi=proc.memory_info();ct=proc.cpu_times();key=str(proc.pid)
                    if key not in handles:
                        h=k.OpenProcess(0x1000|0x100000,False,proc.pid)
                        if h:handles[key]=h
                    row=dict(pid=proc.pid,created=proc.create_time(),rss_bytes=mi.rss,private_bytes=getattr(mi,'private',None),kernel_peak_working_set_bytes=getattr(mi,'peak_wset',None),cpu_seconds=ct.user+ct.system)
                    if key not in seen:seen[key]=dict(pid=proc.pid,created=row['created'],command=proc.cmdline(),observed_rss_peak=0,observed_kernel_peak_working_set=0)
                    seen[key]['observed_rss_peak']=max(seen[key]['observed_rss_peak'],mi.rss)
                    seen[key]['observed_kernel_peak_working_set']=max(seen[key]['observed_kernel_peak_working_set'],row['kernel_peak_working_set_bytes'] or 0)
                    tree.append(row)
                except psutil.Error:continue
            vm=psutil.virtual_memory();total=sum(x['rss_bytes'] for x in tree);peak_tree_rss=max(peak_tree_rss,total)
            sample=dict(at=now(),elapsed_seconds=time.perf_counter()-start,available_physical_bytes=vm.available,tree_rss_bytes=total,processes=tree)
            resources.write(json.dumps(sample)+'\n');resources.flush()
            try:rc=p.wait(timeout=5);break
            except subprocess.TimeoutExpired:pass
        final_cpu={pid:cpu(h) for pid,h in handles.items()}
        for h in handles.values():k.CloseHandle(h)
        save('execution_result.json',dict(status='EVALUATOR_EXITED_SUCCESS' if rc==0 else 'STOP_EVALUATOR_FAILED',returncode=rc,started_at=started,ended_at=now(),wall_seconds=time.perf_counter()-start,processes=seen,process_CPU_times_from_readonly_handles=final_cpu,observed_tree_RSS_peak_bytes=peak_tree_rss,memory_sampling_seconds=5,memory_peak_scope='Windows-reported cumulative peak working sets through last successful sample; tree RSS sampled, shared pages may be double-counted',evaluator_launch_attempts=1,automatic_retry=False,signals_sent=0,phase7_started=False))
        print(json.dumps(dict(event='single_evaluator_exited',returncode=rc,wall_seconds=time.perf_counter()-start)),flush=True)
if __name__=='__main__':main()

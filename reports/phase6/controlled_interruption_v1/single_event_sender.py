"""One user-authorized CTRL_C_EVENT. No retry, escalation or database access.

DETACHED helper attaches to the verified original console, protects ITSELF,
checks exact recipients and sends once, matching the disposable fixture APIs.
"""
from pathlib import Path
from datetime import datetime,timezone
import ctypes,hashlib,json,os,re,subprocess,sys,time
from ctypes import wintypes

ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL')
OUT=Path(__file__).resolve().parent
EXPECTED={22264:('2026-11-17T14:48:06.459723+05:00',12092,'python.exe'),12092:('2026-11-17T14:48:06.435396+05:00',12764,'python.exe'),12764:('2026-11-17T14:48:05.791782+05:00',30188,'pwsh.exe')}
RELEASE='4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370'

def save(name,value):
    with (OUT/name).open('x',encoding='utf8') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def now():return datetime.now().astimezone().isoformat()
def processes():
    command="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|pwsh|powershell)\\.exe$' } | Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine,ExecutablePath | ConvertTo-Json -Depth 2"
    r=subprocess.run([sys.argv[2],'-NoLogo','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
    require(r.returncode==0,'Process metadata query failed: '+r.stderr)
    result=json.loads(r.stdout);return result if isinstance(result,list) else [result]
def progress():
    root=ROOT/'reports/phase6/heldout_test_v2/final_v1';done=[];active=[]
    for p in sorted(root.iterdir()):
        if not p.is_dir():continue
        if (p/'completion.json').exists():
            c=json.loads((p/'completion.json').read_bytes());require(c['status']=='COMPLETE_VALIDATED' and c['identity']['variant']==p.name,'Unexpected completion metadata');done.append(p.name)
        else:
            counts={};last=None;last_complete=None
            for j in sorted((p/'sharing/progress').glob('barriers.*.jsonl')):
                with j.open('rb') as f:
                    for line in f:
                        if not line.endswith(b'\n'):continue
                        r=json.loads(line);b=r['body'];e=b['event'];counts[e]=counts.get(e,0)+1
                        last={k:b.get(k) for k in ('event','at','organization')}
                        if e=='COMPLETE':last_complete=b['at']
            active.append(dict(variant=p.name,counts=counts,last=last,last_completed_barrier=last_complete))
    require(len(done)<171 and len(active)<=1,'No incomplete work or ambiguous active campaign census')
    return dict(checked_at=now(),completed=done,active=active)

def main():
    send=sys.argv[1]=='--send-once';prefix='live' if send else 'inspection'
    require(sys.argv[1] in ('--inspect-only','--send-once'),'Invalid mode')
    require(not (OUT/'signal_attempt.json').exists(),'One-attempt marker exists; no retry allowed')
    auth=json.loads((OUT/'user_authorization_record.json').read_bytes())
    require(auth['decision']=='USER_AUTHORIZED_CONDITIONAL_RECOVERABLE_INTERRUPTION' and not auth['v4_execution_authorized'] and sha(auth['source'])==auth['source_sha256'],'Authorization mismatch')
    checks=[]
    for baseline in ('reports/phase6/wal_continuation_v4_v1/preservation_before.json','reports/phase6/wal_continuation_v4_v1/delivery_manifest_v1.json'):
        values=json.loads((ROOT/baseline).read_bytes());values=values.get('files_sha256',values)
        for p,h in values.items():
            require(p.startswith(('src/','configs/','tests/','reports/phase6/')) and 'data2/' not in p and 'local.sqlite' not in p and '/oracles/' not in p,'Unexpected hash scope')
            require(sha(ROOT/p)==h,'Reviewed source/evidence changed: '+p);checks.append(p)
    sys.path.insert(0,str(ROOT))
    from src.phase6.continuation_contract_v4 import release_identity
    require(release_identity()==RELEASE,'Reviewed release changed')
    rows=processes();byid={p['ProcessId']:p for p in rows}
    for pid,(created,parent,name) in EXPECTED.items():
        require(pid in byid,'Original process absent: '+str(pid));p=byid[pid]
        require(datetime.fromisoformat(p['CreationDate'])==datetime.fromisoformat(created) and p['ParentProcessId']==parent and p['Name']==name,'Original process identity changed: '+str(pid))
        require('-m src.phase6.heldout_driver_v2' in p['CommandLine'] and '--output reports/phase6/heldout_test_v2/final_v1' in p['CommandLine'],'Original command mismatch')
    evaluated={p['ProcessId'] for p in rows if p['Name'].lower().startswith('python') and re.search(r'\s-m\s+src\.phase6\.(heldout_driver_v\d+|continuation_driver_v\d+|detectability_batch)',p.get('CommandLine') or '')}
    require(evaluated=={22264,12092},'Unexpected/duplicate evaluator chain')
    pre=progress()
    save(prefix+'_preflight.json',dict(status='PASS_METADATA_SOURCE_AND_IDENTITY_PRECHECK',checked_at=now(),processes=[byid[p] for p in EXPECTED],reviewed_hash_checks=len(checks),release_identity=RELEASE,progress=pre,helper_pid=os.getpid()))
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.AttachConsole.argtypes=[wintypes.DWORD];k.AttachConsole.restype=wintypes.BOOL
    k.SetConsoleCtrlHandler.argtypes=[ctypes.c_void_p,wintypes.BOOL];k.SetConsoleCtrlHandler.restype=wintypes.BOOL
    k.GetConsoleProcessList.argtypes=[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD];k.GetConsoleProcessList.restype=wintypes.DWORD
    k.GenerateConsoleCtrlEvent.argtypes=[wintypes.DWORD,wintypes.DWORD];k.GenerateConsoleCtrlEvent.restype=wintypes.BOOL
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD
    k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];k.GetExitCodeProcess.restype=wintypes.BOOL
    class FileTime(ctypes.Structure):_fields_=[('lo',wintypes.DWORD),('hi',wintypes.DWORD)]
    k.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(FileTime)]*4;k.GetProcessTimes.restype=wintypes.BOOL
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    handles={p:k.OpenProcess(0x100000|0x1000,False,p) for p in EXPECTED}
    require(all(handles.values()),'Could not obtain read-only process observation handles')
    attached=False
    try:
        for pid,handle in handles.items():
            created,exited,kernel,user=FileTime(),FileTime(),FileTime(),FileTime()
            require(k.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)),'Creation-time handle verification failed')
            delta=datetime.fromisoformat(EXPECTED[pid][0]).astimezone(timezone.utc)-datetime(1601,1,1,tzinfo=timezone.utc)
            expected_microseconds=(delta.days*86400+delta.seconds)*1000000+delta.microseconds
            require(((created.hi<<32)|created.lo)//10==expected_microseconds,'PID reuse/creation-time mismatch')
        k.FreeConsole();require(k.AttachConsole(22264),'Cannot attach inspection helper to original console');attached=True
        require(k.SetConsoleCtrlHandler(None,True),'Helper self-protection failed')
        def members():
            b=(wintypes.DWORD*4096)();n=k.GetConsoleProcessList(b,4096)
            require(0<n<=4096,'Cannot establish exact console recipients');return set(b[:n])
        expected=set(EXPECTED)|{os.getpid()};require(members()==expected,'Unexpected console recipient')
        require(all(k.WaitForSingleObject(h,0)==0x102 for h in handles.values()),'Original process exited during preflight')
        scope=dict(checked_at=now(),original_recipients=sorted(EXPECTED),all_console_members=sorted(expected),helper_ignores_CTRL_C=True,parent_PowerShell_control_flow_may_be_interrupted=True)
        save(prefix+'_recipient_scope.json',scope)
        if not send:
            save('inspection_result.json',dict(status='PASS_NO_EVENT_SENT',scope=scope,signal_attempts=0));return
        require(members()==expected,'Console membership changed immediately before event')
        save('signal_attempt.json',dict(status='ONE_AUTHORIZED_SEND_ATTEMPT_ARMED',at=now(),event='CTRL_C_EVENT',event_value=0,process_group=0,scope=scope,authorization_sha256=sha(OUT/'user_authorization_record.json'),sender_sha256=sha(__file__),retry_allowed=False))
        # EXACTLY ONE call. No fallback or second event exists.
        ok=k.GenerateConsoleCtrlEvent(0,0)
        save('signal_delivery_result.json',dict(at=now(),api_success=bool(ok),win32_error=None if ok else ctypes.get_last_error(),graceful_shutdown_claim=False))
        if not ok:return
        deadline=time.monotonic()+120;observations=[]
        while True:
            row=dict(at=now(),processes={})
            for pid,handle in handles.items():
                exited=k.WaitForSingleObject(handle,0)==0;code=wintypes.DWORD()
                require(k.GetExitCodeProcess(handle,ctypes.byref(code)),'Exit observation failed')
                row['processes'][str(pid)]=dict(exited=exited,exit_code=code.value)
            observations.append(row)
            if all(row['processes'][str(p)]['exited'] for p in (22264,12092)) or time.monotonic()>=deadline:break
            time.sleep(.5)
        exited=all(observations[-1]['processes'][str(p)]['exited'] for p in (22264,12092))
        save('process_exit_observations.json',dict(status='WORKER_AND_LAUNCHER_EXIT_OBSERVED' if exited else 'STOP_WRITER_EXIT_NOT_ESTABLISHED',observations=observations,no_escalation=True))
    finally:
        if attached:k.FreeConsole()
        for handle in handles.values():
            if handle:k.CloseHandle(handle)

if __name__=='__main__':
    try:main()
    except BaseException as error:
        name='sender_failure_'+datetime.now().strftime('%H%M%S%f')+'.json'
        save(name,dict(status='STOP',at=now(),error_type=type(error).__name__,message=str(error),attempt_marker_exists=(OUT/'signal_attempt.json').exists(),retry_allowed=False))
        raise

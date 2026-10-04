"""Audit-only guard: block application secrets, external sockets and writes outside temp/results."""
import os,sys,socket,tempfile
from pathlib import Path

def install(out,live=False,database_port=None):
    if database_port is not None and (type(database_port) is not int or not 1024 <= database_port <= 65535):
        raise ValueError('Invalid isolated database port')
    sys.dont_write_bytecode=True
    root=Path(tempfile.mkdtemp(prefix='garmin-audit-')).resolve()
    out=out.resolve()
    for key in list(os.environ):
        if any(x in key.upper() for x in ('TOKEN','SECRET','DATABASE_URL','PASSWORD','API_KEY')):
            os.environ.pop(key,None)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    os.chdir(root)
    blocked=[]
    def in_allowed(p):
        if isinstance(p,int): return True
        p=Path(os.fsdecode(p)).resolve()
        return p.is_relative_to(root) or p.is_relative_to(out/'ejecuciones')
    def guard(event,args):
        if event=='open':
            path,mode,flags=args
            if not isinstance(path,int):
                p=Path(os.fsdecode(path))
                if (p.name=='.env' or 'strava-tokens' in p.name or '.garminconnect' in p.parts) and not p.resolve().is_relative_to(root):
                    blocked.append('secret_read');raise PermissionError('Audit blocks credential files')
            if ((isinstance(mode,str) and any(x in mode for x in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))) and not in_allowed(path):
                blocked.append('write');raise PermissionError('Audit blocks write outside allowed roots')
        elif event in ('os.mkdir','os.remove','os.rmdir','os.chmod','os.truncate'):
            if not in_allowed(args[0]): blocked.append('mutation');raise PermissionError('Audit blocks filesystem mutation')
        elif event in ('os.rename','os.link','os.symlink'):
            if not all(in_allowed(x) for x in args[:2]): blocked.append('mutation');raise PermissionError('Audit blocks filesystem mutation')
        elif event=='socket.connect':
            addr=args[1]
            allowed_ports=({11434} if live else set()) | ({database_port} if database_port is not None else set())
            if not (isinstance(addr,tuple) and addr[0]=='127.0.0.1' and addr[1] in allowed_ports):
                blocked.append('network');raise PermissionError('Audit blocks network')
        elif event in ('subprocess.Popen','os.system','os.posix_spawn','os.fork'):
            blocked.append('process');raise PermissionError('Audit blocks subprocesses')
    sys.addaudithook(guard)
    import dotenv
    dotenv.load_dotenv=lambda *a,**k:False
    return root,blocked

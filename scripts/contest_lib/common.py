"""Bounded I/O and public runner invocation, without loading AI libraries here."""
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from tournament_lib.execution import command_to_logs
from tournament_lib.storage import sha,identifier

ROOT=Path(__file__).resolve().parents[2]
MAX_JSON=16*1024*1024


def read_json(path,limit=MAX_JSON):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError(f'{path}: duplicate JSON key {key}')
            result[key]=value
        return result
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError(f'not a regular file: {path}')
            data=stream.read(limit+1)
        if len(data)>limit:raise ValueError(f'JSON size limit: {path}')
        return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,
                          parse_constant=lambda x:(_ for _ in ()).throw(ValueError(f'invalid JSON constant: {x}')))
    except (OSError,UnicodeError,json.JSONDecodeError) as error:
        raise ValueError(f'{path}: {error}') from error


def regular(path,executable=False):
    path=Path(path).resolve(strict=True)
    if not path.is_file() or executable and not os.access(path,os.X_OK):
        raise ValueError(f'file missing or not executable: {path}')
    return path


def resolve_runner(path=None):
    if path is not None:return regular(path,True)
    for p in [ROOT/'bin/fff-runner',ROOT/'target/release/fff-runner']:
        if p.is_file():return regular(p,True)
    raise ValueError('fff-runner not found; provide --runner or build release tools')


def resolve_opponent(path,runner):
    if path is not None:return regular(path)
    for p in [ROOT/'lib/libfff_bot_baseline.so',ROOT/'target/release/libfff_bot_baseline.so',
              Path(runner).parent/'libfff_bot_baseline.so',Path(runner).parent.parent/'lib/libfff_bot_baseline.so']:
        if p.is_file():return regular(p)
    raise ValueError('baseline not found; provide --opponent')


def log_text(path,limit=16384):
    with Path(path).open('rb') as stream:
        stream.seek(0,2);stream.seek(max(0,stream.tell()-limit));return stream.read(limit).decode('utf-8',errors='replace')


def invoke(command,logdir,prefix,lock_fd=None):
    logdir=Path(logdir);logdir.mkdir(parents=True,exist_ok=True)
    return command_to_logs([str(x) for x in command],logdir,prefix,lock_fd)


def inspect_map(runner,path):
    path=regular(path)
    if path.stat().st_size>1024*1024:raise ValueError('map exceeds 1MiB')
    with tempfile.TemporaryDirectory(prefix='fff-inspect-') as tmp:
        if invoke([runner,'inspect-map',path],tmp,'inspect'):
            raise ValueError('map inspection failed: '+log_text(Path(tmp)/'inspect.stderr.log'))
        data=read_json(Path(tmp)/'inspect.stdout.log')
    if not isinstance(data,dict) or data.get('format_version')!=1 or type(data.get('players')) is not int or not 2<=data['players']<=8:
        raise ValueError('invalid inspect-map response')
    identifier(data.get('id'))
    return data


def freeze(source,destination):
    source=regular(source);before=source.stat();fingerprint=sha(source)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
    after=source.stat()
    key=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    if key(before)!=key(after) or sha(destination)!=fingerprint:raise ValueError(f'source changed while freezing: {source}')
    return {'source':str(source),'sha256':fingerprint}

"""Verified, non-destructive replay archives with bounded manual extraction."""
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile
from tournament_lib.execution import collect
from tournament_lib.storage import load_plan,publish_path,sha,snapshot_path,staged_directory
from .common import decode_json,read_object,resolve_runner
from .experiment import locked_suite
from .summary import record_inventory,verify_match,tree_bytes,file_stat

MAX_FILES=1000000
MAX_BYTES=64*1024**3
MAX_MANIFEST=256*1024**2
ID=r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'
RAW={'manifest.json','map.json','map.ron','initial.json','initial.txt','summary.json'}


class _LimitedInfo(tarfile.TarInfo):
    """Bound extension headers before tarfile allocates/decodes their contents.

    TarInfo's processing hooks exist in supported Python 3.10+; payload readers
    separately enforce manifest quotas. Sparse formats are outside this format.
    """
    def _proc_pax(self,tar):
        if self.size>65536:raise ValueError('archive extension metadata limit')
        return super()._proc_pax(tar)
    def _proc_gnulong(self,tar):
        if self.size>65536:raise ValueError('archive extension metadata limit')
        return super()._proc_gnulong(tar)
    def _proc_sparse(self,*args,**kwargs):raise ValueError('sparse archives are not supported')
    def _proc_gnusparse_00(self,*args,**kwargs):raise ValueError('sparse archives are not supported')
    def _proc_gnusparse_01(self,*args,**kwargs):raise ValueError('sparse archives are not supported')
    def _proc_gnusparse_10(self,*args,**kwargs):raise ValueError('sparse archives are not supported')


def positive(value,label):
    if type(value) is not int or value<1:raise ValueError(f'{label} must be a positive integer')
    return value


def relative(value):
    if not isinstance(value,str) or not value or len(value)>4096 or '\\' in value or ':' in value or any(ord(c)<32 for c in value):
        raise ValueError('invalid archive path')
    if any(p in ('','.','..') for p in value.split('/')) or value.startswith('/'):
        raise ValueError(f'unsafe archive path: {value}')
    return value


def raw_path(value):
    return value in RAW or re.fullmatch(r'frames/[0-9]{6,}\.(json|txt)',value) is not None


def allowed(value,kind,matches):
    relative(value)
    if kind=='match':return raw_path(value)
    for match in matches:
        if value.startswith(match+'/') and raw_path(value[len(match)+1:]):return True
    if value in ('suite.json','suite.sha256','seeds.json'):return True
    patterns=[rf'config-{ID}\.json',rf'inputs/(opponent\.so|maps/map-[0-9]+\.ron|versions/{ID}\.so)',
              rf'versions/{ID}/(plan\.json|plan\.sha256|inputs/(ais/(candidate|opponent_[0-9]+)\.so|maps/{ID}\.ron))',
              rf'versions/{ID}/matches/[^/]+/attempt-[0-9]+/(attempt\.json|runner\.(stdout|stderr)\.log)']
    return any(re.fullmatch(pattern,value) for pattern in patterns)


def _key(info):
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


@contextmanager
def _open_source(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError(f'unsafe source file: {path}')
        yield stream,info


def _hash_source(path,expected=None):
    with _open_source(path) as (stream,info):
        if expected is not None and _key(info)!=expected:raise ValueError('source changed during archive')
        digest=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if _key(os.fstat(stream.fileno()))!=_key(info):raise ValueError('source changed during archive')
        return digest.hexdigest()


@contextmanager
def _selection(root,runner,logs):
    if (root/'suite.json').is_file():
        with locked_suite(root) as (suite,fds):
            tree_bytes(root)  # Reject all links/special files, including excluded extras.
            selected={root/'suite.json',root/'suite.sha256',root/'seeds.json'}
            selected.update(snapshot_path(root,item['path']) for item in suite['frozen_inputs'])
            matches=[]
            for version in suite['versions']:
                plan_root=snapshot_path(root,version['plan']);plan=load_plan(plan_root)
                for manifest in plan_root.glob('matches/*/attempt-*/match/manifest.json'):
                    value=read_object(manifest)
                    if value.get('status')=='complete':record_inventory(manifest.parent)
                rows=collect(plan_root,plan,fds[version['id']])
                if len(rows)!=len(plan['matches']):raise ValueError('cannot archive incomplete experiment')
                selected.update([root/f'config-{version["id"]}.json',plan_root/'plan.json',plan_root/'plan.sha256'])
                selected.update(snapshot_path(plan_root,item['path']) for item in plan['ais']+plan['groups'])
                for row in rows:
                    match=plan_root/row['directory'];inventory=record_inventory(match)
                    matches.append(str(match.relative_to(root)));selected.update(inventory['files'])
                    selected.add(match.parent/'attempt.json')
                    for name in ['runner.stdout.log','runner.stderr.log']:
                        if (match.parent/name).exists():selected.add(match.parent/name)
            yield 'selftest',sorted(matches),sorted(selected)
    else:
        inventory=verify_match(root,runner,logs)
        yield 'match',['.'],sorted(inventory['files'])


class _HashReader:
    def __init__(self,stream):self.stream=stream;self.digest=hashlib.sha256();self.count=0
    def read(self,size=-1):
        data=self.stream.read(size);self.digest.update(data);self.count+=len(data);return data


def archive_records(source,out,runner=None,max_files=MAX_FILES,max_bytes=MAX_BYTES):
    positive(max_files,'max-files');positive(max_bytes,'max-bytes')
    if Path(source).is_symlink():raise ValueError('symlink archive source')
    root=Path(source).resolve(strict=True);out=Path(out).absolute();runner=resolve_runner(runner)
    if out.resolve().is_relative_to(root):raise ValueError('archive output cannot be inside source')
    if os.path.lexists(out):raise ValueError('output already exists')
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='.'+out.name+'-',dir=out.parent) as tmp:
            temp=Path(tmp)
            with _selection(root,runner,temp/'verify-logs') as (kind,matches,files):
                if len(files)>max_files:raise ValueError('archive file limit')
                entries=[];snapshots={};total=0
                for path in files:
                    rel=str(path.relative_to(root))
                    if not allowed(rel,kind,matches):raise ValueError(f'unsupported archive payload: {rel}')
                    info=file_stat(path);total+=info.st_size
                    if total>max_bytes:raise ValueError('archive byte limit')
                    key=_key(info);snapshots[rel]=key
                    entries.append({'path':rel,'size':info.st_size,'sha256':_hash_source(path,key),'mode':stat.S_IMODE(info.st_mode)&0o777})
                manifest={'format':'fff-replay-archive','version':1,'kind':kind,'matches':matches,'files':entries}
                encoded=json.dumps(manifest,ensure_ascii=False,separators=(',',':')).encode()
                if len(encoded)>MAX_MANIFEST:raise ValueError('archive manifest size limit')
                saved=temp/'archive.tar.gz'
                with saved.open('xb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as zipped,tarfile.open(fileobj=zipped,mode='w|',format=tarfile.PAX_FORMAT) as tar:
                    info=tarfile.TarInfo('archive.json');info.size=len(encoded);info.mode=0o644;tar.addfile(info,io.BytesIO(encoded))
                    for entry in entries:
                        path=root/entry['path'];info=tarfile.TarInfo('payload/'+entry['path']);info.size=entry['size'];info.mode=entry['mode']
                        with _open_source(path) as (stream,before):
                            if _key(before)!=snapshots[entry['path']]:raise ValueError('source changed during archive')
                            reader=_HashReader(stream);tar.addfile(info,reader)
                            if reader.count!=entry['size'] or reader.digest.hexdigest()!=entry['sha256'] or _key(os.fstat(stream.fileno()))!=_key(before):
                                raise ValueError('source changed during archive')
                for entry in entries:
                    path=root/entry['path']
                    if _key(file_stat(path))!=snapshots[entry['path']] or _hash_source(path,snapshots[entry['path']])!=entry['sha256']:
                        raise ValueError('source changed during archive')
                publish_path(saved,out)
        return {'archive':str(out),'sha256':sha(out),'files':len(entries),'matches':len(matches),'uncompressed_bytes':total,'source_preserved':True}
    except tarfile.TarError as error:raise ValueError(f'invalid archive: {error}') from error


def _manifest(data,max_files,max_bytes):
    if not isinstance(data,dict) or set(data)!={'format','version','kind','matches','files'} or data['format']!='fff-replay-archive' or type(data['version']) is not int or data['version']!=1:
        raise ValueError('unsupported archive manifest')
    kind=data['kind'];matches=data['matches'];files=data['files']
    if kind not in ('match','selftest') or not isinstance(matches,list) or not matches or not isinstance(files,list) or not 0<len(files)<=max_files:
        raise ValueError('archive manifest counts/kind')
    if any(not isinstance(p,str) for p in matches) or len(set(matches))!=len(matches):raise ValueError('duplicate/invalid match roots')
    if kind=='match' and matches!=['.']:raise ValueError('single match root must be .')
    if kind=='selftest':
        for match in matches:
            relative(match)
            if not re.fullmatch(rf'versions/{ID}/matches/[^/]+/attempt-[0-9]+/match',match):raise ValueError('invalid experiment match root')
    entries={};total=0
    for item in files:
        if not isinstance(item,dict) or set(item)!={'path','size','sha256','mode'}:raise ValueError('invalid file manifest')
        path=relative(item['path'])
        if path in entries or not allowed(path,kind,matches):raise ValueError('duplicate/unsupported payload path')
        if type(item['size']) is not int or item['size']<0 or type(item['mode']) is not int or not 0<=item['mode']<=0o777:
            raise ValueError('invalid payload size/mode')
        if not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('invalid payload SHA256')
        total+=item['size']
        if total>max_bytes:raise ValueError('archive byte limit')
        entries[path]=item
    roots={str(Path(p).parent) for p in entries if Path(p).name=='manifest.json'}
    if roots!=set(matches):raise ValueError('manifest does not cover every match')
    for match in matches:
        prefix='' if match=='.' else match+'/'
        if not all(prefix+name in entries for name in RAW):raise ValueError('match is missing required records')
    if kind=='selftest' and not {'suite.json','suite.sha256','seeds.json'}<=set(entries):raise ValueError('missing experiment metadata')
    return entries


def _regular_member(member):
    if not member.isreg() or member.linkname or member.sparse is not None or not 0<=member.mode<=0o777:
        raise ValueError('links, sparse or special archive members are not allowed')


def restore_archive(source,out,runner=None,max_files=MAX_FILES,max_bytes=MAX_BYTES):
    positive(max_files,'max-files');positive(max_bytes,'max-bytes')
    if Path(source).is_symlink():raise ValueError('symlink archive file')
    source=Path(source).absolute();out=Path(out).absolute();runner=resolve_runner(runner)
    if os.path.lexists(out):raise ValueError('output already exists')
    try:
        with _open_source(source) as (stream,before),tarfile.open(fileobj=stream,mode='r|*',tarinfo=_LimitedInfo) as tar:
            first=next(iter(tar),None)
            if first is None or first.name!='archive.json':raise ValueError('archive manifest must be first')
            _regular_member(first)
            if first.size>MAX_MANIFEST:raise ValueError('archive manifest size limit')
            content=tar.extractfile(first).read(MAX_MANIFEST+1)
            manifest=decode_json(content,'archive.json');entries=_manifest(manifest,max_files,max_bytes)
            with staged_directory(out) as stage:
                seen=set()
                for member in tar:
                    # Streaming iteration may yield the already consumed first member.
                    if member is first:continue
                    _regular_member(member)
                    if not member.name.startswith('payload/'):raise ValueError('unexpected archive member')
                    rel=relative(member.name[len('payload/'):]);entry=entries.get(rel)
                    if entry is None or rel in seen:raise ValueError('unknown/duplicate archive member')
                    if member.size!=entry['size'] or member.mode!=entry['mode']:raise ValueError('member differs from manifest')
                    target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256();size=0
                    with tar.extractfile(member) as incoming,target.open('xb') as destination:
                        for chunk in iter(lambda:incoming.read(1024*1024),b''):
                            size+=len(chunk)
                            if size>entry['size']:raise ValueError('payload exceeds declared size')
                            digest.update(chunk);destination.write(chunk)
                    if size!=entry['size'] or digest.hexdigest()!=entry['sha256']:raise ValueError('payload checksum/size mismatch')
                    target.chmod(entry['mode']);seen.add(rel)
                if seen!=set(entries):raise ValueError('missing archive payload')
                with tempfile.TemporaryDirectory(prefix='fff-restore-verify-') as logs:
                    for i,match in enumerate(manifest['matches']):verify_match(stage if match=='.' else stage/match,runner,Path(logs)/str(i))
                if _key(os.fstat(stream.fileno()))!=_key(before) or _key(file_stat(source))!=_key(before):
                    raise ValueError('archive changed during restore')
        return {'output':str(out),'files':len(entries),'matches':len(manifest['matches']),'verified':True,'portable_resume':False}
    except (tarfile.TarError,EOFError,RecursionError) as error:raise ValueError(f'invalid archive: {error}') from error

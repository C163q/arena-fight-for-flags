"""Explicit, reusable experiment conditions; AI seeds never derive from engine seeds."""
import re
import secrets


def uint(value,bits,label):
    if type(value) is not int or not 0<=value<2**bits:
        raise ValueError(f'{label}: expected unsigned {bits}-bit integer')
    return value


def make_seed_spec(maps,repeats):
    if type(repeats) is not int or repeats<1:
        raise ValueError('repeats must be positive')
    roots=[secrets.randbits(256),secrets.randbits(256)]
    while roots[0]==roots[1]:roots[1]=secrets.randbits(256)
    used=set();entries={}
    for item in maps:
        values=[]
        while len(values)<repeats:
            seed=secrets.randbits(64)
            if seed not in used:used.add(seed);values.append(seed)
        if item['id'] in entries:raise ValueError('duplicate map ID')
        entries[item['id']]={'players':item['players'],'sha256':item['sha256'],'engine_seeds':values}
    return {'version':1,'ai_seed_root':roots[0],'schedule_seed_root':roots[1],'maps':entries}


def validate_seed_spec(spec,groups,repeats):
    if not isinstance(spec,dict) or set(spec)!={'version','ai_seed_root','schedule_seed_root','maps'}:
        raise ValueError('invalid seed file fields')
    if type(spec['version']) is not int or spec['version']!=1:
        raise ValueError('seed file version must be 1')
    ai=uint(spec['ai_seed_root'],256,'ai_seed_root')
    schedule=uint(spec['schedule_seed_root'],256,'schedule_seed_root')
    if ai==schedule:raise ValueError('AI and schedule seed roots must differ')
    entries=spec['maps'];used=set()
    if not isinstance(entries,dict) or not entries:raise ValueError('seed maps must be nonempty')
    for key,item in entries.items():
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',key):
            raise ValueError('invalid seed map ID')
        if not isinstance(item,dict) or set(item)!={'players','sha256','engine_seeds'}:
            raise ValueError('invalid seed map fields')
        if type(item['players']) is not int or not 2<=item['players']<=8:
            raise ValueError('invalid seed map players')
        if not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']):
            raise ValueError('invalid seed map fingerprint')
        values=item['engine_seeds']
        if not isinstance(values,list) or not values:raise ValueError('engine seeds must be a nonempty list')
        for value in values:
            uint(value,64,'engine seed')
            if value in used:raise ValueError('duplicate engine seed')
            used.add(value)
    for group in groups:
        item=entries.get(group['id'])
        if item is None or item['players']!=group['players'] or item['sha256']!=group['sha256']:
            raise ValueError(f'seed map fingerprint/players mismatch: {group["id"]}')
        if len(item['engine_seeds'])!=repeats:
            raise ValueError(f'seed count differs from repeats: {group["id"]}')
    return spec

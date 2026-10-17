"""Archives must neither overwrite data nor extract hostile paths or file types."""
import copy
import hashlib
import gzip
import io
import json
from pathlib import Path
import tarfile
from unittest.mock import patch
from contest_tools_fixtures import ToolFixture
from test_contest_summary import sample
from tournament_lib.storage import locked
try:
    from contest_lib import archive
except ImportError:archive=None


class ArchiveTests(ToolFixture):
    def setUp(self):
        super().setUp();self.match=self.base/'match';sample(self.match)
    def make(self,name='saved.tar.gz'):
        self.assertIsNotNone(archive,'archive module missing')
        target=self.base/name
        archive.archive_records(self.match,target,self.runner)
        return target
    def altered(self,source,path,edit):
        entries=[]
        with tarfile.open(source) as tar:
            for member in tar:
                entries.append((copy.copy(member),tar.extractfile(member).read()))
        entries=edit(entries)
        with tarfile.open(path,'w:gz') as tar:
            for member,data in entries:tar.addfile(member,io.BytesIO(data) if member.isreg() else None)
        return path

    def test_round_trip_keeps_source_and_exact_payload(self):
        before={str(p.relative_to(self.match)):p.read_bytes() for p in self.match.rglob('*') if p.is_file()}
        saved=self.make();out=self.base/'restored'
        result=archive.restore_archive(saved,out,self.runner)
        self.assertTrue(result['verified'])
        after={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(before,{str(p.relative_to(self.match)):p.read_bytes() for p in self.match.rglob('*') if p.is_file()})

    def test_existing_outputs_and_self_containment_rejected(self):
        saved=self.make();original=saved.read_bytes()
        with self.assertRaises(ValueError):archive.archive_records(self.match,saved,self.runner)
        self.assertEqual(saved.read_bytes(),original)
        with self.assertRaises(ValueError):archive.archive_records(self.match,self.match/'recursive.tar.gz',self.runner)
        out=self.base/'restored';out.mkdir();(out/'keep').write_text('human')
        with self.assertRaises(ValueError):archive.restore_archive(saved,out,self.runner)
        self.assertEqual((out/'keep').read_text(),'human')

    def test_incomplete_and_nonregular_sources_rejected(self):
        self.assertIsNotNone(archive)
        manifest=self.match/'manifest.json';data=json.loads(manifest.read_text());data['status']='in_progress';manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):archive.archive_records(self.match,self.base/'out.tar.gz',self.runner)
        data['status']='complete';manifest.write_text(json.dumps(data))
        target=self.base/'secret';target.write_text('human');(self.match/'extra').symlink_to(target)
        with self.assertRaises(ValueError):archive.archive_records(self.match,self.base/'out.tar.gz',self.runner)
        self.assertEqual(target.read_text(),'human')

    def test_hard_links_are_not_archived(self):
        self.assertIsNotNone(archive)
        import os
        os.link(self.match/'map.ron',self.base/'linked')
        with self.assertRaises(ValueError):archive.archive_records(self.match,self.base/'out.tar.gz',self.runner)

    def test_lock_symlink_never_creates_an_external_file(self):
        root=self.base/'locked';root.mkdir();protected=self.base/'protected-lock'
        (root/'.lock').symlink_to(protected)
        with self.assertRaises((ValueError,OSError)):
            with locked(root):pass
        self.assertFalse(protected.exists())

    def test_traversal_absolute_duplicates_and_special_members_rejected(self):
        saved=self.make()
        for index,bad in enumerate(['../escape','/absolute','payload/../escape','payload/a/./b','payload/a\\b']):
            def edit(entries,bad=bad):
                member,data=entries[1];member.name=bad;return entries
            altered=self.altered(saved,self.base/f'bad-{index}.tar.gz',edit)
            with self.subTest(bad=bad),self.assertRaises(ValueError):archive.restore_archive(altered,self.base/f'out-{index}',self.runner)
            self.assertFalse((self.base/f'out-{index}').exists())
        altered=self.altered(saved,self.base/'duplicate.tar.gz',lambda entries:entries+[entries[1]])
        with self.assertRaises(ValueError):archive.restore_archive(altered,self.base/'dup-out',self.runner)
        for index,kind in enumerate([tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE,tarfile.CHRTYPE]):
            def special(entries,kind=kind):
                entries[1][0].type=kind;entries[1][0].linkname='../protected';entries[1][0].size=0;return entries
            altered=self.altered(saved,self.base/f'special-{index}.tar.gz',special)
            with self.subTest(kind=kind),self.assertRaises(ValueError):archive.restore_archive(altered,self.base/f'special-out-{index}',self.runner)

    def test_checksum_missing_payload_and_limits_rejected(self):
        saved=self.make()
        def corrupt(entries):
            member,data=entries[1];data=b'X'+data[1:];entries[1]=(member,data);return entries
        altered=self.altered(saved,self.base/'corrupt.tar.gz',corrupt)
        with self.assertRaises(ValueError):archive.restore_archive(altered,self.base/'bad',self.runner)
        altered=self.altered(saved,self.base/'missing.tar.gz',lambda entries:entries[:-1])
        with self.assertRaises(ValueError):archive.restore_archive(altered,self.base/'missing',self.runner)
        for options in [{'max_files':1},{'max_bytes':1},{'max_files':True}]:
            with self.subTest(options=options),self.assertRaises(ValueError):archive.restore_archive(saved,self.base/'limited',self.runner,**options)
            self.assertFalse((self.base/'limited').exists())

    def test_oversized_extension_metadata_is_rejected_before_payload(self):
        saved=self.make();target=self.base/'extended.tar.gz'
        with tarfile.open(saved) as original,tarfile.open(target,'w:gz') as changed:
            for index,member in enumerate(original):
                if index==0:member.pax_headers={'comment':'X'*70000}
                changed.addfile(member,io.BytesIO(original.extractfile(member).read()))
        with self.assertRaises(ValueError):archive.restore_archive(target,self.base/'extended-out',self.runner)
        self.assertFalse((self.base/'extended-out').exists())

    def test_source_mutation_during_archive_does_not_publish(self):
        self.assertIsNotNone(archive)
        original=tarfile.TarFile.addfile
        def changed(tar,member,fileobj=None):
            if member.name=='payload/map.ron':(self.match/'map.ron').write_text('mutated source')
            return original(tar,member,fileobj)
        with patch.object(tarfile.TarFile,'addfile',changed):
            with self.assertRaises((ValueError,OSError)):archive.archive_records(self.match,self.base/'raced.tar.gz',self.runner)
        self.assertFalse((self.base/'raced.tar.gz').exists())

    def test_active_and_incomplete_experiments_cannot_be_archived(self):
        self.assertIsNotNone(archive)
        from contest_lib.experiment import prepare_suite
        root=self.base/'suite';prepare_suite([('main',self.ai)],[self.map],self.opponent,self.runner,root)
        with locked(root/'versions/main'):
            with self.assertRaisesRegex(ValueError,'locked'):archive.archive_records(root,self.base/'suite.tar.gz',self.runner)
        with self.assertRaises(ValueError):archive.archive_records(root,self.base/'suite.tar.gz',self.runner)
        self.assertFalse((self.base/'suite.tar.gz').exists())

    def test_global_pax_cannot_hide_raw_data_outside_payload_quota(self):
        saved=self.make()
        with tarfile.open(saved) as tar:
            parts=[(copy.copy(m),tar.extractfile(m).read()) for m in tar]
        manifest=parts[0][1];target=self.base/'global-pax.tar.gz'
        def global_size(size):
            return tarfile.TarInfo.create_pax_global_header({'size':str(size)})
        with gzip.open(target,'wb') as output:
            output.write(global_size(len(manifest)))
            head=tarfile.TarInfo('archive.json');head.size=8*1024*1024
            output.write(head.tobuf(format=tarfile.USTAR_FORMAT))
            output.write(manifest+b'\0'*(head.size-len(manifest)))
            for member,data in parts[1:]:
                output.write(global_size(len(data)))
                output.write(member.tobuf(format=tarfile.USTAR_FORMAT))
                output.write(data+b'\0'*((-len(data))%512))
            output.write(b'\0'*1024)
        quota=sum(len(data) for _,data in parts[1:])
        with self.assertRaises(ValueError):archive.restore_archive(target,self.base/'pax-out',self.runner,max_bytes=quota)
        self.assertFalse((self.base/'pax-out').exists())

    def test_only_one_local_path_extension_is_allowed(self):
        saved=self.make()
        for number,headers in enumerate([{'size':'1'},{'comment':'ignored'},{'path':'archive.json','comment':'ignored'}]):
            target=self.base/f'unsupported-pax-{number}.tar.gz'
            with tarfile.open(saved) as original,tarfile.open(target,'w:gz') as changed:
                for index,member in enumerate(original):
                    if index==0:member.pax_headers=headers
                    changed.addfile(member,io.BytesIO(original.extractfile(member).read()))
            with self.subTest(headers=headers),self.assertRaises(ValueError):
                archive.restore_archive(target,self.base/f'pax-out-{number}',self.runner)
        # Two chained path headers currently recurse and accept the archive.
        target=self.base/'chained.tar.gz'
        with tarfile.open(saved) as original,gzip.open(target,'wb') as output:
            for index,member in enumerate(original):
                if index==0:
                    extension=tarfile.TarInfo('header');extension.pax_headers={'path':'archive.json'}
                    blob=tarfile.TarInfo._create_pax_generic_header({'path':'archive.json'},tarfile.XHDTYPE,'utf-8')
                    output.write(blob);output.write(blob)
                data=original.extractfile(member).read()
                output.write(member.tobuf(format=tarfile.USTAR_FORMAT));output.write(data+b'\0'*((-len(data))%512))
            output.write(b'\0'*1024)
        with self.assertRaises(ValueError):archive.restore_archive(target,self.base/'chain-out',self.runner)

    def test_change_after_verification_before_snapshot_is_not_published(self):
        verify=archive.verify_match
        def changed(*args,**kwargs):
            inventory=verify(*args,**kwargs)
            summary=self.match/'summary.json';data=json.loads(summary.read_text())
            data['scores'][0]+=1;summary.write_text(json.dumps(data))
            return inventory
        with patch.object(archive,'verify_match',changed),self.assertRaises(ValueError):
            archive.archive_records(self.match,self.base/'late-mutation.tar.gz',self.runner)
        self.assertFalse((self.base/'late-mutation.tar.gz').exists())

    def test_experiment_change_after_collect_is_not_published(self):
        from contest_lib.experiment import prepare_suite,resume_suite
        root=self.base/'suite';prepare_suite([('main',self.ai)],[self.map],self.opponent,self.runner,root)
        resume_suite(root);collect=archive.collect
        for manifest in root.glob('versions/*/matches/*/attempt-*/match/manifest.json'):
            for name in ('map.json','initial.json','initial.txt','frames/000001.txt'):
                target=manifest.parent/name
                if not target.exists():target.write_bytes((self.match/name).read_bytes())
        def changed(*args,**kwargs):
            rows=collect(*args,**kwargs)
            target=args[0]/rows[0]['directory']/'summary.json'
            data=json.loads(target.read_text());data['scores'][0]+=1;target.write_text(json.dumps(data))
            return rows
        with patch.object(archive,'collect',changed),self.assertRaises(ValueError):
            archive.archive_records(root,self.base/'late-suite.tar.gz',self.runner)
        self.assertFalse((self.base/'late-suite.tar.gz').exists())

    def test_writer_long_paths_remain_compatible(self):
        from contest_lib.experiment import prepare_suite,resume_suite
        root=self.base/'long-suite';name='version_'+('x'*56)
        prepare_suite([(name,self.ai)],[self.map],self.opponent,self.runner,root);resume_suite(root)
        for manifest in root.glob('versions/*/matches/*/attempt-*/match/manifest.json'):
            for relative in ('map.json','initial.json','initial.txt','frames/000001.txt'):
                target=manifest.parent/relative
                if not target.exists():target.write_bytes((self.match/relative).read_bytes())
        saved=self.base/'long.tar.gz';archive.archive_records(root,saved,self.runner)
        with tarfile.open(saved) as tar:
            self.assertTrue(any('path' in m.pax_headers for m in tar))
        result=archive.restore_archive(saved,self.base/'long-restored',self.runner)
        self.assertEqual(result['matches'],2)

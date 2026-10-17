"""Archives must neither overwrite data nor extract hostile paths or file types."""
import copy
import hashlib
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

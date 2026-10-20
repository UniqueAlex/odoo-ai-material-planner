"""Delivery-specific checks. POSIX checks must run natively on Linux."""
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

pkg=types.ModuleType("mdic_delivery_test")
pkg.__path__=[str(Path(__file__).resolve().parents[1]/"material_delay_impact")]
sys.modules[pkg.__name__]=pkg
secure=importlib.import_module(pkg.__name__+".secure_config")
posix=importlib.import_module(pkg.__name__+".secure_posix")
Error=secure.AnalysisError
FAKE="synthetic-test-key-not-a-real-key"


class DispatchTests(unittest.TestCase):
    def test_windows_format_kept(self):
        if os.name!="nt":self.skipTest("Windows only")
        with tempfile.TemporaryDirectory() as folder:
            old=secure.WindowsStore(folder,"db",1)
            old.save("deepseek","deepseek-flash",FAKE)
            new=secure.Store(folder,"db",1)
            self.assertEqual(new.path,old.path)
            self.assertEqual(new.read()["key"],FAKE)
            new.remove()
            self.assertIsNone(old.read())

    def test_unsupported_os_fails_closed(self):
        with patch.object(secure.os,"name","unsupported"):
            with self.assertRaises(Error):secure.Store("unused","db",1)

    def test_invalid_configuration_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as folder:
            store=secure.Store(folder,"db",1)
            with self.assertRaises(Error):store.save("unsupported","model",FAKE)
            self.assertFalse(store.directory.exists())


@unittest.skipUnless(os.name=="posix","Requires real POSIX filesystem and flock")
class PosixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=secure.Store(self.temp.name,"db",1)
    def save(self):self.store.save("deepseek","deepseek-flash",FAKE)
    def test_roundtrip_private_encrypted(self):
        self.assertIsNone(self.store.read());self.save()
        self.assertEqual(self.store.read()["key"],FAKE)
        self.assertEqual(stat.S_IMODE(self.store.directory.stat().st_mode),0o700)
        for p in self.store.directory.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
            self.assertNotIn(FAKE.encode(),p.read_bytes())
    def test_scope_separation(self):
        self.save()
        for db,company in [("db",2),("db2",1)]:
            other=secure.Store(self.temp.name,db,company)
            self.assertIsNone(other.read())
    def test_swapped_ciphertext_rejected(self):
        self.save();other=secure.Store(self.temp.name,"db",2);other.save("deepseek","model",FAKE)
        for a,b in [(self.store.name,other.name),(self.store.key_name,other.key_name)]:
            (other.directory/b).write_bytes((self.store.directory/a).read_bytes())
        with self.assertRaises(Error):other.read()
    def test_tamper_rejected(self):
        self.save();p=self.store.directory/self.store.name;p.write_bytes(b"corrupted")
        with self.assertRaises(Error):self.store.read()
    def test_missing_key_not_silently_regenerated(self):
        self.save();(self.store.directory/self.store.key_name).unlink()
        with self.assertRaises(Error):self.store.read()
        with self.assertRaises(Error):self.save()
    def test_world_readable_refused(self):
        self.save();p=self.store.directory/self.store.name;p.chmod(0o644)
        with self.assertRaises(Error):self.store.read()
        with self.assertRaises(Error):self.save()
    def test_directory_symlink_refused(self):
        actual=Path(self.temp.name)/"actual";actual.mkdir()
        self.store.directory.symlink_to(actual,target_is_directory=True)
        with self.assertRaises(Error):self.save()
    def test_file_symlink_and_hardlink_refused(self):
        self.save();p=self.store.directory/self.store.name;backup=self.store.directory/"outside"
        p.rename(backup);p.symlink_to(backup)
        with self.assertRaises(Error):self.store.read()
        p.unlink();os.link(backup,p)
        with self.assertRaises(Error):self.store.read()
    def test_private_owner_required(self):
        self.save()
        with patch.object(posix.os,"geteuid",return_value=os.geteuid()+1):
            with self.assertRaises(Error):self.store.read()
    def test_rotation_and_remove(self):
        self.save();self.store.save("deepseek","new-model",FAKE+"-2")
        self.assertEqual(self.store.read()["key"],FAKE+"-2")
        self.store.remove();self.store.remove();self.assertIsNone(self.store.read())
        self.assertFalse((self.store.directory/self.store.key_name).exists())
    def test_parallel_processes_do_not_split_key_and_payload(self):
        import subprocess
        code="import runpy,sys;x=runpy.run_path(sys.argv[2]);s=x['secure'].Store(sys.argv[1],'db',1);s.save('deepseek','model',x['FAKE']);assert s.read()['key']==x['FAKE']"
        processes=[subprocess.Popen([sys.executable,"-c",code,self.temp.name,str(Path(__file__).resolve())]) for _ in range(6)]
        self.assertTrue(all(p.wait(timeout=30)==0 for p in processes))
        self.assertEqual(self.store.read()["key"],FAKE)

if __name__=="__main__":unittest.main()

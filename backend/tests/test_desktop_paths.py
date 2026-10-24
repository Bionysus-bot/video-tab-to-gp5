import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class DesktopPathsTests(unittest.TestCase):
    def test_desktop_log_streams_are_utf8_even_when_windows_defaults_to_gbk(self):
        with tempfile.TemporaryDirectory() as directory:
            code="import sys;sys.path.insert(0,"+repr(str(ROOT))+ ");from desktop.launcher import configure;from pathlib import Path;configure(Path("+repr(directory)+"));print('\\u2705 中文日志')"
            result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONIOENCODING':'gbk'},capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('中文日志',result.stdout.decode('utf-8'))
            self.assertIn('\u2705',result.stdout.decode('utf-8'))

    def test_data_override_does_not_write_into_program_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            code="from app.storage.manager import STORAGE_ROOT;import json;print(json.dumps(str(STORAGE_ROOT)))"
            result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PUJIAN_DATA_DIR':directory,'PYTHONPATH':str(ROOT/'backend')},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(Path(json.loads(result.stdout)),Path(directory)/'storage/projects')

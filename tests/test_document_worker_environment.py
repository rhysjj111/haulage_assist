"""Document workers retain required runtime paths without app credentials.

The native startup regression uses a private shared-library dependency, not a
mocked Popen/environment assertion. Without LD_LIBRARY_PATH the launcher cannot
start at all; with the minimal worker environment it execs the real interpreter
and all three bounded document workers read fictional reports successfully.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

import owner_test_support  # Configure the isolated app before package imports.
from fuel_xlsx_fixtures import transactions_xlsx
from payroll_pdf_fixtures import report_pdf
from silvey_pdf_fixtures import invoice_pdf
from haulage_app.document_processing import worker_environment
from haulage_app.fuel import silvey_processing, silvey_reader, xlsx_processing, xlsx_reader
from haulage_app.payslip import pdf_processing, pdf_reader


_BASE_ENVIRONMENT = {
    "PATH": os.defpath,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}


class DocumentWorkerEnvironmentTests(unittest.TestCase):
    def test_default_environment_discards_application_configuration_and_pythonpath(self):
        supplied = {
            "PATH": "/fictional/custom-path",
            "PYTHONPATH": "/fictional/import-path",
            "SECRET_KEY": "synthetic-credential-only",
            "DATABASE_URL": "synthetic-database-only",
            "OPENAI_API_KEY": "synthetic-key-only",
            "DOCUMENT_PRIVATE_SENTINEL": "synthetic-private-only",
        }
        with patch.dict(os.environ, supplied, clear=True):
            self.assertEqual(worker_environment(), _BASE_ENVIRONMENT)

    def test_nonempty_runtime_paths_are_preserved_without_other_python_settings(self):
        supplied = {
            "PYTHONHOME": "/fictional/runtime-home",
            "LD_LIBRARY_PATH": "/fictional/runtime-lib:/fictional/other-lib",
            "PYTHONPATH": "/fictional/import-path",
            "PYTHONSTARTUP": "/fictional/startup.py",
            "PYTHONUSERBASE": "/fictional/user-packages",
            "DB_URL": "synthetic-database-only",
        }
        with patch.dict(os.environ, supplied, clear=True):
            self.assertEqual(worker_environment(), {
                **_BASE_ENVIRONMENT,
                "PYTHONHOME": supplied["PYTHONHOME"],
                "LD_LIBRARY_PATH": supplied["LD_LIBRARY_PATH"],
            })

    def test_empty_runtime_paths_are_omitted_and_each_call_returns_independent_state(self):
        with patch.dict(os.environ, {"PYTHONHOME": "", "LD_LIBRARY_PATH": ""}, clear=True):
            first = worker_environment()
            first["PRIVATE_TEST_KEY"] = "synthetic-only"
            self.assertEqual(worker_environment(), _BASE_ENVIRONMENT)
            self.assertNotIn("PRIVATE_TEST_KEY", os.environ)


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("cc"),
                     "Native document-worker startup regression requires Linux and a C compiler")
class DocumentWorkerNativeStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="document-runtime-test-")
        cls.root = Path(cls.scratch.name)
        cls.library_directory = cls.root / "lib"
        cls.library_directory.mkdir()
        cls.python = sys.executable
        cls.python_home = sys.base_prefix
        cls.launcher = cls.root / "runtime-python"
        cls.library_name = "libdocument_probe_" + uuid.uuid4().hex + ".so"
        cls.library = cls.library_directory / cls.library_name
        cls.compiler = shutil.which("cc")
        try:
            library_source = cls.root / "probe.c"
            library_source.write_text("int document_runtime_probe(void) { return 42; }\n")
            cls.compile("-shared", "-fPIC", str(library_source), "-o", str(cls.library))
            launcher_source = cls.root / "launcher.c"
            launcher_source.write_text(
                "#include <stdlib.h>\n"
                "#include <string.h>\n"
                "#include <unistd.h>\n"
                "extern char **environ;\n"
                "extern int document_runtime_probe(void);\n"
                "static int allowed(const char *value) {\n"
                "  const char *keys[] = {\"PATH=\", \"PYTHONIOENCODING=\", "
                "\"PYTHONDONTWRITEBYTECODE=\", \"PYTHONHOME=\", \"LD_LIBRARY_PATH=\", NULL};\n"
                "  for (int i = 0; keys[i]; ++i)\n"
                "    if (!strncmp(value, keys[i], strlen(keys[i]))) return 1;\n"
                "  return 0;\n"
                "}\n"
                "int main(int argc, char **argv) {\n"
                "  if (document_runtime_probe() != 42) return 91;\n"
                "  for (char **entry = environ; *entry; ++entry)\n"
                "    if (!allowed(*entry)) return 92;\n"
                "  if (!getenv(\"PYTHONHOME\") || !*getenv(\"PYTHONHOME\")) return 93;\n"
                "  if (!getenv(\"LD_LIBRARY_PATH\") || !*getenv(\"LD_LIBRARY_PATH\")) return 94;\n"
                "  if (argc < 2) return 95;\n"
                "  argv[0] = " + json.dumps(cls.python) + ";\n"
                "  execv(argv[0], argv);\n"
                "  return 96;\n"
                "}\n"
            )
            # -L finds the library only at link time. No rpath/runpath is added,
            # so the OS loader requires LD_LIBRARY_PATH before main can run.
            cls.compile(str(launcher_source), "-L" + str(cls.library_directory),
                        "-l:" + cls.library_name, "-o", str(cls.launcher))
        except Exception:
            cls.scratch.cleanup()
            raise

    @classmethod
    def compile(cls, *arguments):
        result = subprocess.run(
            [cls.compiler, *arguments], capture_output=True, text=True, timeout=20,
            env={"PATH": os.defpath, "LC_ALL": "C"}, cwd=cls.root,
        )
        if result.returncode:
            raise RuntimeError("Native document-worker fixture compilation failed: " + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_launcher_really_requires_its_private_shared_library_before_startup(self):
        environment = {**_BASE_ENVIRONMENT, "PYTHONHOME": self.python_home}
        result = subprocess.run([str(self.launcher), "-c", "pass"], env=environment,
                                capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.library_name.encode(), result.stderr)
        self.assertIn(b"shared libraries", result.stderr)

    def test_all_real_document_workers_start_with_runtime_paths_but_without_parent_secrets(self):
        cases = (
            (pdf_processing, pdf_processing.read_payroll_pdf_isolated,
             pdf_reader.read_payroll_pdf, report_pdf()),
            (xlsx_processing, xlsx_processing.read_fuel_store_xlsx_isolated,
             xlsx_reader.read_fuel_store_transactions_xlsx, transactions_xlsx()),
            (silvey_processing, silvey_processing.read_silvey_pdf_isolated,
             silvey_reader.read_silvey_pdf, invoice_pdf()),
        )
        for processor, isolated_reader, direct_reader, document in cases:
            with self.subTest(worker=processor.__name__):
                expected = direct_reader(document)
                inherited_library_path = os.environ.get("LD_LIBRARY_PATH")
                library_path = str(self.library_directory)
                if inherited_library_path:
                    library_path += os.pathsep + inherited_library_path
                sentinel_environment = {
                    "PYTHONHOME": self.python_home,
                    "LD_LIBRARY_PATH": library_path,
                    "PYTHONPATH": "/fictional/private-python-path",
                    "SECRET_KEY": "synthetic-credential-only",
                    "DATABASE_URL": "synthetic-database-only",
                    "OPENAI_API_KEY": "synthetic-key-only",
                    "DOCUMENT_PRIVATE_SENTINEL": "synthetic-private-only",
                }
                with ExitStack() as guards:
                    guards.enter_context(patch.dict(os.environ, sentinel_environment))
                    guards.enter_context(patch.object(processor.sys, "executable", str(self.launcher)))
                    actual = isolated_reader(document)
                self.assertEqual(actual, expected)
                self.assertTrue(actual.rows)

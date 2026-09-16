"""
Phase 3 Tests: Built-in Tools and Verification Engine.
"""

import csv
import os
import tempfile
import pytest

from tools.builtin.filesystem import (
    read_file, write_file, rename_file, copy_file, move_file,
    delete_file, list_directory, create_directory, search_files, file_exists,
)
from tools.builtin.data import read_csv, inspect_csv, calculate_statistics, filter_dataframe, save_csv
from tools.builtin.system import system_info, process_info
from tools.builtin.testing import verify_file, verify_directory
from ecogent_experiment.verifier import verify_assertion, verify_all


# ============================================================
# Filesystem Tool Tests
# ============================================================


class TestFilesystemTools:
    """Test filesystem operations in a temp directory."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read_file(self):
        path = os.path.join(self.tmpdir, "test.txt")
        result = write_file(path, "Hello, World!")
        assert result["success"] is True

        result = read_file(path)
        assert result["success"] is True
        assert result["content"] == "Hello, World!"

    def test_read_nonexistent_file(self):
        result = read_file(os.path.join(self.tmpdir, "nope.txt"))
        assert result["success"] is False

    def test_rename_file(self):
        src = os.path.join(self.tmpdir, "old.txt")
        dst = os.path.join(self.tmpdir, "new.txt")
        write_file(src, "data")
        result = rename_file(src, dst)
        assert result["success"] is True
        assert os.path.exists(dst)
        assert not os.path.exists(src)

    def test_copy_file(self):
        src = os.path.join(self.tmpdir, "original.txt")
        dst = os.path.join(self.tmpdir, "copy.txt")
        write_file(src, "data")
        result = copy_file(src, dst)
        assert result["success"] is True
        assert os.path.exists(src)
        assert os.path.exists(dst)

    def test_move_file(self):
        src = os.path.join(self.tmpdir, "a.txt")
        subdir = os.path.join(self.tmpdir, "sub")
        dst = os.path.join(subdir, "a.txt")
        write_file(src, "data")
        result = move_file(src, dst)
        assert result["success"] is True
        assert not os.path.exists(src)
        assert os.path.exists(dst)

    def test_delete_file(self):
        path = os.path.join(self.tmpdir, "del.txt")
        write_file(path, "data")
        result = delete_file(path)
        assert result["success"] is True
        assert not os.path.exists(path)

    def test_list_directory(self):
        write_file(os.path.join(self.tmpdir, "a.txt"), "a")
        write_file(os.path.join(self.tmpdir, "b.txt"), "b")
        result = list_directory(self.tmpdir)
        assert result["success"] is True
        assert result["count"] == 2

    def test_create_directory(self):
        path = os.path.join(self.tmpdir, "newdir")
        result = create_directory(path)
        assert result["success"] is True
        assert os.path.isdir(path)

    def test_search_files(self):
        write_file(os.path.join(self.tmpdir, "a.csv"), "a")
        write_file(os.path.join(self.tmpdir, "b.txt"), "b")
        result = search_files(self.tmpdir, "*.csv", recursive=False)
        assert result["success"] is True
        assert result["count"] == 1

    def test_file_exists(self):
        path = os.path.join(self.tmpdir, "exists.txt")
        result = file_exists(path)
        assert result["exists"] is False

        write_file(path, "data")
        result = file_exists(path)
        assert result["exists"] is True
        assert result["type"] == "file"


# ============================================================
# Data Tool Tests
# ============================================================


class TestDataTools:
    """Test data processing operations."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.tmpdir, "test.csv")
        with open(self.csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "age", "score"])
            writer.writerow(["Alice", "30", "85.5"])
            writer.writerow(["Bob", "25", "92.0"])
            writer.writerow(["Charlie", "35", "78.3"])

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_csv(self):
        result = read_csv(self.csv_path)
        assert result["success"] is True
        assert result["row_count"] == 3
        assert result["columns"] == ["name", "age", "score"]

    def test_inspect_csv(self):
        result = inspect_csv(self.csv_path)
        assert result["success"] is True
        assert result["column_count"] == 3
        assert result["row_count"] == 3

    def test_calculate_statistics(self):
        result = calculate_statistics(self.csv_path, "score")
        assert result["success"] is True
        assert result["count"] == 3
        assert abs(result["mean"] - 85.267) < 0.1

    def test_filter_dataframe(self):
        result = filter_dataframe(self.csv_path, "age", "gt", 28)
        assert result["success"] is True
        assert result["filtered_count"] == 2  # Alice (30) and Charlie (35)

    def test_save_csv(self):
        rows = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        out_path = os.path.join(self.tmpdir, "out.csv")
        result = save_csv(out_path, rows)
        assert result["success"] is True
        assert result["row_count"] == 2

        # Verify the file
        read_result = read_csv(out_path)
        assert read_result["row_count"] == 2


# ============================================================
# System Tool Tests
# ============================================================


class TestSystemTools:
    def test_system_info(self):
        result = system_info()
        assert result["success"] is True
        assert "os" in result
        assert "cpu" in result
        assert result["ram_total_gb"] > 0

    def test_process_info(self):
        result = process_info()
        assert result["success"] is True
        assert result["total_count"] > 0


# ============================================================
# Verifier Tests
# ============================================================


class TestVerifier:
    """Test the assertion-based verification engine."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_exists_assertion(self):
        path = os.path.join(self.tmpdir, "test.txt")
        with open(path, "w") as f:
            f.write("data")

        result = verify_assertion({
            "assertion_type": "FILE_EXISTS",
            "target": path,
        })
        assert result["passed"] is True

    def test_file_not_exists_assertion(self):
        result = verify_assertion({
            "assertion_type": "FILE_NOT_EXISTS",
            "target": os.path.join(self.tmpdir, "nope.txt"),
        })
        assert result["passed"] is True

    def test_file_min_size_assertion(self):
        path = os.path.join(self.tmpdir, "big.txt")
        with open(path, "w") as f:
            f.write("x" * 100)

        result = verify_assertion({
            "assertion_type": "FILE_MIN_SIZE",
            "target": {"file_path": path, "min_size": 50},
        })
        assert result["passed"] is True

    def test_directory_exists_assertion(self):
        result = verify_assertion({
            "assertion_type": "DIRECTORY_EXISTS",
            "target": self.tmpdir,
        })
        assert result["passed"] is True

    def test_csv_column_exists_assertion(self):
        path = os.path.join(self.tmpdir, "test.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "age"])
            writer.writerow(["Alice", "30"])

        result = verify_assertion({
            "assertion_type": "CSV_COLUMN_EXISTS",
            "target": {"file_path": path, "column_name": "name"},
        })
        assert result["passed"] is True

    def test_text_contains_assertion(self):
        path = os.path.join(self.tmpdir, "doc.txt")
        with open(path, "w") as f:
            f.write("Hello World! This is a test.")

        result = verify_assertion({
            "assertion_type": "TEXT_CONTAINS",
            "target": {"file_path": path, "text": "World"},
        })
        assert result["passed"] is True

    def test_verify_all(self):
        path = os.path.join(self.tmpdir, "multi.txt")
        with open(path, "w") as f:
            f.write("test content")

        results = verify_all([
            {"assertion_type": "FILE_EXISTS", "target": path},
            {"assertion_type": "TEXT_CONTAINS", "target": {"file_path": path, "text": "test"}},
        ])
        assert results["all_passed"] is True
        assert results["passed"] == 2

    def test_unknown_assertion_type(self):
        result = verify_assertion({
            "assertion_type": "NONEXISTENT",
            "target": "anything",
        })
        assert result["passed"] is False

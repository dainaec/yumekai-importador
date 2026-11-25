import logging
from zipfile import ZipFile
from yumekai_importer import diagnostics


def test_events_errors_rotation_and_export_hide_credentials(tmp_path, app):
    logger = diagnostics.logger
    original = logger.handlers[:], logger.level, logger.propagate, diagnostics._log_path
    logger.handlers = []
    try:
        diagnostics.configure_logging(tmp_path)
        handler = logger.handlers[0]
        diagnostics.register_secret("test-super-secret")
        logger.info("test.action_saved products=3 password=test-super-secret")
        try:
            raise ValueError("authorization: Basic abc123 and password=test-super-secret")
        except ValueError:
            logger.exception("test.error")
        handler.flush()
        content = (tmp_path / "yumekai.log").read_text()
        assert "test.action_saved products=3" in content
        assert "Traceback" in content and "test.error" in content
        assert "test-super-secret" not in content and "abc123" not in content
        handler.maxBytes = 300
        for i in range(5):
            logger.info("test.rotation %s %s", i, "x" * 150)
        diagnostics.export_diagnostics(tmp_path / "diagnostico.zip")
        with ZipFile(tmp_path / "diagnostico.zip") as archive:
            assert "version.txt" in archive.namelist()
            assert "yumekai.log.1" in archive.namelist()
            assert all("test-super-secret" not in archive.read(name).decode() for name in archive.namelist())
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers, logger.level, logger.propagate, diagnostics._log_path = original

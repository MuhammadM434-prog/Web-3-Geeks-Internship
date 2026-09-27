import os
import tempfile

# Must run before any `app.*` module is imported anywhere in the test
# session, since app.tools builds its module-level DatabaseAdapter/
# CalendarService/EmailService singletons at import time.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import unittest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, make_engine, make_sessionmaker
from app.deps import get_catalog, get_keitaro, get_references, get_session, settings_dep
from app.main import app
from app.offers import OfferCatalog
from app.references import References

SETTINGS = Settings(
    _env_file=None, keitaro_api_key="x", campaign_prefix="test_mironov_",
    keitaro_domain_id=1, keitaro_group_id=2, keitaro_traffic_source_id=3,
)


class ApiCase(unittest.TestCase):
    def make_keitaro(self):
        raise NotImplementedError

    def setUp(self):
        self.kt = self.make_keitaro()
        self.engine = None
        catalog = OfferCatalog(self.kt)
        references = References(self.kt)

        async def session_override():
            if self.engine is None:
                self.engine = make_engine("sqlite+aiosqlite://", poolclass=StaticPool)
                async with self.engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            async with make_sessionmaker(self.engine)() as s:
                yield s

        app.dependency_overrides = {
            get_session: session_override,
            get_keitaro: lambda: self.kt,
            get_catalog: lambda: catalog,
            get_references: lambda: references,
            settings_dep: lambda: SETTINGS,
        }
        self.addCleanup(lambda: setattr(app, "dependency_overrides", {}))
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self._close)

    def _close(self):
        if self.engine is not None:
            self.client.portal.call(self.engine.dispose)
        self.client.__exit__(None, None, None)

    def ok(self, method, url, status=200, **kwargs):
        r = self.client.request(method, url, **kwargs)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

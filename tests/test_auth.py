import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.pool import StaticPool

from app import cli
from app.core import security
from app.core.config import Settings
from app.core.db import Base, make_engine, make_sessionmaker
from app.core.errors import AppError
from app.services import users
from tests.helpers import USERNAME, ApiCase
from tests.test_editor_api import EditorKeitaro
from tests.test_streams import CAMPAIGN_KT_ID

SECRET = "s3cret"
USER = security.CurrentUser(7, "dima")


class PasswordTest(unittest.TestCase):
    def test_roundtrip(self):
        stored = security.hash_password("correct horse")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn("correct horse", stored)
        self.assertTrue(security.verify_password("correct horse", stored))
        self.assertFalse(security.verify_password("wrong horse", stored))

    def test_salted(self):
        self.assertNotEqual(security.hash_password("same"), security.hash_password("same"))

    def test_malformed_hash(self):
        for stored in ("", "plain", "md5$1$2$3$aa$bb", "scrypt$x$8$1$zz$yy"):
            self.assertFalse(security.verify_password("x", stored))


class TokenTest(unittest.TestCase):
    def test_roundtrip(self):
        token = security.make_token(USER, SECRET, 60, now=1000)
        self.assertEqual(security.read_token(token, SECRET, now=1030), USER)

    def test_expired(self):
        token = security.make_token(USER, SECRET, 60, now=1000)
        self.assertIsNone(security.read_token(token, SECRET, now=1061))

    def test_tampered_or_foreign(self):
        token = security.make_token(USER, SECRET, 60, now=1000)
        payload, sig = token.rsplit(".", 1)
        forged = security.make_token(security.CurrentUser(1, "admin"), SECRET, 60, now=1000).rsplit(".", 1)[0]
        for bad in (None, "", "junk", f"{forged}.{sig}", f"{payload}.{sig[:-1]}x"):
            self.assertIsNone(security.read_token(bad, SECRET, now=1000))
        self.assertIsNone(security.read_token(token, "other", now=1000))

    def test_safe_next(self):
        self.assertEqual(security.safe_next("/campaigns/2?x=1"), "/campaigns/2?x=1")
        for bad in (None, "", "https://evil.com", "//evil.com", "/\\evil.com", "campaigns"):
            self.assertEqual(security.safe_next(bad), "/")


class UsersTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = make_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session = make_sessionmaker(self.engine)()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_create_and_authenticate(self):
        await users.create_user(self.session, "Dima", "long enough")
        self.assertEqual((await users.authenticate(self.session, "dima", "long enough")).username, "Dima")
        self.assertIsNone(await users.authenticate(self.session, "dima", "nope"))
        self.assertIsNone(await users.authenticate(self.session, "ghost", "long enough"))

    async def test_validation(self):
        with self.assertRaises(AppError):
            await users.create_user(self.session, "a", "short")
        with self.assertRaises(AppError):
            await users.create_user(self.session, "  ", "long enough")
        await users.create_user(self.session, "a", "long enough")
        with self.assertRaises(AppError):
            await users.create_user(self.session, "A", "long enough")

    async def test_inactive_user_cannot_login(self):
        user = await users.create_user(self.session, "b", "long enough")
        user.is_active = False
        await self.session.commit()
        self.assertIsNone(await users.authenticate(self.session, "b", "long enough"))

    async def test_set_password(self):
        await users.create_user(self.session, "c", "long enough")
        await users.set_password(self.session, "c", "brand new pass")
        self.assertIsNotNone(await users.authenticate(self.session, "c", "brand new pass"))
        self.assertIsNone(await users.authenticate(self.session, "c", "long enough"))


class CliTest(unittest.TestCase):
    def test_create_user_and_set_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = f"sqlite+aiosqlite:///{Path(tmp) / 'cli.db'}"

            async def init():
                engine = make_engine(url)
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                await engine.dispose()

            asyncio.run(init())
            settings = Settings(_env_file=None, database_url=url)
            with mock.patch.object(cli, "get_settings", return_value=settings), mock.patch("builtins.print"):
                self.assertEqual(cli.main(["create-user", "ops", "--password", "long enough"]), 0)
                self.assertEqual(cli.main(["create-user", "ops", "--password", "long enough"]), 1)
                self.assertEqual(cli.main(["set-password", "ops", "--password", "another one"]), 0)
                self.assertEqual(cli.main(["set-password", "ghost", "--password", "another one"]), 1)


class AccessTest(ApiCase):
    login_on_setup = False

    def make_keitaro(self):
        return EditorKeitaro()

    def test_anonymous_redirected_or_401(self):
        r = self.client.get("/campaigns/5?tab=x", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login?next=%2Fcampaigns%2F5%3Ftab%3Dx")
        self.assertEqual(self.client.get("/", follow_redirects=False).headers["location"], "/login?next=%2F")
        r = self.client.get("/api/campaigns")
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "Нужно войти в сервис"))
        self.assertEqual(self.client.post("/api/streams/1/push").status_code, 401)
        self.assertEqual(self.client.get("/docs", follow_redirects=False).status_code, 303)

    def test_public_paths(self):
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/static/app.css").status_code, 200)

    def test_wrong_password(self):
        r = self.login(password="nope")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Неверное имя пользователя или пароль", r.text)
        self.assertNotIn(security.COOKIE_NAME, self.client.cookies)
        self.assertEqual(self.client.get("/api/campaigns").status_code, 401)

    def test_login_logout(self):
        r = self.login(next_path="/offers")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/offers"))
        cookie = r.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertEqual(self.client.get("/api/campaigns").status_code, 200)
        page = self.client.get("/campaigns")
        self.assertIn(USERNAME, page.text)
        self.assertIn('action="/logout"', page.text)
        self.assertEqual(self.client.get("/login", follow_redirects=False).status_code, 303)

        r = self.client.post("/logout", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login"))
        self.assertEqual(self.client.get("/api/campaigns").status_code, 401)

    def test_open_redirect_blocked(self):
        r = self.login(next_path="https://evil.example")
        self.assertEqual(r.headers["location"], "/")

    def test_username_is_case_insensitive(self):
        self.assertEqual(self.login(username=USERNAME.upper()).status_code, 303)

    def test_journal_records_author(self):
        self.login()
        self.ok("POST", "/api/campaigns/import", json={"keitaro_id": CAMPAIGN_KT_ID})
        log = self.ok("GET", "/api/campaigns/1/log")
        self.assertTrue(all(e["username"] == USERNAME for e in log))


if __name__ == "__main__":
    unittest.main()

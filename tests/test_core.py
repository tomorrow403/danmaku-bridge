import base64
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from danmaku_bridge.ass import Comment, build_ass, load_comments, parse_comment  # noqa: E402
from danmaku_bridge.cli import main  # noqa: E402
from danmaku_bridge.client import MatchCache, sign  # noqa: E402
from danmaku_bridge.matcher import MediaFile, file_hash, pick_episode, scan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures")


class TestSignature(unittest.TestCase):
    def test_signature_matches_definition(self):
        app_id, secret, ts, path = "testapp", "s3cret", 1700000000, "/api/v2/match"
        raw = f"{app_id}{ts}{path}{secret}".encode()
        expected = base64.b64encode(hashlib.sha256(raw).digest()).decode()
        self.assertEqual(sign(app_id, secret, ts, path), expected)

    def test_signature_is_path_sensitive(self):
        a = sign("a", "b", 1, "/api/v2/match")
        b = sign("a", "b", 1, "/api/v2/comment/1")
        self.assertNotEqual(a, b)


class TestCommentParsing(unittest.TestCase):
    def test_parse_scroll(self):
        c = parse_comment({"p": "12.34,1,16777215,0", "m": "测试"})
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.seconds, 12.34)
        self.assertEqual(c.mode, 1)
        self.assertEqual(c.color, 0xFFFFFF)

    def test_parse_invalid(self):
        self.assertIsNone(parse_comment({"p": "bad", "m": "x"}))
        self.assertIsNone(parse_comment({"p": "1,1,0,0", "m": "   "}))


class TestAss(unittest.TestCase):
    def test_header_and_events(self):
        comments = [
            Comment(1.0, 1, 0xFFFFFF, "第一条"),
            Comment(2.0, 5, 0xFF0000, "顶部"),
            Comment(3.0, 4, 0x00FF00, "底部"),
        ]
        text, count = build_ass(comments, play_res_x=1280, play_res_y=720)
        self.assertEqual(count, 3)
        self.assertIn("PlayResX: 1280", text)
        self.assertIn("[V4+ Styles]", text)
        self.assertIn("Dialogue: 0,0:00:01.00", text)
        self.assertIn("\\an8", text)   # 顶部弹幕
        self.assertIn("\\an2", text)   # 底部弹幕
        self.assertEqual(text.count("Dialogue:"), 3)

    def test_escape_braces(self):
        text, _ = build_ass([Comment(1.0, 1, 0xFFFFFF, "带{控制符}的文本")])
        self.assertNotIn("{控制符}", text)
        self.assertIn("(控制符)", text)

    def test_duplicate_removed(self):
        dup = [Comment(5.0, 1, 0xFFFFFF, "重复"), Comment(5.0, 1, 0xFFFFFF, "重复")]
        text, count = build_ass(dup)
        self.assertEqual(count, 1)


class TestMatcher(unittest.TestCase):
    def test_scan_filters_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["a.mkv", "b.MP4", "c.txt", ".hidden.mkv"]:
                with open(os.path.join(tmp, name), "wb") as fh:
                    fh.write(b"x")
            files = scan(tmp)
            names = sorted(f.name for f in files)
            self.assertEqual(names, ["a.mkv", "b.MP4"])

    def test_hash_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mkv")
            with open(path, "wb") as fh:
                fh.write(b"abc" * 1000)
            head = file_hash(path, "head16m")
            full = file_hash(path, "full")
            self.assertEqual(len(head), 32)
            self.assertEqual(head, full)  # 小于 16MB 时两者一致
            self.assertIsNone(file_hash(path, "none"))

    def test_pick_episode(self):
        self.assertIsNone(pick_episode({"isMatched": False, "matches": []}))
        got = pick_episode({"isMatched": True, "matches": [{"episodeId": 1}]})
        self.assertEqual(got["episodeId"], 1)


class TestCache(unittest.TestCase):
    def test_roundtrip_and_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cache.json")
            cache = MatchCache(path, ttl=3600)
            cache.put("a.mkv", 100, {"isMatched": True})
            self.assertIsNotNone(MatchCache(path, ttl=3600).get("a.mkv", 100))
            self.assertIsNone(MatchCache(path, ttl=-1).get("a.mkv", 100))


class TestEndToEndMock(unittest.TestCase):
    """离线跑通完整链路：扫描 → 识别（固定响应）→ 取弹幕 → 生成 .ass。"""

    def test_run_generates_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "示例作品 - 第01话.mkv")
            with open(media, "wb") as fh:
                fh.write(b"\x00" * 2048)
            cache = os.path.join(tmp, "cache.json")

            code = main([
                "run", tmp,
                "--mock", "--mock-dir", FIXTURES,
                "--cache", cache,
            ])
            self.assertEqual(code, 0)

            ass_path = os.path.splitext(media)[0] + ".ass"
            self.assertTrue(os.path.exists(ass_path))
            with open(ass_path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("[Script Info]", body)
            self.assertGreaterEqual(body.count("Dialogue:"), 50)

            # 第二次运行应跳过已存在字幕
            code2 = main(["run", tmp, "--mock", "--mock-dir", FIXTURES, "--cache", cache])
            self.assertEqual(code2, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
